"""etf_tracker 单元测试 — 核心分析逻辑，不依赖网络"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import etf_tracker


# ==================== 测试数据构造 ====================

def make_kline(flows):
    """flows: [(change_pct, amount), ...] → mock kline rows"""
    rows = []
    base_price = 2.0
    for i, (change_pct, amount) in enumerate(flows):
        base_price = base_price * (1 + change_pct / 100)
        rows.append({
            "date": f"2026-09-0{i + 1}",
            "close": round(base_price, 4),
            "change_pct": change_pct,
            "volume": int(amount / base_price),
            "amount": amount,
            "net_flow": amount * (1 if change_pct >= 0 else -1),
        })
    return rows


@pytest.fixture
def patch_kline(monkeypatch):
    """替换 get_etf_kline，返回 {code: kline_rows} 映射驱动的数据源"""
    def _patch(code_kline_map, source="测试源"):
        def fake_get_etf_kline(code, market, days=5):
            rows = code_kline_map.get(code)
            if rows is None:
                return {"code": code, "error": "所有数据源不可用"}
            return {"code": code, "kline": rows[:days], "source": source}
        monkeypatch.setattr(etf_tracker, "get_etf_kline", fake_get_etf_kline)
    return _patch


# ==================== generate_mock_kline ====================

def test_generate_mock_kline_structure():
    kline = etf_tracker.generate_mock_kline("510300", days=5)
    assert len(kline) == 5
    for row in kline:
        assert set(row) == {"date", "close", "change_pct", "volume", "amount", "net_flow"}
        assert row["amount"] > 0
        assert row["net_flow"] == row["amount"] * (1 if row["change_pct"] >= 0 else -1)


# ==================== calculate_fund_flow_summary ====================

def test_flow_summary_sorting_and_math(patch_kline):
    inflow = make_kline([(1.0, 1e9)] * 5)      # 5日全流入 → 累计 +5亿
    outflow = make_kline([(-1.0, 1e9)] * 5)    # 5日全流出 → 累计 -5亿
    patch_kline({"510300": inflow, "510500": outflow})

    results = etf_tracker.calculate_fund_flow_summary(
        [{"code": "510300", "name": "沪深300", "market": "sh", "category": "宽基核心"},
         {"code": "510500", "name": "中证500", "market": "sh", "category": "宽基核心"}],
        days=5)

    assert len(results) == 2
    # 降序：流入在前
    assert results[0]["code"] == "510300"
    assert results[0]["total_net_flow_yi"] == pytest.approx(50.0)
    assert results[0]["trend"] == "连续流入"
    assert results[0]["positive_days"] == "5/5"
    # 流出方向恢复真实负值（回归：修复前恒为正）
    assert results[1]["total_net_flow_yi"] == pytest.approx(-50.0)
    assert results[1]["trend"] == "连续流出"


def test_flow_summary_trend_mixed(patch_kline):
    # 4正1负 → 以流入为主；4负1正 → 以流出为主；3正2负 → 中性
    mostly_in = make_kline([(1.0, 1e8)] * 4 + [(-1.0, 1e8)])
    mostly_out = make_kline([(-1.0, 1e8)] * 4 + [(1.0, 1e8)])
    neutral = make_kline([(1.0, 1e8)] * 3 + [(-1.0, 1e8)] * 2)
    patch_kline({"A": mostly_in, "B": mostly_out, "C": neutral})

    etfs = [{"code": c, "name": c, "market": "sh", "category": "t"} for c in "ABC"]
    results = {r["code"]: r["trend"] for r in etf_tracker.calculate_fund_flow_summary(etfs, days=5)}

    assert results["A"] == "以流入为主"
    assert results["B"] == "以流出为主"
    assert results["C"] == "中性"


def test_flow_summary_skips_error_codes(patch_kline):
    patch_kline({"510300": make_kline([(1.0, 1e9)] * 5)})
    results = etf_tracker.calculate_fund_flow_summary(
        [{"code": "510300", "name": "ok", "market": "sh", "category": "c"},
         {"code": "000000", "name": "bad", "market": "sh", "category": "c"}],
        days=5)
    assert [r["code"] for r in results] == ["510300"]


# ==================== detect_state_fund_signals ====================

@pytest.mark.parametrize("flow_yi,trend,expected_type,expected_conf", [
    (64.0, "连续流入", "强加仓信号", "高"),
    (55.0, "中性", "大额加仓信号", "高"),
    (12.0, "以流入为主", "加仓信号", "中"),
    (3.0, "连续流入", "关注信号", "低"),
    (-64.0, "连续流出", "强减仓信号", "高"),
    (-12.0, "中性", "减仓信号", "中"),
    (-3.0, "连续流出", "关注信号(流出)", "低"),
])
def test_signal_thresholds(flow_yi, trend, expected_type, expected_conf):
    item = {"code": "X", "name": "X", "category": "c", "latest_price": 1.0,
            "change_pct": 0.0, "daily_amount_yi": 1.0, "total_net_flow_yi": flow_yi,
            "avg_net_flow_yi": flow_yi / 5, "positive_days": "5/5",
            "trend": trend,
            "source": "s", "daily_flows": []}
    signals = etf_tracker.detect_state_fund_signals([item])
    assert len(signals) == 1
    assert signals[0]["signal_type"] == expected_type
    assert signals[0]["confidence"] == expected_conf


def test_signal_below_threshold_filtered():
    item = {"code": "X", "name": "X", "category": "c", "latest_price": 1.0,
            "change_pct": 0.0, "daily_amount_yi": 1.0, "total_net_flow_yi": 1.5,
            "avg_net_flow_yi": 0.3, "positive_days": "3/5", "trend": "中性",
            "source": "s", "daily_flows": []}
    assert etf_tracker.detect_state_fund_signals([item]) == []


# ==================== visualize_flow_bars ====================

def test_visualize_flow_bars_positive_and_negative():
    data = [{"date": "2026-09-01", "flow_yi": 10.0},
            {"date": "2026-09-02", "flow_yi": -5.0}]
    out = etf_tracker.visualize_flow_bars(data)
    assert "█" in out and "░" in out
    assert "[+10.00亿]" in out and "[-5.00亿]" in out


def test_visualize_flow_bars_empty():
    assert etf_tracker.visualize_flow_bars([]) == "无数据"


# ==================== archive_to_daily_reports ====================

def test_archive_to_daily_reports(tmp_path):
    archive_root = tmp_path / "archive"
    out = etf_tracker.archive_to_daily_reports("# 测试报告", archive_root=str(archive_root))
    today = datetime.now().strftime("%Y-%m-%d")
    expected = archive_root / today / f"ETF资金监测_{datetime.now().strftime('%Y%m%d')}.md"
    assert os.path.abspath(out) == os.path.abspath(str(expected))
    assert expected.read_text(encoding="utf-8") == "# 测试报告"


# ==================== parse_args ====================

def test_parse_args_defaults():
    args = etf_tracker.parse_args([])
    assert args.days == 5
    assert args.source == "auto"
    assert args.top == 15
    assert args.no_archive is False
    assert args.archive_dir is None


def test_parse_args_custom():
    args = etf_tracker.parse_args(["--days", "10", "--source", "mock",
                                   "--top", "20", "--no-archive",
                                   "--archive-dir", "./x"])
    assert args.days == 10
    assert args.source == "mock"
    assert args.top == 20
    assert args.no_archive is True
    assert args.archive_dir == "./x"


def test_parse_args_rejects_bad_source():
    with pytest.raises(SystemExit):
        etf_tracker.parse_args(["--source", "windx"])


# ==================== 数据源探测 ====================

def test_detect_wind_mcp_missing_path(monkeypatch):
    monkeypatch.setattr(etf_tracker, "WIND_MCP_PATH", "/nonexistent/path")
    assert etf_tracker._detect_wind_mcp() is False


def test_source_enabled_logic():
    etf_tracker.SOURCE_MODE = "auto"
    assert etf_tracker._source_enabled("mock") is True
    etf_tracker.SOURCE_MODE = "mock"
    assert etf_tracker._source_enabled("mock") is True
    assert etf_tracker._source_enabled("akshare") is False