"""A-stock extended data toolkit — research, news, announcements, capital flow, signals, and fundamentals.

Integrates the open-source simonlin1212/a-stock-data (V3.2.2, 4.8k stars) into
vibe-trading. Provides 27 endpoints across 7 layers covering non-OHLCV A-share data
that the existing loaders (tushare, mootdx, baostock, tencent, akshare) do not
provide: 研报, 新闻, 公告, 资金面, 信号, 基础数据, and 估值.

OHLCV 行情 data remains the responsibility of the existing DataLoaderProtocol
loaders (tushare → mootdx → baostock → tencent → akshare fallback chain).

Authenticated sources:
  - All endpoints are free except iwencai, which requires IWENCAI_API_KEY.
  - Eastmoney is throttled (≥1s between calls) to avoid IP bans.

Dependencies:
  - requests (already in project)
  - pandas (already in project)
  - mootdx (optional, already in project as ashare extra)
  - stockstats (optional, for full_valuation)
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)

_EM_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))

_IWENCAI_API_KEY = os.environ.get("IWENCAI_API_KEY", "")
_IWENCAI_BASE_URL = os.environ.get(
    "IWENCAI_BASE_URL", "https://openapi.iwencai.com",
)

_CNINFO_ANN_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_CNINFO_ORGID_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"

# Module-level cache for cninfo orgId mapping (downloaded once).
_cninfo_orgid_cache: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def get_prefix(code: str) -> str:
    """Map a 6-digit stock code to its market prefix (sh/sz/bj).

    Args:
        code: 6-digit stock code, e.g. ``"600519"`` or ``"000001"``.
            Also accepts formats like ``"600519.SH"`` — the suffix is stripped.

    Returns:
        ``"sh"``, ``"sz"``, or ``"bj"``.
    """
    # Strip suffix if present (600519.SH → 600519)
    code = code.split(".")[0].strip()
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


def _strip_suffix(code: str) -> str:
    """Return the 6-digit code portion, stripping any .SZ/.SH/.BJ suffix."""
    return code.split(".")[0].strip()


# ---------------------------------------------------------------------------
# Eastmoney throttled session
# ---------------------------------------------------------------------------

_EM_SESSION = requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
_em_last_call: list[float] = [0.0]


def em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    **kwargs: Any,
) -> requests.Response:
    """Throttled GET request to Eastmoney with session reuse.

    Enforces a minimum interval (``EM_MIN_INTERVAL``) between calls plus
    random jitter (0.1–0.5s) to avoid IP bans from Eastmoney's CDN.

    Args:
        url: Target URL.
        params: Query parameters.
        headers: Additional headers (merged with session defaults).
        timeout: Request timeout in seconds.
        **kwargs: Additional keyword arguments passed to ``requests.Session.get``.

    Returns:
        The ``requests.Response`` object.
    """
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        resp = _EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
        return resp
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """Query Eastmoney DataCenter API and return result rows.

    Args:
        report_name: Eastmoney report name (e.g. ``"RPT_CUSTOM_WEB_BROKERPENNY"``).
        columns: Column filter (default ``"ALL"``).
        filter_str: Eastmoney filter expression.
        page_size: Rows per page.
        sort_columns: Sort column name.
        sort_types: Sort direction (``"-1"`` descending, ``"1"`` ascending).

    Returns:
        List of row dicts from the ``result.data`` field, or empty list.
    """
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = em_get(_EM_DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception as exc:
        logger.warning("eastmoney_datacenter(%s) failed: %s", report_name, exc)
    return []


# ---------------------------------------------------------------------------
# Layer 2: 研报 (Research Reports)
# ---------------------------------------------------------------------------


def eastmoney_reports(code: str, max_pages: int = 5) -> list[dict]:
    """Fetch analyst research reports for a stock from Eastmoney.

    Args:
        code: 6-digit stock code (e.g. ``"600519"``).
        max_pages: Maximum number of pages to fetch (default 5).

    Returns:
        List of report dicts with keys like ``title``, ``reportDate``,
        ``orgSname``, ``researcher``, ``emCode``, etc.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    secid = f"0.{code6}" if prefix == "sz" else f"1.{code6}"
    results: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "reportName": "RPT_CUSTOM_WEB_BROKERPENNY",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{code6}")',
            "pageNumber": str(page),
            "pageSize": "50",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        }
        try:
            r = em_get(_EM_DATACENTER_URL, params=params, timeout=15)
            d = r.json()
            data = d.get("result", {}).get("data", [])
            if not data:
                break
            results.extend(data)
        except Exception as exc:
            logger.warning("eastmoney_reports page %d failed: %s", page, exc)
            break
    return results


def download_pdf(record: dict, target_dir: str = "./reports") -> str | None:
    """Download a research report PDF from Eastmoney.

    Args:
        record: A report dict from :func:`eastmoney_reports` that contains
            ``infoCode`` or ``researchReportId`` and ``title`` keys.
        target_dir: Directory to save the PDF (created if missing).

    Returns:
        Path to the saved PDF file, or ``None`` on failure.
    """
    info_code = record.get("infoCode") or record.get("researchReportId", "")
    if not info_code:
        logger.warning("download_pdf: no infoCode in record")
        return None
    url = f"https://data.eastmoney.com/report/zw_industry.jshtml?infocode={info_code}"
    pdf_url = (
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
    )
    out_dir = Path(target_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    title = record.get("title", info_code).replace("/", "_").replace("\\", "_")
    out_path = out_dir / f"{title}.pdf"
    try:
        resp = requests.get(pdf_url, headers={"User-Agent": _UA}, timeout=30)
        if resp.status_code == 200:
            out_path.write_bytes(resp.content)
            return str(out_path)
        else:
            logger.warning("download_pdf: HTTP %d for %s", resp.status_code, info_code)
    except Exception as exc:
        logger.warning("download_pdf failed: %s", exc)
    return None


def ths_eps_forecast(code: str) -> pd.DataFrame:
    """Fetch consensus EPS forecast from 10jqka (同花顺).

    Args:
        code: 6-digit stock code.

    Returns:
        DataFrame with columns like ``reportDate``, ``forecastEps``, etc.
        Empty DataFrame on failure.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    url = f"https://basic.10jqka.com.cn/{prefix}{code6}/finance.html"
    headers = {
        "User-Agent": _UA,
        "Referer": f"https://basic.10jqka.com.cn/{prefix}{code6}/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "gbk"
        tables = pd.read_html(resp.text)
        for table in tables:
            if "预测每股收益" in table.to_string() or "EPS" in table.to_string():
                return table
        # Fallback: return last table if any
        if tables:
            return tables[-1]
    except Exception as exc:
        logger.warning("ths_eps_forecast(%s) failed: %s", code6, exc)
    return pd.DataFrame()


def _claw_headers(call_type: str = "normal") -> dict:
    """Build X-Claw authentication headers for iwencai API calls.

    Requires the ``IWENCAI_API_KEY`` environment variable.
    """
    api_key = _IWENCAI_API_KEY
    if not api_key:
        raise EnvironmentError(
            "IWENCAI_API_KEY is required for iwencai calls. "
            "Set it via environment variable or .env file."
        )
    return {
        "X-Claw-Api-Key": api_key,
        "User-Agent": "a-stock-data/3.2",
        "Content-Type": "application/json",
    }


def iwencai_search(query: str, channel: str = "report", size: int = 50) -> list[dict]:
    """Semantic search on iwencai (问财) — NL query for research reports.

    Requires ``IWENCAI_API_KEY`` environment variable.

    Args:
        query: Natural language query (e.g. ``"新能源车市盈率最低的10只股票"``).
        channel: Search channel (``"report"`` or ``"stock"``).
        size: Maximum results to return.

    Returns:
        List of result dicts, or empty list on failure.
    """
    if not _IWENCAI_API_KEY:
        logger.warning("iwencai_search: IWENCAI_API_KEY not set, skipping")
        return []
    url = f"{_IWENCAI_BASE_URL}/openapi/search"
    payload = {"query": query, "channel": channel, "size": size}
    try:
        resp = requests.post(url, json=payload, headers=_claw_headers(), timeout=20)
        data = resp.json()
        if data.get("data") and data["data"].get("result"):
            return data["data"]["result"]
    except Exception as exc:
        logger.warning("iwencai_search failed: %s", exc)
    return []


def iwencai_query(query: str, page: int = 1, limit: int = 50) -> list[dict]:
    """Structured data query on iwencai (问财).

    Requires ``IWENCAI_API_KEY`` environment variable.

    Args:
        query: Structured query string.
        page: Page number.
        limit: Rows per page.

    Returns:
        List of row dicts, or empty list on failure.
    """
    if not _IWENCAI_API_KEY:
        logger.warning("iwencai_query: IWENCAI_API_KEY not set, skipping")
        return []
    url = f"{_IWENCAI_BASE_URL}/openapi/query"
    payload = {"query": query, "page": page, "limit": limit}
    try:
        resp = requests.post(url, json=payload, headers=_claw_headers(), timeout=20)
        data = resp.json()
        if data.get("data") and data["data"].get("result"):
            return data["data"]["result"]
    except Exception as exc:
        logger.warning("iwencai_query failed: %s", exc)
    return []


def dedup_articles(articles: list[dict]) -> list[dict]:
    """Deduplicate articles by title, keeping the most recent.

    Args:
        articles: List of article dicts with a ``title`` key.

    Returns:
        Deduplicated list.
    """
    seen: set[str] = set()
    result: list[dict] = []
    for art in articles:
        title = art.get("title", "")
        if title and title not in seen:
            seen.add(title)
            result.append(art)
    return result


# ---------------------------------------------------------------------------
# Layer 3: 信号 (Signals)
# ---------------------------------------------------------------------------


def ths_hot_reason(date: str | None = None) -> pd.DataFrame:
    """Fetch daily strong-reason stocks from 10jqka (同花顺人气榜).

    Args:
        date: Date string ``"YYYY-MM-DD"`` (default: today).

    Returns:
        DataFrame with stock code, name, reason/strong tags.
        Empty DataFrame on failure.
    """
    if date is None:
        date = pd.Timestamp.now().strftime("%Y-%m-%d")
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    params = {"page": "1", "limit": "200", "field": "199112,10,9001,330323,330324,330325,9002,330326,133971,133970,1968584,3475914,9003,9004", "filter_date": date}
    headers = {"User-Agent": _UA, "Referer": "https://www.10jqka.com.cn/"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json().get("data", {})
        if data and data.get("list"):
            return pd.DataFrame(data["list"])
    except Exception as exc:
        logger.warning("ths_hot_reason(%s) failed: %s", date, exc)
    return pd.DataFrame()


def hsgt_realtime() -> pd.DataFrame:
    """Fetch real-time northbound capital flow (沪港通 + 深港通).

    Returns:
        DataFrame with columns like ``date``, ``hgt``, ``sgt``, ``north``.
        Empty DataFrame on failure.
    """
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_MUTUAL_DEAL_NORTHBOUND",
        "columns": "ALL",
        "filter": '',
        "pageNumber": "1",
        "pageSize": "1",
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = em_get(url, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return pd.DataFrame(d["result"]["data"])
    except Exception as exc:
        logger.warning("hsgt_realtime() failed: %s", exc)
    return pd.DataFrame()


def _northbound_cache_path() -> Path:
    """Return the path for northbound flow CSV cache."""
    cache_dir = Path.home() / ".vibe-trading" / "cache" / "northbound"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "history.csv"


def _save_northbound_snapshot(date: str, hgt: float, sgt: float) -> None:
    """Append a daily northbound snapshot to the local CSV cache."""
    path = _northbound_cache_path()
    header = not path.exists()
    import csv
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(["date", "hgt", "sgt"])
        writer.writerow([date, hgt, sgt])


def _load_northbound_history(n: int = 20) -> pd.DataFrame:
    """Load the last *n* northbound snapshots from local cache.

    Returns:
        DataFrame with ``date``, ``hgt``, ``sgt`` columns.
        Empty DataFrame if no cache exists.
    """
    path = _northbound_cache_path()
    if not path.exists():
        return pd.DataFrame(columns=["date", "hgt", "sgt"])
    df = pd.read_csv(path, encoding="utf-8")
    return df.tail(n).reset_index(drop=True)


def eastmoney_concept_blocks(code: str) -> dict:
    """Fetch concept/sector blocks for a stock from Eastmoney.

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with keys ``"concepts"`` (list of dicts with name, code) and
        ``"industries"`` (list of dicts).
    """
    code6 = _strip_suffix(code)
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_CUSTOM_WEB_BKZC",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code6}")',
        "pageSize": "50",
        "source": "WEB",
        "client": "WEB",
    }
    result: dict[str, list] = {"concepts": [], "industries": []}
    try:
        r = em_get(url, params=params, timeout=15)
        d = r.json()
        data = d.get("result", {}).get("data", [])
        for row in data:
            entry = {"name": row.get("BK_NAME", ""), "code": row.get("BK_CODE", "")}
            if row.get("BK_TYPE") == "0":
                result["concepts"].append(entry)
            else:
                result["industries"].append(entry)
    except Exception as exc:
        logger.warning("eastmoney_concept_blocks(%s) failed: %s", code6, exc)
    return result


def eastmoney_fund_flow_minute(code: str) -> list[dict]:
    """Fetch intraday minute-level capital flow from Eastmoney.

    Args:
        code: 6-digit stock code.

    Returns:
        List of dicts with minute-level flow data.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    market_id = "1" if prefix == "sh" else "0"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": f"{market_id}.{code6}",
        "klt": "1",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "lmt": "0",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=15)
        d = r.json().get("data", {})
        klines = d.get("klines", [])
        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 8:
                result.append({
                    "time": parts[0],
                    "main_net_inflow": float(parts[1]),
                    "small_net_inflow": float(parts[2]),
                    "medium_net_inflow": float(parts[3]),
                    "large_net_inflow": float(parts[4]),
                    "super_net_inflow": float(parts[5]),
                })
        return result
    except Exception as exc:
        logger.warning("eastmoney_fund_flow_minute(%s) failed: %s", code6, exc)
    return []


def dragon_tiger_board(code: str, trade_date: str, look_back: int = 30) -> dict:
    """Fetch dragon-tiger board (龙虎榜) detail for a stock.

    Args:
        code: 6-digit stock code.
        trade_date: Trade date ``"YYYY-MM-DD"``.
        look_back: Number of days to look back if exact date has no data.

    Returns:
        Dict with ``"details"`` (list of entry dicts) and ``"code"``.
    """
    code6 = _strip_suffix(code)
    filter_str = f'(SECURITY_CODE="{code6}")(TRADE_DATE=\'{trade_date}\')'
    return {
        "code": code6,
        "details": eastmoney_datacenter(
            "RPT_DAILYBOARD_DETAILS",
            filter_str=filter_str,
            page_size=20,
        ),
    }


def daily_dragon_tiger(trade_date: str | None = None, min_net_buy: float | None = None) -> dict:
    """Fetch market-wide dragon-tiger board for a specific date.

    Args:
        trade_date: Date ``"YYYY-MM-DD"`` (default: latest available).
        min_net_buy: Only return entries with net buy >= this value (in 亿元).

    Returns:
        Dict with ``"data"`` (list of entry dicts).
    """
    filter_parts: list[str] = []
    if trade_date:
        filter_parts.append(f"TRADE_DATE='{trade_date}'")
    filter_str = f'({")(".join(filter_parts)})' if filter_parts else ""
    data = eastmoney_datacenter(
        "RPT_DAILYBOARD_DETAILS",
        filter_str=filter_str,
        page_size=50,
        sort_columns="NET_BUY",
        sort_types="-1",
    )
    if min_net_buy is not None:
        data = [r for r in data if float(r.get("NET_BUY", 0)) >= min_net_buy]
    return {"data": data}


def lockup_expiry(code: str, trade_date: str, forward_days: int = 90) -> dict:
    """Fetch upcoming lockup expiry events for a stock.

    Args:
        code: 6-digit stock code.
        trade_date: Reference date ``"YYYY-MM-DD"``.
        forward_days: Number of days to look ahead from ``trade_date``.

    Returns:
        Dict with ``"data"`` (list of lockup event dicts).
    """
    code6 = _strip_suffix(code)
    end_date = pd.Timestamp(trade_date) + pd.Timedelta(days=forward_days)
    filter_str = (
        f'(SECURITY_CODE="{code6}")'
        f'(END_DATE>="{trade_date}")'
        f'(END_DATE<="{end_date.strftime("%Y-%m-%d")}")'
    )
    return {
        "code": code6,
        "data": eastmoney_datacenter(
            "RPT_SHAREBUS_UNLOCK",
            filter_str=filter_str,
            page_size=20,
        ),
    }


def industry_comparison(top_n: int = 20) -> dict:
    """Fetch industry sector comparison from Eastmoney.

    Args:
        top_n: Number of top industries to return.

    Returns:
        Dict with ``"data"`` — list of industry dicts with performance metrics.
    """
    return {
        "data": eastmoney_datacenter(
            "RPT_INDUSTRY_BOARD",
            columns="ALL",
            page_size=top_n,
            sort_columns="CHANGE_RATE",
            sort_types="-1",
        ),
    }


# ---------------------------------------------------------------------------
# Layer 4: 资金面 / 筹码 (Capital / Shares)
# ---------------------------------------------------------------------------


def margin_trading(code: str, page_size: int = 30) -> list[dict]:
    """Fetch margin trading (融资融券) data for a stock.

    Args:
        code: 6-digit stock code.
        page_size: Number of records to return.

    Returns:
        List of margin-trading dicts.
    """
    code6 = _strip_suffix(code)
    return eastmoney_datacenter(
        "RPT_RZRQ_LSHJ",
        filter_str=f'(SECURITY_CODE="{code6}")',
        page_size=page_size,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )


def block_trade(code: str, page_size: int = 20) -> list[dict]:
    """Fetch block trade (大宗交易) data for a stock.

    Args:
        code: 6-digit stock code.
        page_size: Number of records to return.

    Returns:
        List of block-trade dicts.
    """
    code6 = _strip_suffix(code)
    return eastmoney_datacenter(
        "RPT_BLOCKTRADE_DETAILS",
        filter_str=f'(SECURITY_CODE="{code6}")',
        page_size=page_size,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )


def holder_num_change(code: str, page_size: int = 10) -> list[dict]:
    """Fetch shareholder count change (股东人数变化) data.

    Args:
        code: 6-digit stock code.
        page_size: Number of records to return.

    Returns:
        List of holder-count dicts.
    """
    code6 = _strip_suffix(code)
    return eastmoney_datacenter(
        "RPT_SHHOLDER_NUM_CHANGE",
        filter_str=f'(SECURITY_CODE="{code6}")',
        page_size=page_size,
        sort_columns="END_DATE",
        sort_types="-1",
    )


def dividend_history(code: str, page_size: int = 20) -> list[dict]:
    """Fetch dividend (分红) history for a stock.

    Args:
        code: 6-digit stock code.
        page_size: Number of records to return.

    Returns:
        List of dividend dicts.
    """
    code6 = _strip_suffix(code)
    return eastmoney_datacenter(
        "RPT_DIVIDEND_INFO",
        filter_str=f'(SECURITY_CODE="{code6}")',
        page_size=page_size,
        sort_columns="REPORT_DATE",
        sort_types="-1",
    )


def stock_fund_flow_120d(code: str) -> list[dict]:
    """Fetch 120-day capital flow data for a stock.

    Args:
        code: 6-digit stock code.

    Returns:
        List of daily fund-flow dicts covering ~120 trading days.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    market_id = "1" if prefix == "sh" else "0"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{market_id}.{code6}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "lmt": "0",
        "klt": "101",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=15)
        d = r.json().get("data", {})
        klines = d.get("klines", [])
        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                result.append({
                    "date": parts[0],
                    "main_net_inflow": float(parts[1]),
                    "small_net_inflow": float(parts[2]),
                    "medium_net_inflow": float(parts[3]),
                    "large_net_inflow": float(parts[4]),
                    "super_net_inflow": float(parts[5]),
                })
        return result
    except Exception as exc:
        logger.warning("stock_fund_flow_120d(%s) failed: %s", code6, exc)
    return []


# ---------------------------------------------------------------------------
# Layer 5: 新闻 (News)
# ---------------------------------------------------------------------------


def eastmoney_stock_news(code: str, page_size: int = 20) -> list[dict]:
    """Fetch stock-specific news from Eastmoney.

    Args:
        code: 6-digit stock code.
        page_size: Number of news items to return.

    Returns:
        List of news dicts with ``title``, ``url``, ``publish_time``, etc.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    secid = f"0.{code6}" if prefix == "sz" else f"1.{code6}"
    url = "https://search-api.eastmoney.com/search/jsonp"
    params = {
        "cb": "jQuery_callback",
        "param": json.dumps({
            "uid": "",
            "keyword": code6,
            "type": ["news"],
            "client": "web",
            "secid": secid,
            "page_index": 1,
            "page_size": page_size,
        }, ensure_ascii=False),
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=15)
        text = r.text
        # Strip JSONP callback wrapper
        if "(" in text and text.endswith(")"):
            text = text[text.index("(") + 1 : text.rindex(")")]
        data = json.loads(text)
        items = data.get("result", {}).get("news", {}).get("list", [])
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "publish_time": item.get("publish_time", ""),
                "source": item.get("source", ""),
                "content": item.get("content", ""),
            }
            for item in items
        ]
    except Exception as exc:
        logger.warning("eastmoney_stock_news(%s) failed: %s", code6, exc)
    return []


def eastmoney_global_news(page_size: int = 50) -> list[dict]:
    """Fetch global 7×24 finance news from Eastmoney.

    Args:
        page_size: Number of news items to return.

    Returns:
        List of news dicts.
    """
    url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
    params = {
        "client": "web",
        "biz": "20001",
        "column": "20002",
        "order": "1",
        "needInteract": "0",
        "page_index": "1",
        "page_size": str(page_size),
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("list", [])
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "publish_time": item.get("showTime", ""),
                "source": item.get("source", ""),
            }
            for item in items
        ]
    except Exception as exc:
        logger.warning("eastmoney_global_news() failed: %s", exc)
    return []


# ---------------------------------------------------------------------------
# Layer 6: 基础数据 (Base Data / Fundamentals)
# ---------------------------------------------------------------------------


def eastmoney_stock_info(code: str) -> dict:
    """Fetch stock basic info (industry, shares, market cap) from Eastmoney.

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with stock info keys (``industry``, ``totalShares``, etc.),
        or empty dict on failure.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    secid = f"0.{code6}" if prefix == "sz" else f"1.{code6}"
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_CUSTOM_STOCK_BASICINFO",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code6}")',
        "pageSize": "1",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = em_get(url, params=params, timeout=15)
        d = r.json()
        data = d.get("result", {}).get("data", [])
        if data:
            return data[0]
    except Exception as exc:
        logger.warning("eastmoney_stock_info(%s) failed: %s", code6, exc)
    return {}


def sina_financial_report(code: str, report_type: str = "lrb", num: int = 8) -> list[dict]:
    """Fetch financial statements from Sina Finance.

    Args:
        code: 6-digit stock code.
        report_type: One of ``"lrb"`` (income statement), ``"fzb"`` (balance sheet),
            ``"llb"`` (cash flow statement).
        num: Number of recent reports to return (default 8).

    Returns:
        List of report dicts.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    url = f"https://money.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{code6}/ctrlpart/displaytype/4/{report_type}"
    headers = {"User-Agent": _UA, "Referer": f"https://money.finance.sina.com.cn/"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "gbk"
        tables = pd.read_html(resp.text, flavor="html5lib")
        for table in tables:
            # The first table with enough columns is likely the financial report
            if len(table.columns) >= 3:
                df = table.iloc[:num]
                return df.to_dict(orient="records")
    except Exception as exc:
        logger.warning("sina_financial_report(%s, %s) failed: %s", code6, report_type, exc)
    return []


# ---------------------------------------------------------------------------
# Layer 7: 公告 (Announcements)
# ---------------------------------------------------------------------------


def _cninfo_ts_to_date(ts: int | str) -> str:
    """Convert cninfo Unix-millisecond timestamp to date string."""
    try:
        ts_int = int(ts) // 1000
        return pd.Timestamp(ts_int, unit="s").strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def _cninfo_orgid(code: str) -> str:
    """Resolve a 6-digit stock code to its cninfo orgId (with module-level cache).

    Downloads the orgId mapping from cninfo on first call, then caches it.
    """
    global _cninfo_orgid_cache
    code6 = _strip_suffix(code)

    if _cninfo_orgid_cache is not None:
        return _cninfo_orgid_cache.get(code6, "")

    try:
        resp = requests.get(
            _CNINFO_ORGID_URL,
            headers={"User-Agent": _UA},
            timeout=15,
        )
        data = resp.json()
        cache: dict[str, str] = {}
        for item in data.get("stockList", data if isinstance(data, list) else []):
            stock_code = item.get("code", item.get("SECURITY_CODE", ""))
            org_id = item.get("orgId", item.get("ORG_ID", ""))
            if stock_code and org_id:
                cache[stock_code] = org_id
        _cninfo_orgid_cache = cache
    except Exception as exc:
        logger.warning("_cninfo_orgid() failed to download mapping: %s", exc)
        _cninfo_orgid_cache = {}

    return _cninfo_orgid_cache.get(code6, "")


def cninfo_announcements(code: str, page_size: int = 30) -> list[dict]:
    """Fetch announcements (公告) from cninfo.org.cn for a stock.

    Args:
        code: 6-digit stock code.
        page_size: Number of announcements to return.

    Returns:
        List of announcement dicts with ``title``, ``annDate``, ``url``, etc.
    """
    code6 = _strip_suffix(code)
    org_id = _cninfo_orgid(code6)
    if not org_id:
        logger.warning("cninfo_announcements(%s): could not resolve orgId", code6)
        return []

    url = _CNINFO_ANN_URL
    payload = {
        "pageNum": 1,
        "pageSize": page_size,
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": [code6 + "," + org_id],
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
    }
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=15)
        d = resp.json()
        announcements = d.get("announcements", [])
        result = []
        for ann in announcements:
            result.append({
                "title": ann.get("announcementTitle", ann.get("title", "")),
                "annDate": _cninfo_ts_to_date(ann.get("announcementTime", "")),
                "url": f"https://static.cninfo.com.cn/{ann.get('adjunctUrl', '')}",
                "column": ann.get("column", ""),
            })
        return result
    except Exception as exc:
        logger.warning("cninfo_announcements(%s) failed: %s", code6, exc)
    return []


# ---------------------------------------------------------------------------
# Valuation helpers
# ---------------------------------------------------------------------------


def forward_pe(price: float, eps_forecast: float) -> float:
    """Calculate forward (predicted) PE ratio.

    Args:
        price: Current stock price.
        eps_forecast: Forecasted earnings per share.

    Returns:
        Forward PE ratio, or ``float("inf")`` if eps_forecast is zero/negative.
    """
    if not eps_forecast or eps_forecast <= 0:
        return float("inf")
    return price / eps_forecast


def pe_digestion(current_pe: float, cagr: float, target_pe: float = 30) -> float:
    """Calculate how many years it takes for PE to be "digested" by growth.

    Args:
        current_pe: Current PE ratio.
        cagr: Compound annual growth rate (as a decimal, e.g. 0.20 for 20%).
        target_pe: Target PE ratio to digest down to (default 30).

    Returns:
        Number of years, or ``float("inf")`` if growth is non-positive.
    """
    if not cagr or cagr <= 0 or current_pe <= 0:
        return float("inf")
    import math
    if current_pe <= target_pe:
        return 0.0
    return math.log(current_pe / target_pe) / math.log(1 + cagr)


def calc_peg(pe: float, cagr: float) -> float:
    """Calculate PEG ratio.

    Args:
        pe: Current PE ratio.
        cagr: Compound annual growth rate (as a decimal, e.g. 0.20 for 20%).

    Returns:
        PEG ratio, or ``float("inf")`` if CAGR is non-positive.
    """
    if not cagr or cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)


def full_valuation(code: str) -> dict:
    """End-to-end single-stock valuation combining price, forward PE, CAGR, and PEG.

    Fetches current quote, EPS forecast, and computes forward PE, PEG, and
    PE digestion years.

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with ``code``, ``price``, ``forward_pe``, ``peg``,
        ``digestion_years``, ``analyst_count``, and ``eps_forecast``.
    """
    result: dict[str, Any] = {"code": code}

    # Step 1: Get current price via tencent_quote
    try:
        qt = tencent_quote([code])
        if code in qt:
            result["price"] = qt[code].get("price", 0)
        elif _strip_suffix(code) in qt:
            result["price"] = qt[_strip_suffix(code)].get("price", 0)
    except Exception as exc:
        logger.warning("full_valuation(%s): tencent_quote failed: %s", code, exc)
        result["price"] = None

    # Step 2: Get EPS forecast from 10jqka
    try:
        eps_df = ths_eps_forecast(code)
        if not eps_df.empty:
            # Try to extract consensus EPS
            for col in eps_df.columns:
                if "预测" in str(col) and "每股收益" in str(col):
                    vals = eps_df[col].dropna()
                    if not vals.empty:
                        result["eps_forecast"] = float(vals.iloc[0])
                        break
            result["analyst_count"] = len(eps_df)
    except Exception as exc:
        logger.warning("full_valuation(%s): ths_eps_forecast failed: %s", code, exc)

    # Step 3: Compute valuation metrics
    price = result.get("price") or 0
    eps_f = result.get("eps_forecast")
    if price and eps_f:
        result["forward_pe"] = forward_pe(price, eps_f)
        cagr = result.get("cagr", 0)
        result["peg"] = calc_peg(result["forward_pe"], cagr)
        result["digestion_years"] = pe_digestion(result["forward_pe"], cagr)
    else:
        result["forward_pe"] = None
        result["peg"] = None
        result["digestion_years"] = None

    return result


# ---------------------------------------------------------------------------
# Layer 1 extras: Real-time quote (tencent)
# ---------------------------------------------------------------------------


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """Fetch real-time quotes from Tencent Finance (supports PE/PB/market cap).

    Args:
        codes: List of stock codes with market suffix (e.g. ``["600519.SH", "000001.SZ"]``).

    Returns:
        Dict mapping code → quote dict with keys like ``price``, ``pe``, ``pb``,
        ``market_cap``, ``turnover``, etc.
    """
    formatted = []
    for code in codes:
        code6 = _strip_suffix(code)
        prefix = get_prefix(code6)
        formatted.append(f"s_{prefix}{code6}")

    url = "https://qt.gtimg.cn/q=" + ",".join(formatted)
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=10)
        resp.encoding = "gbk"
        text = resp.text
        result: dict[str, dict] = {}
        for segment in text.split(";"):
            segment = segment.strip()
            if not segment or '="' not in segment:
                continue
            try:
                # Format: v_s_sh600519="1~贵贵州茅台~600519~1850.00~..."
                var_part, value_part = segment.split("=", 1)
                value_part = value_part.strip('"')
                fields = value_part.split("~")
                if len(fields) < 40:
                    continue
                code6 = fields[2] if len(fields) > 2 else ""
                result[code6] = {
                    "name": fields[1],
                    "code": code6,
                    "price": float(fields[3]) if fields[3] else 0,
                    "last_close": float(fields[4]) if fields[4] else 0,
                    "open": float(fields[5]) if fields[5] else 0,
                    "volume": float(fields[6]) if fields[6] else 0,
                    "turnover": float(fields[37]) if fields[37] else 0,
                    "pe": float(fields[39]) if len(fields) > 39 and fields[39] else 0,
                    "pb": float(fields[40]) if len(fields) > 40 and fields[40] else 0,
                    "market_cap": float(fields[45]) if len(fields) > 45 and fields[45] else 0,
                }
            except (ValueError, IndexError) as e:
                logger.debug("tencent_quote: failed to parse segment: %s", e)
                continue
        return result
    except Exception as exc:
        logger.warning("tencent_quote() failed: %s", exc)
    return {}


# ---------------------------------------------------------------------------
# K-line with MA (baidu)
# ---------------------------------------------------------------------------


def baidu_kline_with_ma(code: str, start_time: str = "") -> dict:
    """Fetch K-line data with MA5/MA10/MA20 from Baidu Stock.

    Args:
        code: 6-digit stock code.
        start_time: Start date ``"YYYY-MM-DD"`` (default: auto).

    Returns:
        Dict with ``"klines"`` (list of OHLCV+MA dicts) and meta info.
    """
    code6 = _strip_suffix(code)
    prefix = get_prefix(code6)
    url = "https://finance.baidu.com/newfinance/api/openapi/openapi"
    params = {
        "code": f"{prefix}{code6}",
        "start_time": start_time,
        "type": "day",
    }
    headers = {
        "User-Agent": _UA,
        "Referer": f"https://gushibei.baidu.com/stock/{prefix}{code6}",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        d = resp.json()
        return d.get("data", d)
    except Exception as exc:
        logger.warning("baidu_kline_with_ma(%s) failed: %s", code6, exc)
    return {}