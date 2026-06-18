"""A-stock extended data tool for MCP — research reports, news, announcements, capital flow, signals, and fundamentals.

Exposes the 27 endpoints from ``src.skills.a_stock_data.a_stock_data`` as a single
MCP tool with an ``action`` dispatch parameter. This covers the non-OHLCV A-share
data layers that the existing DataLoaderProtocol loaders (tushare, mootdx, baostock,
tencent, akshare) do not provide.

For OHLCV 行情 data, use the existing ``get_market_data`` tool with source auto-detection.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.tools import BaseTool
from src.skills.a_stock_data import a_stock_data as asd

logger = logging.getLogger(__name__)

_ACTION_MAP: dict[str, str] = {
    "reports": "eastmoney_reports",
    "news": "eastmoney_stock_news",
    "global_news": "eastmoney_global_news",
    "announcements": "cninfo_announcements",
    "stock_info": "eastmoney_stock_info",
    "financial_report": "sina_financial_report",
    "concept_blocks": "eastmoney_concept_blocks",
    "fund_flow_minute": "eastmoney_fund_flow_minute",
    "fund_flow_120d": "stock_fund_flow_120d",
    "dragon_tiger": "dragon_tiger_board",
    "daily_dragon_tiger": "daily_dragon_tiger",
    "margin_trading": "margin_trading",
    "block_trade": "block_trade",
    "holder_change": "holder_num_change",
    "dividend_history": "dividend_history",
    "northbound_flow": "hsgt_realtime",
    "hot_stocks": "ths_hot_reason",
    "lockup_expiry": "lockup_expiry",
    "industry_comparison": "industry_comparison",
    "valuation": "full_valuation",
    "eps_forecast": "ths_eps_forecast",
    "tencent_quote": "tencent_quote",
    "baidu_kline": "baidu_kline_with_ma",
    "iwencai_search": "iwencai_search",
    "iwencai_query": "iwencai_query",
}

# Actions that require only the code parameter (no extra kwargs)
_CODE_ONLY_ACTIONS = frozenset({
    "reports", "stock_info", "concept_blocks", "fund_flow_minute",
    "fund_flow_120d", "margin_trading", "block_trade", "holder_change",
    "dividend_history", "announcements", "valuation", "eps_forecast",
    "tencent_quote", "baidu_kline",
})


def _serialize(result: Any) -> str:
    """Convert a result to a JSON string, handling DataFrames via to_dict()."""
    if isinstance(result, pd_DataFrame):
        return json.dumps(result.to_dict(orient="records"), ensure_ascii=False, indent=2, default=str)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if isinstance(result, list):
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


try:
    from pandas import DataFrame as pd_DataFrame  # noqa: N813
except ImportError:
    pd_DataFrame = None  # type: ignore[assignment,misc]


class AStockDataTool(BaseTool):
    """Fetch A-share extended data: research reports, news, announcements, capital flow, signals, and fundamentals."""

    name = "get_a_stock_data"
    description = (
        "Fetch A-share extended data beyond OHLCV: research reports (研报), "
        "news (新闻), announcements (公告), capital flow (资金面), signals (信号), "
        "fundamentals (基础数据), and valuation (估值). "
        "For OHLCV price bars, use the get_market_data tool instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_ACTION_MAP.keys()),
                "description": (
                    "Data category to fetch. Options: "
                    "reports=analyst research reports, news=stock-specific news, "
                    "global_news=7x24 market news, announcements=cninfo filings, "
                    "stock_info=basic stock info, financial_report=Sina 3 statements, "
                    "concept_blocks=sector/concept attribution, "
                    "fund_flow_minute=intraday capital flow, fund_flow_120d=120-day flow, "
                    "dragon_tiger=dragon-tiger board detail, "
                    "daily_dragon_tiger=market-wide dragon-tiger, "
                    "margin_trading=融资融券, block_trade=大宗交易, "
                    "holder_change=股东人数变化, dividend_history=分红历史, "
                    "northbound_flow=北向资金, hot_stocks=同花顺人气榜, "
                    "lockup_expiry=解禁日历, industry_comparison=行业排名, "
                    "valuation=full valuation (PE/PEG), eps_forecast=EPS预测, "
                    "tencent_quote=real-time quote, baidu_kline=K-line+MA, "
                    "iwencai_search=iwencai NL search, iwencai_query=iwencai structured query"
                ),
            },
            "code": {
                "type": "string",
                "description": "6-digit stock code, e.g. '000001' or '600519'. Also accepts '000001.SZ' format.",
            },
            "page_size": {
                "type": "integer",
                "description": "Number of records to return (default 20-50 depending on action).",
            },
            "max_pages": {
                "type": "integer",
                "description": "For reports: maximum pages to paginate (default 5).",
            },
            "trade_date": {
                "type": "string",
                "description": "Trade date in YYYY-MM-DD format (for dragon_tiger, lockup_expiry, hot_stocks).",
            },
            "look_back": {
                "type": "integer",
                "description": "For dragon_tiger: days to look back if exact date has no data (default 30).",
            },
            "forward_days": {
                "type": "integer",
                "description": "For lockup_expiry: days to look ahead from trade_date (default 90).",
            },
            "report_type": {
                "type": "string",
                "enum": ["lrb", "fzb", "llb"],
                "description": "For financial_report: lrb=income statement, fzb=balance sheet, llb=cash flow.",
            },
            "query": {
                "type": "string",
                "description": "For iwencai_search/iwencai_query: natural language or structured query.",
            },
            "channel": {
                "type": "string",
                "description": "For iwencai_search: search channel ('report' or 'stock').",
            },
            "min_net_buy": {
                "type": "number",
                "description": "For daily_dragon_tiger: minimum net buy threshold (in 亿元).",
            },
            "top_n": {
                "type": "integer",
                "description": "For industry_comparison: number of top industries to return.",
            },
            "start_time": {
                "type": "string",
                "description": "For baidu_kline: start date YYYY-MM-DD.",
            },
        },
        "required": ["action", "code"],
    }
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        code = kwargs.get("code", "")

        func_name = _ACTION_MAP.get(action)
        if not func_name:
            return json.dumps(
                {"error": f"Unknown action '{action}'. Valid: {sorted(_ACTION_MAP.keys())}"},
                ensure_ascii=False,
            )

        func = getattr(asd, func_name, None)
        if func is None:
            return json.dumps(
                {"error": f"Function '{func_name}' not found in a_stock_data module"},
                ensure_ascii=False,
            )

        try:
            # Dispatch based on action type with appropriate kwargs
            result = self._dispatch(func, func_name, action, kwargs)
            return _serialize(result)
        except Exception as exc:
            logger.exception("AStockDataTool action=%s code=%s failed", action, code)
            return json.dumps(
                {"error": f"{func_name} failed: {exc}", "action": action, "code": code},
                ensure_ascii=False,
            )

    def _dispatch(self, func: Any, func_name: str, action: str, kwargs: Any) -> Any:
        """Route to the correct function with appropriate arguments."""
        code = kwargs.get("code", "")
        page_size = kwargs.get("page_size")

        # Actions that don't take a code parameter
        if action == "global_news":
            ps = page_size or 50
            return func(page_size=ps)
        if action == "northbound_flow":
            return func()
        if action == "hot_stocks":
            return func(date=kwargs.get("trade_date"))
        if action == "daily_dragon_tiger":
            return func(
                trade_date=kwargs.get("trade_date"),
                min_net_buy=kwargs.get("min_net_buy"),
            )
        if action == "industry_comparison":
            return func(top_n=kwargs.get("top_n", 20))

        # iwencai actions
        if action == "iwencai_search":
            return func(
                query=kwargs.get("query", ""),
                channel=kwargs.get("channel", "report"),
                size=kwargs.get("page_size", 50),
            )
        if action == "iwencai_query":
            return func(
                query=kwargs.get("query", ""),
                page=kwargs.get("page_size", 1),
                limit=kwargs.get("page_size", 50),
            )

        # Actions with special signatures
        if action == "reports":
            return func(code=code, max_pages=kwargs.get("max_pages", 5))
        if action == "dragon_tiger":
            return func(
                code=code,
                trade_date=kwargs.get("trade_date", ""),
                look_back=kwargs.get("look_back", 30),
            )
        if action == "lockup_expiry":
            return func(
                code=code,
                trade_date=kwargs.get("trade_date", ""),
                forward_days=kwargs.get("forward_days", 90),
            )
        if action == "financial_report":
            return func(
                code=code,
                report_type=kwargs.get("report_type", "lrb"),
                num=kwargs.get("page_size", 8),
            )
        if action == "tencent_quote":
            return func(codes=[code])
        if action == "baidu_kline":
            return func(code=code, start_time=kwargs.get("start_time", ""))

        # Code-only actions with optional page_size
        ps_val = page_size  # May be None
        if action in ("margin_trading",):
            return func(code=code, page_size=ps_val or 30)
        if action in ("block_trade",):
            return func(code=code, page_size=ps_val or 20)
        if action in ("holder_change",):
            return func(code=code, page_size=ps_val or 10)
        if action in ("dividend_history",):
            return func(code=code, page_size=ps_val or 20)
        if action in ("announcements",):
            return func(code=code, page_size=ps_val or 30)
        if action in ("news",):
            return func(code=code, page_size=ps_val or 20)

        # Default: pass code and any page_size
        if ps_val is not None:
            return func(code=code, page_size=ps_val)
        return func(code=code)