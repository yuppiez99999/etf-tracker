"""
ETF 国家队资金监测系统
追踪中央汇金等国家队 ETF 持仓变化

核心逻辑：
1. 覆盖20+主流宽基ETF实时行情
2. 通过K线成交额+涨跌幅估算资金净流入
3. 连续N日资金流趋势检测→国家队加仓/减仓信号
4. 自动构建ETF成交额TOP20排名

数据来源: Wind MCP Skill (优先) / akshare (备选) / 模拟数据 (兜底演示)
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ==================== 数据源探测 ====================
WIND_FUND_ENDPOINT = "https://mcp.wind.com.cn/vserver_fund_data/mcp/"
_WIND_API_KEY_CACHE: str | None = None


def _get_wind_api_key() -> str | None:
    """Wind MCP API key: 环境变量 > ~/.wind-aifinmarket/config"""
    global _WIND_API_KEY_CACHE
    if _WIND_API_KEY_CACHE is not None:
        return _WIND_API_KEY_CACHE
    env_key = os.environ.get("WIND_API_KEY")
    if env_key:
        _WIND_API_KEY_CACHE = env_key.strip()
        return _WIND_API_KEY_CACHE
    cfg = os.path.join(os.path.expanduser("~"), ".wind-aifinmarket", "config")
    try:
        if os.path.isfile(cfg):
            with open(cfg, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    if line.startswith("WIND_API_KEY="):
                        _WIND_API_KEY_CACHE = line.split("=", 1)[1].strip()
                        return _WIND_API_KEY_CACHE
    except Exception:
        pass
    _WIND_API_KEY_CACHE = None
    return None


def _detect_wind_available() -> bool:
    """Wind MCP 可用性 = API key 已配置（HTTP 直连模式）"""
    return _get_wind_api_key() is not None


def _detect_akshare() -> bool:
    try:
        import akshare  # noqa: F401

        return True
    except ImportError:
        return False


WIND_MCP_AVAILABLE = _detect_wind_available()
AK_AVAILABLE = _detect_akshare()

# 数据源模式: auto(按优先级降级) / wind(强制Wind MCP) / akshare(强制akshare) / mock(强制演示)
SOURCE_MODE = "auto"


def _source_enabled(source_name: str) -> bool:
    if SOURCE_MODE == "auto":
        return True
    return SOURCE_MODE == source_name


# 模拟数据模式（当所有数据源不可用或强制指定时使用）
def generate_mock_kline(code, days=5):
    """生成模拟K线数据"""
    price_map = {
        "510300": 3.85,
        "510310": 3.86,
        "159919": 3.84,
        "510500": 6.20,
        "510510": 6.18,
        "510050": 2.65,
        "510180": 6.85,
        "159915": 1.98,
        "159952": 1.97,
        "588000": 1.85,
        "588080": 1.84,
        "560010": 1.52,
        "512100": 1.53,
        "159647": 1.25,
        "515080": 1.45,
        "515180": 1.46,
        "512890": 1.38,
        "512880": 1.28,
        "512800": 1.15,
        "512170": 0.78,
        "512010": 0.82,
        "512760": 1.35,
        "515030": 1.42,
        "518880": 8.95,
    }
    base_price = price_map.get(code, 2.0)
    kline = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=days - i - 1)).strftime("%Y-%m-%d")
        change_pct = random.uniform(-2, 3)
        base_price = base_price * (1 + change_pct / 100)
        amount = random.uniform(50000000, 500000000)  # 5000万 - 5亿
        kline.append(
            {
                "date": date,
                "close": round(base_price, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(amount / base_price),
                "amount": amount,
                "net_flow": amount * (1 if change_pct >= 0 else -1),
            }
        )
    return kline


# ==================== 配置区 ====================
CONFIG = {
    # 扩展至20+主流宽基ETF（覆盖视频中提及的核心标的）
    "etf_list": [
        # 宽基指数ETF - 核心配置
        {"code": "510300", "name": "沪深300ETF华泰柏瑞", "market": "sh", "category": "宽基核心"},
        {"code": "510310", "name": "沪深300ETF易方达", "market": "sh", "category": "宽基核心"},
        {"code": "159919", "name": "沪深300ETF嘉实", "market": "sz", "category": "宽基核心"},
        {"code": "510500", "name": "中证500ETF南方", "market": "sh", "category": "宽基核心"},
        {"code": "510510", "name": "中证500ETF广发", "market": "sh", "category": "宽基核心"},
        {"code": "510050", "name": "上证50ETF华夏", "market": "sh", "category": "蓝筹核心"},
        {"code": "510180", "name": "上证180ETF华安", "market": "sh", "category": "蓝筹核心"},
        {"code": "159915", "name": "创业板ETF易方达", "market": "sz", "category": "成长科技"},
        {"code": "159952", "name": "创业板ETF广发", "market": "sz", "category": "成长科技"},
        {"code": "588000", "name": "科创50ETF华夏", "market": "sh", "category": "成长科技"},
        {"code": "588080", "name": "科创50ETF易方达", "market": "sh", "category": "成长科技"},
        # 中证1000/国证2000 - 小盘风格
        {"code": "560010", "name": "中证1000ETF富国", "market": "sh", "category": "小盘风格"},
        {"code": "512100", "name": "中证1000ETF南方", "market": "sh", "category": "小盘风格"},
        {"code": "159647", "name": "国证2000ETF万家", "market": "sz", "category": "小盘风格"},
        # 红利/低波 - 防御型
        {"code": "515080", "name": "中证红利ETF易方达", "market": "sh", "category": "防御红利"},
        {"code": "515180", "name": "中证红利ETF富国", "market": "sh", "category": "防御红利"},
        {
            "code": "512890",
            "name": "红利低波100ETF华泰柏瑞",
            "market": "sh",
            "category": "防御红利",
        },
        # 行业主题ETF - 国家队关注
        {"code": "512880", "name": "证券ETF国泰", "market": "sh", "category": "金融主题"},
        {"code": "512800", "name": "银行ETF华宝", "market": "sh", "category": "金融主题"},
        {"code": "512170", "name": "医疗ETF华宝", "market": "sh", "category": "医药主题"},
        {"code": "512010", "name": "医药ETF易方达", "market": "sh", "category": "医药主题"},
        {"code": "512760", "name": "半导体ETF国泰", "market": "sh", "category": "科技主题"},
        {"code": "515030", "name": "新能源车ETF华夏", "market": "sh", "category": "新能源主题"},
        {"code": "518880", "name": "黄金ETF华安", "market": "sh", "category": "避险资产"},
    ],
    # 国家队关键词（用于报告标记）
    "state_keywords": ["中央汇金", "证金", "社保", "国家队", "中投"],
    # 信号阈值（窗口累计净流入，单位：元）
    "signal_threshold": {
        "high": 50_000_000_000,  # 50亿以上 - 高置信度（国家队级别资金）
        "medium": 10_000_000_000,  # 10亿以上 - 中等置信度
        "low": 2_000_000_000,  # 2亿以上 - 关注级别
    },
}

DATA_DIR = "./data"
REPORT_DIR = "./reports"
# 归档根目录优先级: CLI参数 > 环境变量 ETF_TRACKER_ARCHIVE_DIR > reports/archive
ARCHIVE_ENV_VAR = "ETF_TRACKER_ARCHIVE_DIR"


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)


def _wind_http_fund(tool_name: str, params: dict) -> dict | None:
    """Wind MCP fund_data HTTP 直连 (urllib, 无新依赖)

    返回解析后的 SSE JSON dict, 或 None。
    """
    api_key = _get_wind_api_key()
    if not api_key:
        return None
    import json as _json
    import urllib.request

    payload = _json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": params},
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    try:
        # 绕过系统代理 (国内 Wind 端点直连)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(WIND_FUND_ENDPOINT, data=payload, headers=headers)
        resp = opener.open(req, timeout=60)
        text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Wind HTTP 调用失败: {e}")
        return None

    if not text or not text.strip():
        return None
    # SSE 解析: 提取 "data: {json}" 行
    for line in reversed(text.strip().split("\n")):
        line = line.strip()
        if line.startswith("data: "):
            try:
                return _json.loads(line[6:])
            except Exception:
                return None
    try:
        return _json.loads(text)
    except Exception:
        return None


def _parse_fund_kline_rows(sse_data: dict) -> list[dict]:
    """解析 Wind MCP fund_data K线响应 → [{date, close, volume, amount}, ...]

    fund_data 字段: TIME / OPEN / MATCH(收盘) / HIGH / LOW / TURNOVER(成交额) / VOLUME(成交量)
    """
    if not isinstance(sse_data, dict):
        return []
    result = sse_data.get("result") or sse_data.get("data") or {}
    content = result.get("content") if isinstance(result, dict) else None
    if not content and isinstance(sse_data.get("result"), dict):
        content = sse_data["result"].get("content")
    if not content or not isinstance(content, list):
        return []
    text = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
    try:
        import json as _json

        inner = _json.loads(text)
    except Exception:
        return []
    data = inner.get("data", inner)
    rows = data.get("rows", [])
    if not rows:
        return []
    # 字段索引映射
    columns = [c["name"].upper() for c in data.get("columns", [])]
    idx = {name: i for i, name in enumerate(columns)}
    parsed = []
    for row in rows:
        time_val = row[idx["TIME"]] if "TIME" in idx else ""
        date_str = str(time_val)[:10]  # 2026-09-01T... → 2026-09-01
        close = float(row[idx["MATCH"]]) if "MATCH" in idx and row[idx["MATCH"]] else 0
        volume = float(row[idx["VOLUME"]]) if "VOLUME" in idx and row[idx["VOLUME"]] else 0
        amount = float(row[idx["TURNOVER"]]) if "TURNOVER" in idx and row[idx["TURNOVER"]] else 0
        parsed.append({"date": date_str, "close": close, "volume": volume, "amount": amount})
    return parsed


def _fetch_wind_fund_kline(windcode: str, days: int) -> list[dict] | None:
    """通过 Wind MCP 获取 ETF K线 (前复权), 返回最近 days 个交易日"""
    import datetime as dt

    end_date = dt.datetime.now()
    start_date = end_date - dt.timedelta(days=int(days * 1.5) + 10)
    sse = _wind_http_fund(
        "get_fund_kline",
        {
            "windcode": windcode,
            "begin_date": start_date.strftime("%Y%m%d"),
            "end_date": end_date.strftime("%Y%m%d"),
            "price_type": 1,  # 前复权
        },
    )
    if not sse:
        return None
    rows = _parse_fund_kline_rows(sse)
    if not rows:
        return None
    return rows[-days:] if len(rows) > days else rows


# ==================== 数据获取层 ====================


def get_etf_basic_info(code: str, market: str) -> dict:
    """获取ETF实时行情 (Wind MCP优先 → akshare → 模拟数据)"""
    if _source_enabled("wind") and WIND_MCP_AVAILABLE:
        try:
            wind_code = f"{code}.{market.upper()}"
            # 用 K线最近 2 天推算行情: 最后一天 = 今日, 倒数第二天 = prev_close
            rows = _fetch_wind_fund_kline(wind_code, days=2)
            if rows and len(rows) >= 1:
                latest = rows[-1]
                close = latest["close"]
                prev_close = rows[-2]["close"] if len(rows) >= 2 else close
                change_pct = (close / prev_close - 1) * 100 if prev_close else 0.0
                return {
                    "code": code,
                    "name": next(
                        (e["name"] for e in CONFIG["etf_list"] if e["code"] == code), code
                    ),
                    "latest_price": close,
                    "change_pct": round(change_pct, 2),
                    "volume": int(latest["volume"]) if latest["volume"] else None,
                    "amount": latest["amount"],
                    "source": "Wind MCP",
                }
        except Exception as e:
            print(f"Wind MCP 获取 {code} 信息失败: {e}")

    # 备选：akshare（新浪接口无涨跌幅列，用相邻收盘价计算）
    if _source_enabled("akshare") and AK_AVAILABLE:
        try:
            import akshare as ak

            symbol = f"{market}{code}"
            df = ak.fund_etf_hist_sina(symbol=symbol)
            if df is not None and len(df) >= 2:
                latest = df.iloc[-1]
                prev_close = float(df.iloc[-2]["close"])
                close = float(latest["close"])
                change_pct = (close / prev_close - 1) * 100 if prev_close else 0.0
                return {
                    "code": code,
                    "name": next(
                        (e["name"] for e in CONFIG["etf_list"] if e["code"] == code), code
                    ),
                    "latest_price": close,
                    "change_pct": round(change_pct, 2),
                    "volume": int(latest.get("volume", 0)) if "volume" in df.columns else None,
                    "amount": float(latest.get("amount", 0)) if "amount" in df.columns else 0,
                    "source": "akshare",
                }
        except Exception as e:
            print(f"akshare 获取 {code} 信息失败: {e}")

    # 兜底：模拟数据
    if _source_enabled("mock"):
        kline = generate_mock_kline(code, days=1)
        row = kline[-1]
        return {
            "code": code,
            "name": next((e["name"] for e in CONFIG["etf_list"] if e["code"] == code), code),
            "latest_price": row["close"],
            "change_pct": row["change_pct"],
            "volume": row["volume"],
            "amount": row["amount"],
            "source": "模拟数据",
        }

    return {
        "code": code,
        "name": next((e["name"] for e in CONFIG["etf_list"] if e["code"] == code), code),
        "error": "所有数据源不可用",
    }


def get_etf_kline(code: str, market: str, days: int = 5) -> dict:
    """获取ETF K线数据用于计算资金流 (Wind MCP优先 → akshare → 模拟数据)"""
    if _source_enabled("wind") and WIND_MCP_AVAILABLE:
        try:
            wind_code = f"{code}.{market.upper()}"
            # 取 days+1 条用于计算首日涨跌幅
            rows = _fetch_wind_fund_kline(wind_code, days=days + 1)
            if rows and len(rows) >= 1:
                kline_data = []
                for i, row in enumerate(rows):
                    close = row["close"]
                    prev_close = rows[i - 1]["close"] if i > 0 else close
                    change_pct = (close / prev_close - 1) * 100 if prev_close else 0.0
                    amount = row["amount"]
                    kline_data.append(
                        {
                            "date": row["date"],
                            "close": close,
                            "change_pct": round(change_pct, 2),
                            "volume": row["volume"],
                            "amount": amount,
                            "net_flow": amount * (1 if change_pct >= 0 else -1),
                        }
                    )
                # 只保留最近 days 天
                kline_data = kline_data[-days:]
                return {"code": code, "kline": kline_data, "source": "Wind MCP"}
        except Exception as e:
            print(f"Wind MCP 获取 {code} K线失败: {e}")

    # 备选：akshare（新浪接口无涨跌幅列，用 pct_change 计算）
    if _source_enabled("akshare") and AK_AVAILABLE:
        try:
            import akshare as ak

            symbol = f"{market}{code}"
            df = ak.fund_etf_hist_sina(symbol=symbol)
            if df is not None and len(df) >= 2:
                df = df.assign(change_pct=lambda d: d["close"].pct_change().fillna(0) * 100)
                recent = df.tail(days).reset_index(drop=True)
                kline_data = []
                for _, row in recent.iterrows():
                    amount = float(row.get("amount", row.get("volume", 0)))
                    change_pct = float(row.get("change_pct", 0))
                    kline_data.append(
                        {
                            "date": str(row.get("date", "")),
                            "close": float(row.get("close", 0)),
                            "change_pct": round(change_pct, 2),
                            "volume": float(row.get("volume", 0)),
                            "amount": amount,
                            "net_flow": amount * (1 if change_pct >= 0 else -1),
                        }
                    )
                return {"code": code, "kline": kline_data, "source": "akshare"}
        except Exception as e:
            print(f"akshare 获取 {code} K线失败: {e}")

    # 兜底：模拟数据
    if _source_enabled("mock"):
        return {"code": code, "kline": generate_mock_kline(code, days=days), "source": "模拟数据"}

    return {"code": code, "error": "所有数据源不可用"}


def get_etf_scale_ranking(etf_info: dict) -> dict:
    """
    构建ETF规模/成交额TOP20排名
    复用已采集的行情数据（etf_info），避免重复请求
    """
    print("  → 正在构建ETF规模TOP20排名...")

    scale_list = []
    for etf in CONFIG["etf_list"]:
        basic = etf_info.get(etf["code"], {})
        if "error" in basic or not basic:
            continue
        amount = basic.get("amount", 0) or 0  # 成交额作为活跃度代理
        scale_list.append(
            {
                "代码": etf["code"],
                "名称": basic.get("name", etf["name"]),
                "最新价": basic.get("latest_price", 0),
                "涨跌幅%": round(basic.get("change_pct", 0), 2),
                "成交额(亿)": round(amount / 1e8, 2) if amount else 0,
                "类别": etf.get("category", ""),
            }
        )

    # 按成交额降序排列
    scale_list.sort(key=lambda x: x.get("成交额(亿)", 0), reverse=True)

    return {
        "top_etf_by_scale": scale_list,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Wind MCP / akshare 实时数据",
    }


# ==================== 分析层 ====================


def calculate_fund_flow_summary(etf_list: list, days: int = 5) -> list:
    """
    计算每只ETF的N日资金流汇总
    返回：按窗口累计净流入降序的列表
    """
    results = []
    for etf in etf_list:
        code = etf["code"]
        name = etf["name"]
        category = etf.get("category", "")

        # 获取K线数据
        kline_result = get_etf_kline(code, etf["market"], days=days)
        if "error" in kline_result:
            continue

        kline = kline_result["kline"]
        if not kline:
            continue

        # 计算汇总
        total_net_flow = sum(k["net_flow"] for k in kline)
        avg_flow = total_net_flow / len(kline) if kline else 0
        positive_days = sum(1 for k in kline if k["net_flow"] > 0)
        latest_price = kline[-1]["close"]
        latest_change = kline[-1]["change_pct"]
        latest_amount = kline[-1]["amount"]

        # 连续流入/流出判断
        trend = "中性"
        if all(k["net_flow"] > 0 for k in kline):
            trend = "连续流入"
        elif all(k["net_flow"] < 0 for k in kline):
            trend = "连续流出"
        elif positive_days >= len(kline) - 1:
            trend = "以流入为主"
        elif len(kline) - positive_days >= len(kline) - 1:
            trend = "以流出为主"

        results.append(
            {
                "code": code,
                "name": name,
                "category": category,
                "latest_price": round(latest_price, 4),
                "change_pct": round(latest_change, 2),
                "daily_amount_yi": round(latest_amount / 1e8, 2),  # 亿元
                "total_net_flow_yi": round(total_net_flow / 1e8, 2),
                "avg_net_flow_yi": round(avg_flow / 1e8, 2),
                "positive_days": f"{positive_days}/{len(kline)}",
                "trend": trend,
                "source": kline_result["source"],
                # 详细每日数据（用于可视化）
                "daily_flows": [
                    {"date": k["date"], "flow_yi": round(k["net_flow"] / 1e8, 2)} for k in kline
                ],
            }
        )

    # 按窗口累计净流入降序
    results.sort(key=lambda x: x["total_net_flow_yi"], reverse=True)
    return results


def detect_state_fund_signals(flow_results: list) -> list:
    """
    检测国家队加仓/减仓信号
    逻辑：
    - 高置信度：窗口累计净流入 >= 50亿 且 连续流入/以流入为主
    - 中置信度：窗口累计净流入 >= 10亿
    - 低置信度（关注）：窗口累计净流入 >= 2亿
    - 反向减仓信号同理
    """
    signals = []
    for item in flow_results:
        total_flow_yi = item["total_net_flow_yi"]
        trend = item["trend"]

        # 加仓信号
        if total_flow_yi >= 50 and trend in ["连续流入", "以流入为主"]:
            confidence = "高"
            signal_type = "强加仓信号"
        elif total_flow_yi >= 50:
            confidence = "高"
            signal_type = "大额加仓信号"
        elif total_flow_yi >= 10:
            confidence = "中"
            signal_type = "加仓信号"
        elif total_flow_yi >= 2:
            confidence = "低"
            signal_type = "关注信号"
        # 减仓信号
        elif total_flow_yi <= -50:
            confidence = "高"
            signal_type = "强减仓信号"
        elif total_flow_yi <= -10:
            confidence = "中"
            signal_type = "减仓信号"
        elif total_flow_yi <= -2:
            confidence = "低"
            signal_type = "关注信号(流出)"
        else:
            continue

        signals.append(
            {
                **item,
                "signal_type": signal_type,
                "confidence": confidence,
            }
        )

    return signals


def visualize_flow_bars(flow_data: list, max_bars: int = 50) -> str:
    """
    ASCII可视化资金流柱状图
    正数用 █ 表示，负数用 ░ 表示
    """
    if not flow_data:
        return "无数据"

    # 归一化到 max_bars 个字符
    max_abs = max(abs(d["flow_yi"]) for d in flow_data) if flow_data else 1
    if max_abs == 0:
        return "无数据"

    visualization = []
    for d in flow_data:
        flow = d["flow_yi"]
        # 映射到字符长度
        length = int(abs(flow) / max_abs * max_bars)
        if length == 0 and abs(flow) > 0.01:
            length = 1
        if flow >= 0:
            bar = "█" * length + " " * (max_bars - length)
            marker = f" [+{flow:.2f}亿]"
        else:
            bar = "░" * length + " " * (max_bars - length)
            marker = f" [{flow:.2f}亿]"

        # 日期显示
        date_short = (
            d["date"][5:] if isinstance(d["date"], str) and len(d["date"]) > 5 else str(d["date"])
        )
        visualization.append(f"  {date_short} │ {bar} {marker}")

    return "\n".join(visualization)


# ==================== CLI ====================


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="ETF 国家队资金监测系统 - 追踪国家队 ETF 资金流向信号"
    )
    parser.add_argument("--days", type=int, default=5, help="资金流监测窗口天数（默认5）")
    parser.add_argument(
        "--source",
        choices=["auto", "wind", "akshare", "mock"],
        default="auto",
        help="数据源模式：auto按优先级降级 / 强制指定单一数据源",
    )
    parser.add_argument("--top", type=int, default=15, help="报告展示的排名条数（默认15）")
    parser.add_argument("--no-archive", action="store_true", help="不归档到每日报告目录")
    parser.add_argument(
        "--archive-dir",
        default=None,
        help=f"归档根目录（默认读取环境变量 {ARCHIVE_ENV_VAR}，再退回 reports/archive）",
    )
    return parser.parse_args(argv)


# ==================== 报告生成 ====================


def generate_report(window_days: int = 5, top_n: int = 15) -> tuple:
    """生成追踪报告，返回 (report_file, report_content)"""
    ensure_dirs()

    report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_date = datetime.now().strftime("%Y%m%d")
    report_file = os.path.join(REPORT_DIR, f"report_{report_date}.md")

    print(f"\n{'=' * 60}")
    print("  ETF 国家队资金监测系统")
    print(f"  监测标的数量: {len(CONFIG['etf_list'])} 只 | 监测窗口: {window_days} 日")
    print(
        f"  数据源模式: {SOURCE_MODE} | Wind MCP: {'可用' if WIND_MCP_AVAILABLE else '不可用'} | akshare: {'可用' if AK_AVAILABLE else '不可用'}"
    )
    print(f"  报告时间: {report_time}")
    print(f"{'=' * 60}\n")

    # ============ 数据采集 ============
    print("📊 正在获取实时行情...")
    etf_info = {}
    for etf in CONFIG["etf_list"]:
        info = get_etf_basic_info(etf["code"], etf["market"])
        etf_info[etf["code"]] = info

    print(f"💰 正在计算{window_days}日资金流向...")
    flow_results = calculate_fund_flow_summary(CONFIG["etf_list"], days=window_days)

    print("📈 正在检测国家队信号...")
    signals = detect_state_fund_signals(flow_results)

    print("🏆 正在构建规模TOP20排名...")
    scale_ranking = get_etf_scale_ranking(etf_info)

    # 检测使用的数据源
    data_sources = set()
    for info in etf_info.values():
        if "source" in info:
            data_sources.add(info["source"])
    for f in flow_results:
        if "source" in f:
            data_sources.add(f["source"])
    if scale_ranking and "source" in scale_ranking:
        data_sources.add(scale_ranking["source"])

    # ============ 生成 Markdown 报告 ============
    report = f"""# 📊 ETF 国家队资金监测报告

**生成时间**：{report_time}
**数据来源**：{", ".join(sorted(data_sources)) if data_sources else "Wind MCP / akshare"}
**监测标的**：{len(CONFIG["etf_list"])} 只主流宽基ETF | **监测窗口**：{window_days} 日

---

## 📈 一、今日行情速览（按成交额排序）

"""

    # 今日行情表（按成交额排序）
    sorted_by_amount = sorted(
        [v for v in flow_results if "error" not in (etf_info.get(v["code"], {}))],
        key=lambda x: x["daily_amount_yi"],
        reverse=True,
    )[:top_n]

    report += "| 排名 | ETF名称 | 代码 | 最新价 | 涨跌幅 | 成交额(亿) | 类别 |\n"
    report += "|------|---------|------|--------|--------|-----------|------|\n"
    for i, item in enumerate(sorted_by_amount, 1):
        change_str = (
            f"**+{item['change_pct']}%**" if item["change_pct"] >= 0 else f"*{item['change_pct']}%*"
        )
        report += f"| {i} | {item['name']} | {item['code']} | {item['latest_price']} | {change_str} | {item['daily_amount_yi']} | {item['category']} |\n"

    report += f"""

## 🔥 二、国家队信号检测

> **信号判定规则**
> - 🔴 **高置信度**：{window_days}日净流入 ≥ 50亿 或 ≤ -50亿，且连续资金趋势一致
> - 🟡 **中置信度**：{window_days}日净流入 ≥ 10亿 或 ≤ -10亿
> - 🟢 **低置信度**：{window_days}日净流入 ≥ 2亿 或 ≤ -2亿（关注级别）

**检测到 {len(signals)} 条潜在信号**

"""

    if signals:
        # 按置信度分组
        high_conf = [s for s in signals if s["confidence"] == "高"]
        medium_conf = [s for s in signals if s["confidence"] == "中"]
        low_conf = [s for s in signals if s["confidence"] == "低"]

        if high_conf:
            report += "\n### 🔴 高置信度信号\n"
            report += "| ETF名称 | 代码 | 累计净流入(亿) | 资金趋势 | 信号 |\n"
            report += "|---------|------|-------------|---------|------|\n"
            for s in high_conf[:10]:
                report += f"| {s['name']} | {s['code']} | **{s['total_net_flow_yi']}** | {s['trend']} | {s['signal_type']} |\n"

        if medium_conf:
            report += "\n### 🟡 中置信度信号\n"
            report += "| ETF名称 | 代码 | 累计净流入(亿) | 资金趋势 | 信号 |\n"
            report += "|---------|------|-------------|---------|------|\n"
            for s in medium_conf[:10]:
                report += f"| {s['name']} | {s['code']} | {s['total_net_flow_yi']} | {s['trend']} | {s['signal_type']} |\n"

        if low_conf:
            report += "\n### 🟢 关注级信号\n"
            report += "| ETF名称 | 代码 | 累计净流入(亿) | 资金趋势 |\n"
            report += "|---------|------|-------------|---------|\n"
            for s in low_conf[:10]:
                report += (
                    f"| {s['name']} | {s['code']} | {s['total_net_flow_yi']} | {s['trend']} |\n"
                )
    else:
        report += "> 📉 近期未检测到明显的国家队操作信号\n"

    # ============ 资金流TOP10 ============
    report += f"""

## 💰 三、{window_days}日资金流向TOP10（国家队重点关注）

"""

    # 取净流入前10
    top10_inflow = flow_results[:10]

    # 整体流入流出统计
    total_inflow = sum(max(x["total_net_flow_yi"], 0) for x in flow_results)
    total_outflow = sum(abs(min(x["total_net_flow_yi"], 0)) for x in flow_results)
    net_flow = total_inflow - total_outflow

    report += f"""
**整体资金流向汇总**
- 📥 总净流入：**{total_inflow:.2f} 亿元**
- 📤 总净流出：**{total_outflow:.2f} 亿元**
- 📊 净资金流向：**{"净流入" if net_flow >= 0 else "净流出"} {abs(net_flow):.2f} 亿元**

"""

    report += "| 排名 | ETF名称 | 代码 | 类别 | 累计净流入(亿) | 日均净流入(亿) | 资金趋势 |\n"
    report += "|------|---------|------|------|-------------|---------------|---------|\n"
    for i, item in enumerate(top10_inflow, 1):
        report += f"| {i} | {item['name']} | {item['code']} | {item['category']} | {item['total_net_flow_yi']} | {item['avg_net_flow_yi']} | {item['trend']} |\n"

    # ============ 重点标的可视化 ============
    report += f"""

## 📊 四、重点标的资金流趋势图（近{window_days}日）

**图例**：`█` 净流入 | `░` 净流出

"""

    # 显示TOP5净流入和TOP3净流出的可视化（净流出按流出最大在前）
    top5 = flow_results[:5]
    bottom3 = sorted(
        (x for x in flow_results if x["total_net_flow_yi"] < 0),
        key=lambda x: x["total_net_flow_yi"],
    )[:3]
    to_visualize = top5 + bottom3

    for item in to_visualize:
        report += f"\n### {item['name']} ({item['code']}) - {window_days}日净流入: **{item['total_net_flow_yi']}亿**\n"
        report += "```\n"
        report += visualize_flow_bars(item["daily_flows"])
        report += "\n```\n"
        report += f"资金趋势：**{item['trend']}**\n"

    # ============ 规模排名TOP15 ============
    report += f"""

## 🏆 五、ETF规模/成交额TOP{top_n}（国家队重点持仓参考）

> 注：以成交额排名间接反映资金关注度和ETF活跃度

"""

    if scale_ranking and "top_etf_by_scale" in scale_ranking:
        report += "| 排名 | ETF名称 | 代码 | 类别 | 最新价 | 涨跌幅% | 成交额(亿) |\n"
        report += "|------|---------|------|------|--------|---------|-----------|\n"
        for i, etf in enumerate(scale_ranking["top_etf_by_scale"][:top_n], 1):
            report += f"| {i} | {etf.get('名称', '-')} | {etf.get('代码', '-')} | {etf.get('类别', '-')} | {etf.get('最新价', '-')} | {etf.get('涨跌幅%', '-')} | {etf.get('成交额(亿)', '-')} |\n"
    else:
        report += "> 暂无可用数据\n"

    # ============ 风险提示 ============
    report += """

## ⚠️ 六、风险提示

1. **资金流为估算值**：本系统通过K线成交额与涨跌幅估算资金流向，与ETF实际申购赎回数据存在差异
2. **国家队动作的推断性**：大额资金流可能是国家队操作，也可能是机构、外资等其他主体
3. **滞后性**：本系统为T+1监测，不包含实时交易信号
4. **仅供参考**：本报告不构成投资建议，投资需谨慎

---

## 📋 七、全量监测标的明细

"""

    report += "| 代码 | ETF名称 | 类别 | 最新价 | 涨跌幅% | 成交额(亿) | 累计净流入(亿) | 正流天数 | 资金趋势 |\n"
    report += "|------|---------|------|--------|---------|-----------|-------------|---------|---------|\n"
    for item in flow_results:
        report += f"| {item['code']} | {item['name']} | {item['category']} | {item['latest_price']} | {item['change_pct']}% | {item['daily_amount_yi']} | {item['total_net_flow_yi']} | {item['positive_days']} | {item['trend']} |\n"

    report += f"""

---

*本报告由 ETF 国家队监测系统自动生成*
*数据来源于 Wind MCP Skill / akshare，资金流为估算值，仅供参考*
*生成时间：{report_time}*
"""

    # 保存报告
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    # 同时保存最新报告为 latest.md
    latest_file = os.path.join(REPORT_DIR, "latest.md")
    with open(latest_file, "w", encoding="utf-8") as f:
        f.write(report)

    # ============ 控制台摘要输出 ============
    print(f"\n{'=' * 60}")
    print(f"  ✅ 报告生成完成: {report_file}")
    print(f"{'=' * 60}")

    # 控制台打印信号摘要
    if signals:
        print("\n🔴 国家队信号摘要:")
        for s in signals[:5]:
            print(
                f"  [{s['confidence']}] {s['signal_type']}: {s['name']} ({s['code']}) "
                f"→ {window_days}日净流入 {s['total_net_flow_yi']}亿, 趋势: {s['trend']}"
            )
    else:
        print("\n📉 未检测到明显的国家队操作信号")

    # 控制台打印资金流摘要
    print("\n💰 整体资金流:")
    print(f"  📥 总净流入: {total_inflow:.2f} 亿")
    print(f"  📤 总净流出: {total_outflow:.2f} 亿")
    print(f"  📊 净资金流向: {'净流入' if net_flow >= 0 else '净流出'} {abs(net_flow):.2f} 亿")

    print("\n📈 净流入TOP5:")
    for item in flow_results[:5]:
        print(f"  {item['name']} ({item['code']}): +{item['total_net_flow_yi']}亿, {item['trend']}")

    print("\n📉 净流出TOP3:")
    for item in sorted(
        (x for x in flow_results if x["total_net_flow_yi"] < 0),
        key=lambda x: x["total_net_flow_yi"],
    )[:3]:
        print(f"  {item['name']} ({item['code']}): {item['total_net_flow_yi']}亿, {item['trend']}")

    return report_file, report


def archive_to_daily_reports(report_content: str, archive_root: str | None = None) -> str:
    """将报告归档至每日报告归档目录"""
    today = datetime.now().strftime("%Y-%m-%d")
    if archive_root is None:
        archive_root = os.environ.get(ARCHIVE_ENV_VAR, os.path.join(REPORT_DIR, "archive"))
    archive_dir = os.path.join(archive_root, today)
    os.makedirs(archive_dir, exist_ok=True)
    report_date = datetime.now().strftime("%Y%m%d")
    archive_file = os.path.join(archive_dir, f"ETF资金监测_{report_date}.md")
    with open(archive_file, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"  📁 已归档至: {archive_file}")
    return archive_file


def run_tracker(args) -> tuple:
    """运行追踪器"""
    report_file, report_content = generate_report(window_days=args.days, top_n=args.top)
    if not args.no_archive:
        archive_to_daily_reports(report_content, archive_root=args.archive_dir)
    return report_file, report_content


def main(argv=None):
    global SOURCE_MODE
    args = parse_args(argv)
    SOURCE_MODE = args.source
    run_tracker(args)


if __name__ == "__main__":
    main()
