---
name: a_stock_data
category: data-source
description: A-share full-stack data toolkit covering 研报/新闻/公告/资金面/信号/基础数据. Free (no API key required for most endpoints). Integrates simonlin1212/a-stock-data V3.2.2.
---

## Overview

A-stock extended data toolkit based on [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) (4.8k stars, V3.2.2). Covers **7 layers of non-OHLCV A-share data** that the existing loaders (tushare, mootdx, baostock, tencent, akshare) do not provide.

For **OHLCV 行情** data (daily/intraday bars), use the existing `get_market_data` tool with source auto-detection — this skill does NOT provide OHLCV bars.

**No API key required** for most endpoints (Eastmoney, Sina, THS, cninfo, Baidu, Tencent are all free). The only exception is **iwencai** which requires `IWENCAI_API_KEY`.

- Repository: https://github.com/simonlin1212/a-stock-data
- Dependencies: `requests`, `pandas` (already in project); `stockstats` (optional, for full_valuation)

## 7 Data Layers (27 Endpoints)

### Layer 1: 行情层 (Quotes — real-time, no IP ban)

| Function | Description | Key Params |
|----------|-------------|------------|
| `tencent_quote(codes)` | Real-time PE/PB/market cap/turnover | List of codes with .SZ/.SH suffix |
| `baidu_kline_with_ma(code, start_time)` | K-line with MA5/10/20 | 6-digit code, start date |

> **Note**: For OHLCV backtesting data, use existing loaders. These Layer 1 functions are supplementary (real-time quote snapshots, MA overlays).

### Layer 2: 研报层 (Research Reports)

| Function | Description | Key Params |
|----------|-------------|------------|
| `eastmoney_reports(code, max_pages=5)` | Analyst report list | code, max pages |
| `download_pdf(record, target_dir)` | Download report PDF | record dict from eastmoney_reports |
| `ths_eps_forecast(code)` | Consensus EPS estimates | 6-digit code |
| `iwencai_search(query, channel, size)` | NL semantic search | query, channel="report" |
| `iwencai_query(query, page, limit)` | Structured data query | query, page, limit |
| `dedup_articles(articles)` | Deduplicate by title | list of article dicts |

> `iwencai_search` / `iwencai_query` require `IWENCAI_API_KEY` env var.

### Layer 3: 信号层 (Signals)

| Function | Description | Key Params |
|----------|-------------|------------|
| `ths_hot_reason(date)` | Daily strong-reason stocks | date YYYY-MM-DD, default today |
| `hsgt_realtime()` | Northbound capital flow (沪深港通) | None |
| `eastmoney_concept_blocks(code)` | Stock sector/concept attribution | 6-digit code |
| `eastmoney_fund_flow_minute(code)` | Intraday minute-level flow | 6-digit code |
| `dragon_tiger_board(code, trade_date, look_back)` | Dragon-tiger list seats | code, date, look_back days |
| `daily_dragon_tiger(trade_date, min_net_buy)` | Market-wide dragon-tiger | date, min net buy (亿元) |
| `lockup_expiry(code, trade_date, forward_days)` | Lockup expiry calendar | code, date, forward Days |
| `industry_comparison(top_n)` | Industry ranking | top N industries |

### Layer 4: 资金面/筹码层 (Capital / Shares)

| Function | Description | Key Params |
|----------|-------------|------------|
| `margin_trading(code, page_size)` | 融资融券 detail | code, page size |
| `block_trade(code, page_size)` | 大宗交易 detail | code, page size |
| `holder_num_change(code, page_size)` | 股东人数变化 | code, page size |
| `dividend_history(code, page_size)` | 分红历史 | code, page size |
| `stock_fund_flow_120d(code)` | 120-day capital flow | 6-digit code |

### Layer 5: 新闻层 (News)

| Function | Description | Key Params |
|----------|-------------|------------|
| `eastmoney_stock_news(code, page_size)` | Stock-specific news | code, page size |
| `eastmoney_global_news(page_size)` | 7×24 global finance news | page size |

> `cls_telegraph()` is **DEPRECATED** (cls.cn 404 since 2026-05) and has been omitted.

### Layer 6: 基础数据层 (Base Data)

| Function | Description | Key Params |
|----------|-------------|------------|
| `eastmoney_stock_info(code)` | Industry/shares/market cap | 6-digit code |
| `sina_financial_report(code, report_type, num)` | Three financial statements | code, type="lrb"/"fzb"/"llb" |

> Mootdx finance/F10 data is available through the existing `mootdx` loader.

### Layer 7: 公告层 (Announcements)

| Function | Description | Key Params |
|----------|-------------|------------|
| `cninfo_announcements(code, page_size)` | Full-text filing search | code, page size |

### Valuation Formulas

| Function | Description | Key Params |
|----------|-------------|------------|
| `forward_pe(price, eps_forecast)` | Forward PE ratio | price, forecast EPS |
| `pe_digestion(current_pe, cagr, target_pe)` | PE digestion years | current PE, CAGR, target PE=30 |
| `calc_peg(pe, cagr)` | PEG ratio | PE, CAGR |
| `full_valuation(code)` | Single-ticket end-to-end valuation | 6-digit code |

## Symbol Format

- Input accepted: `600519`, `SH688017`, `sh600519`, `600519.SH`, `SZ000001`, `BJ832000`
- All functions normalize internally via `get_prefix()` and `_strip_suffix()`
- Market detection: 6xx/9xx → SH, 8xx → BJ, otherwise → SZ

## Built-in Module

`src/skills/a_stock_data/a_stock_data.py` contains all 27 endpoint functions. Import from there:

```python
from src.skills.a_stock_data.a_stock_data import (
    get_prefix, eastmoney_reports, eastmoney_stock_news,
    cninfo_announcements, eastmoney_stock_info,
    sina_financial_report, hsgt_realtime,
)
```

The MCP tool `get_a_stock_data` exposes these functions through a single `action` dispatch parameter:

```python
# Via MCP tool
result = get_a_stock_data(action="reports", code="600519")
result = get_a_stock_data(action="news", code="000001", page_size=10)
result = get_a_stock_data(action="announcements", code="600519")
```

## Rate Limits (Eastmoney Anti-Ban)

Eastmoney enforces IP bans when request patterns exceed thresholds:

| Metric | Threshold | Risk |
|--------|-----------|------|
| Requests/sec | >5/s | High |
| Concurrent connections | ≥10 | High |
| 1-min total | ≥200 | Medium-high |
| 5-min total | ≥300 | Ban triggered |

The built-in `em_get()` function enforces ≥1s interval + random jitter (0.1–0.5s) with session reuse. **Do not bypass this throttle** in batch scripts — add your own `time.sleep()` between stocks.

Mootdx (TCP 7709) and Tencent (HTTP GBK) are documented as "never IP-banned" and need no throttling.

## Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `EM_MIN_INTERVAL` | Min seconds between Eastmoney calls (default 1.0) | No |
| `IWENCAI_API_KEY` | iwencai API key for NL search | Only for iwencai_search/query |
| `IWENCAI_BASE_URL` | iwencai API base URL (default https://openapi.iwencai.com) | No |

## Known Limitations

| Limitation | Workaround |
|------------|-----------|
| `ths_eps_forecast` scrapes HTML from 10jqka; GBK encoding may fail on some stocks | Try again, or use `iwencai_search` for EPS queries |
| `baidu_kline_with_ma` is fragile (Baidu PAE API may return error codes) | Use existing loaders for OHLCV data |
| `cninfo_announcements` orgId lookup may fail for very new IPOs | _cninfo_orgid caches after first download |
| Mainland residential IPs may get intermittent HTTP 000 from Eastmoney | Retry or switch network |
| `cls_telegraph` is DEPRECATED (cls.cn 404 since 2026-05) | Use `eastmoney_global_news` instead |

## Reference Docs

- a-stock-data repository: https://github.com/simonlin1212/a-stock-data
- a-stock-data SKILL.md (V3.2.2): https://raw.githubusercontent.com/simonlin1212/a-stock-data/main/SKILL.md
- Eastmoney DataCenter API: https://datacenter-web.eastmoney.com
- cninfo announcement search: https://www.cninfo.com.cn