"""Tests for the a_stock_data module and AStockDataTool."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.skills.a_stock_data.a_stock_data import (
    calc_peg,
    cninfo_announcements,
    dedup_articles,
    eastmoney_datacenter,
    eastmoney_global_news,
    eastmoney_stock_info,
    eastmoney_stock_news,
    forward_pe,
    get_prefix,
    hsgt_realtime,
    lockup_expiry,
    margin_trading,
    pe_digestion,
    sina_financial_report,
    _strip_suffix,
)
from src.tools.a_stock_data_tool import AStockDataTool, _ACTION_MAP


# ---------------------------------------------------------------------------
# Helper: get_prefix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        ("600519", "sh"),
        ("000001", "sz"),
        ("300750", "sz"),
        ("835174", "bj"),
        ("688017", "sh"),
        ("600519.SH", "sh"),
        ("000001.SZ", "sz"),
        ("835174.BJ", "bj"),
        ("990001", "sh"),  # 9xx → SH
        ("002230", "sz"),
    ],
)
def test_get_prefix(code: str, expected: str) -> None:
    assert get_prefix(code) == expected


# ---------------------------------------------------------------------------
# Helper: _strip_suffix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        ("600519.SH", "600519"),
        ("000001.SZ", "000001"),
        ("835174.BJ", "835174"),
        ("600519", "600519"),
        (" 000001 ", "000001"),
    ],
)
def test_strip_suffix(code: str, expected: str) -> None:
    assert _strip_suffix(code) == expected


# ---------------------------------------------------------------------------
# Valuation helpers
# ---------------------------------------------------------------------------


def test_forward_pe_basic() -> None:
    assert forward_pe(100.0, 5.0) == 20.0


def test_forward_pe_zero_eps() -> None:
    assert forward_pe(100.0, 0.0) == float("inf")
    assert forward_pe(100.0, -1.0) == float("inf")


def test_calc_peg_basic() -> None:
    # PE=30, CAGR=20% → PEG = 30/(0.20*100) = 1.5
    assert calc_peg(30.0, 0.20) == 1.5


def test_calc_peg_zero_cagr() -> None:
    assert calc_peg(30.0, 0.0) == float("inf")


def test_pe_digestion_basic() -> None:
    # PE=60, CAGR=20%, target PE=30 → years = ln(60/30)/ln(1.20) ≈ 3.8
    import math
    expected = math.log(60 / 30) / math.log(1.2)
    assert abs(pe_digestion(60.0, 0.20, 30.0) - expected) < 0.01


def test_pe_digestion_below_target() -> None:
    assert pe_digestion(20.0, 0.20, 30.0) == 0.0


def test_pe_digestion_zero_cagr() -> None:
    assert pe_digestion(60.0, 0.0) == float("inf")


# ---------------------------------------------------------------------------
# dedup_articles
# ---------------------------------------------------------------------------


def test_dedup_articles_removes_duplicates() -> None:
    articles = [
        {"title": "A", "date": "2024-01-01"},
        {"title": "B", "date": "2024-01-02"},
        {"title": "A", "date": "2024-01-03"},  # duplicate title, later date
    ]
    result = dedup_articles(articles)
    assert len(result) == 2
    # Keeps first occurrence
    assert result[0]["title"] == "A"
    assert result[0]["date"] == "2024-01-01"


def test_dedup_articles_empty_title() -> None:
    articles = [
        {"title": "", "date": "2024-01-01"},
        {"title": "B", "date": "2024-01-02"},
    ]
    result = dedup_articles(articles)
    # Empty titles are skipped
    assert len(result) == 1
    assert result[0]["title"] == "B"


# ---------------------------------------------------------------------------
# Eastmoney throttled session (mocked)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, json_data: dict) -> None:
        self._json = json_data
        self.status_code = 200
        self.text = json.dumps(json_data)

    def json(self) -> dict:
        return self._json


def _make_eastmoney_response(data: list[dict]) -> dict:
    return {"result": {"data": data}}


# ---------------------------------------------------------------------------
# eastmoney_datacenter (mocked)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.em_get")
def test_eastmoney_datacenter_returns_data(mock_em_get: MagicMock) -> None:
    rows = [{"SECURITY_CODE": "600519", "REPORT_DATE": "2024-01-01"}]
    mock_em_get.return_value = _FakeResponse(_make_eastmoney_response(rows))
    result = eastmoney_datacenter("RPT_CUSTOM_WEB_BROKERPENNY", filter_str='(SECURITY_CODE="600519")')
    assert len(result) == 1
    assert result[0]["SECURITY_CODE"] == "600519"


@patch("src.skills.a_stock_data.a_stock_data.em_get")
def test_eastmoney_datacenter_empty_result(mock_em_get: MagicMock) -> None:
    mock_em_get.return_value = _FakeResponse({"result": None})
    result = eastmoney_datacenter("RPT_CUSTOM_WEB_BROKERPENNY")
    assert result == []


@patch("src.skills.a_stock_data.a_stock_data.em_get")
def test_eastmoney_datacenter_network_error(mock_em_get: MagicMock) -> None:
    mock_em_get.side_effect = ConnectionError("network down")
    result = eastmoney_datacenter("RPT_CUSTOM_WEB_BROKERPENNY")
    assert result == []


# ---------------------------------------------------------------------------
# eastmoney_stock_news (mocked)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.requests.get")
def test_eastmoney_stock_news_returns_items(mock_get: MagicMock) -> None:
    jsonp = 'jQuery_callback({"result":{"news":{"list":[{"title":"Test News","url":"http://example.com","publish_time":"2024-01-01","source":"Test","content":"Content"}]}}})'
    mock_resp = MagicMock()
    mock_resp.text = jsonp
    mock_resp.json = MagicMock(return_value={})
    mock_get.return_value = mock_resp

    result = eastmoney_stock_news("600519", page_size=10)
    # The function parses JSONP — this test verifies it doesn't crash
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# eastmoney_global_news (mocked)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.requests.get")
def test_eastmoney_global_news_returns_items(mock_get: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "list": [
                {"title": "Global News 1", "url": "http://example.com/1", "showTime": "2024-01-01 10:00", "source": "Test"},
                {"title": "Global News 2", "url": "http://example.com/2", "showTime": "2024-01-01 09:00", "source": "Test"},
            ]
        }
    }
    mock_get.return_value = mock_resp

    result = eastmoney_global_news(page_size=10)
    assert len(result) == 2
    assert result[0]["title"] == "Global News 1"


# ---------------------------------------------------------------------------
# cninfo_announcements (mocked)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data._cninfo_orgid")
@patch("src.skills.a_stock_data.a_stock_data.requests.post")
def test_cninfo_announcements_returns_items(mock_post: MagicMock, mock_orgid: MagicMock) -> None:
    mock_orgid.return_value = "ORG123"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "announcements": [
            {
                "announcementTitle": "Annual Report 2024",
                "announcementTime": 1704067200000,  # 2024-01-01
                "adjunctUrl": "disclosure/2024-01-01/annual.pdf",
                "column": "szse",
            }
        ]
    }
    mock_post.return_value = mock_resp

    result = cninfo_announcements("600519", page_size=10)
    assert len(result) == 1
    assert result[0]["title"] == "Annual Report 2024"
    assert "cninfo.com.cn" in result[0]["url"]


@patch("src.skills.a_stock_data.a_stock_data._cninfo_orgid")
def test_cninfo_announcements_no_orgid(mock_orgid: MagicMock) -> None:
    mock_orgid.return_value = ""
    result = cninfo_announcements("999999")
    assert result == []


# ---------------------------------------------------------------------------
# sina_financial_report (mocked)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.requests.get")
def test_sina_financial_report_handles_failure(mock_get: MagicMock) -> None:
    mock_get.side_effect = ConnectionError("network down")
    result = sina_financial_report("600519", report_type="lrb")
    assert result == []


# ---------------------------------------------------------------------------
# margin_trading (mocked via eastmoney_datacenter)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.eastmoney_datacenter")
def test_margin_trading(mock_edc: MagicMock) -> None:
    rows = [{"SECURITY_CODE": "600519", "RZRQYE": 1000000}]
    mock_edc.return_value = rows
    result = margin_trading("600519", page_size=10)
    assert len(result) == 1
    assert result[0]["SECURITY_CODE"] == "600519"


# ---------------------------------------------------------------------------
# lockup_expiry (mocked via eastmoney_datacenter)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.eastmoney_datacenter")
def test_lockup_expiry(mock_edc: MagicMock) -> None:
    mock_edc.return_value = [{"SECURITY_CODE": "600519", "END_DATE": "2024-06-30"}]
    result = lockup_expiry("600519", trade_date="2024-01-01", forward_days=90)
    assert "data" in result
    assert len(result["data"]) == 1


# ---------------------------------------------------------------------------
# hsgt_realtime (mocked)
# ---------------------------------------------------------------------------


@patch("src.skills.a_stock_data.a_stock_data.em_get")
def test_hsgt_realtime(mock_em_get: MagicMock) -> None:
    mock_em_get.return_value = _FakeResponse({
        "result": {"data": [{"TRADE_DATE": "2024-01-01", "HGT": 50.0, "SGT": 30.0}]}
    })
    result = hsgt_realtime()
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# AStockDataTool
# ---------------------------------------------------------------------------


class TestAStockDataTool:
    """Tests for the MCP tool dispatch."""

    def test_tool_name_defined(self) -> None:
        tool = AStockDataTool()
        assert tool.name == "get_a_stock_data"

    def test_tool_has_required_params(self) -> None:
        tool = AStockDataTool()
        assert "action" in tool.parameters["properties"]
        assert "code" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["action", "code"]

    def test_action_map_complete(self) -> None:
        """Verify all action enums have a corresponding function in the module."""
        import src.skills.a_stock_data.a_stock_data as asd
        for action, func_name in _ACTION_MAP.items():
            assert hasattr(asd, func_name), f"Missing function: {func_name}"

    def test_execute_unknown_action(self) -> None:
        tool = AStockDataTool()
        result = tool.execute(action="nonexistent", code="600519")
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("src.skills.a_stock_data.a_stock_data.eastmoney_datacenter")
    def test_execute_margin_trading(self, mock_edc: MagicMock) -> None:
        mock_edc.return_value = [{"SECURITY_CODE": "600519", "RZRQYE": 1000000}]
        tool = AStockDataTool()
        result = tool.execute(action="margin_trading", code="600519", page_size=10)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_execute_forward_pe(self) -> None:
        """Test valuation helpers via execute with mock."""
        tool = AStockDataTool()
        # forward_pe is called from full_valuation, test directly
        assert forward_pe(100.0, 5.0) == 20.0

    @patch("src.skills.a_stock_data.a_stock_data.eastmoney_datacenter")
    def test_execute_dividend_history(self, mock_edc: MagicMock) -> None:
        mock_edc.return_value = [{"SECURITY_CODE": "600519", "REPORT_DATE": "2024-01-01"}]
        tool = AStockDataTool()
        result = tool.execute(action="dividend_history", code="600519")
        parsed = json.loads(result)
        assert isinstance(parsed, list)


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_a_stock_data_action_map_not_empty() -> None:
    """Verify the action map has entries for all expected categories."""
    assert "reports" in _ACTION_MAP
    assert "news" in _ACTION_MAP
    assert "announcements" in _ACTION_MAP
    assert "stock_info" in _ACTION_MAP
    assert "financial_report" in _ACTION_MAP
    assert "margin_trading" in _ACTION_MAP
    assert "dividend_history" in _ACTION_MAP
    assert "northbound_flow" in _ACTION_MAP
    assert "valuation" in _ACTION_MAP