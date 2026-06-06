"""
ETF 国家队资金监测系统
追踪中央汇金等国家队 ETF 持仓变化

核心逻辑：
1. 覆盖20+主流宽基ETF实时行情
2. 通过K线成交额+涨跌幅估算资金净流入
3. 连续5日资金流趋势检测→国家队加仓/减仓信号
4. 自动构建ETF规模TOP20排名

数据来源: Wind MCP Skill (优先) / akshare (备选)
"""

import pandas as pd
from datetime import datetime, timedelta
import json
import os
import subprocess

# ==================== 数据源抽象 ====================
WIND_MCP_AVAILABLE = True
WIND_MCP_PATH = os.path.join(os.path.expanduser("~"), ".agents", "skills", "wind-mcp-skill")

try:
    import akshare as ak
    AK_AVAILABLE = True
except ImportError:
    AK_AVAILABLE = False

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
        {"code": "512890", "name": "红利低波100ETF华泰柏瑞", "market": "sh", "category": "防御红利"},
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
    # 信号阈值（5日累计净流入）
    "signal_threshold": {
        "high": 50_000_000_000,   # 50亿以上 - 高置信度（国家队级别资金）
        "medium": 10_000_000_000,  # 10亿以上 - 中等置信度
        "low": 2_000_000_000,      # 2亿以上 - 关注级别
    },
}

DATA_DIR = "./data"
REPORT_DIR = "./reports"


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)


def _call_wind_mcp(server_type, tool_name, params):
    """调用Wind MCP Skill"""
    try:
        import json
        temp_script = os.path.join(WIND_MCP_PATH, 'temp_call.js')
        params_json = json.dumps(params)

        script_content = f"""
const {{ spawnSync }} = require('child_process');
const params = {params_json};
const args = ['scripts/cli.mjs', 'call', '{server_type}', '{tool_name}', JSON.stringify(params)];
const result = spawnSync('node', args, {{ encoding: 'utf-8' }});
if (result.error) {{
    console.log(JSON.stringify({{ok: false, error: {{code: 'SPAWN_ERROR', agent_action: result.error.message}}}}));
    process.exit(1);
}}
if (result.status !== 0) {{
    console.log(result.stdout || result.stderr);
    process.exit(result.status);
}}
console.log(result.stdout);
"""

        with open(temp_script, 'w', encoding='utf-8') as f:
            f.write(script_content)

        result = subprocess.run(['node', 'temp_call.js'], shell=True, cwd=WIND_MCP_PATH,
                               capture_output=True, text=True, encoding='utf-8')

        if os.path.exists(temp_script):
            os.remove(temp_script)

        if result.returncode == 0:
            output = json.loads(result.stdout)
            if 'content' in output:
                text_content = output['content'][0]['text']
                return json.loads(text_content)
            return output
        else:
            try:
                error = json.loads(result.stdout)
                print(f"Wind MCP 错误: {error.get('error', {}).get('agent_action', '未知错误')}")
            except:
                print(f"Wind MCP 调用失败: {result.stderr}")
            return None
    except Exception as e:
        print(f"Wind MCP 调用异常: {e}")
        return None


# ==================== 数据获取层 ====================

def get_etf_basic_info(code: str, market: str) -> dict:
    """获取ETF实时行情 (Wind MCP优先)"""
    if WIND_MCP_AVAILABLE:
        try:
            wind_code = f"{code}.{market.upper()}"
            result = _call_wind_mcp('fund_data', 'get_fund_price_indicators',
                                  {'windcode': wind_code,
                                   'indexes': '中文简称,最新成交价,涨跌幅,成交量,成交额'})
            if result and 'data' in result and result['data'].get('rows'):
                rows = result['data']['rows']
                if rows:
                    row = rows[0]
                    return {
                        "code": code,
                        "name": row[0] if row[0] else code,
                        "latest_price": float(row[1]) if row[1] else None,
                        "change_pct": float(row[2]) if row[2] else 0,
                        "volume": int(row[3]) if row[3] else None,
                        "amount": float(row[4]) if row[4] else 0,
                        "source": "Wind MCP"
                    }
        except Exception as e:
            print(f"Wind MCP 获取 {code} 信息失败: {e}")

    # 备选：akshare
    if AK_AVAILABLE:
        try:
            symbol = f"{market}{code}"
            df = ak.fund_etf_hist_sina(symbol=symbol)
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                return {
                    "code": code,
                    "name": next((e["name"] for e in CONFIG["etf_list"] if e["code"] == code), code),
                    "latest_price": float(latest["close"]) if "close" in df.columns else None,
                    "change_pct": float(latest.get("change_pct", 0)),
                    "volume": int(latest.get("volume", 0)) if "volume" in df.columns else None,
                    "amount": float(latest.get("amount", 0)) if "amount" in df.columns else 0,
                    "source": "akshare"
                }
        except Exception as e:
            print(f"akshare 获取 {code} 信息失败: {e}")

    return {"code": code,
            "name": next((e["name"] for e in CONFIG["etf_list"] if e["code"] == code), code),
            "error": "所有数据源不可用"}


def get_etf_kline(code: str, market: str, days: int = 5) -> dict:
    """获取ETF K线数据用于计算资金流 (Wind MCP优先)"""
    if WIND_MCP_AVAILABLE:
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days + 10)
            wind_code = f"{code}.{market.upper()}"
            result = _call_wind_mcp('fund_data', 'get_fund_kline',
                                  {'windcode': wind_code,
                                   'begin_date': start_date.strftime("%Y%m%d"),
                                   'end_date': end_date.strftime("%Y%m%d"),
                                   'count': days})
            if result and 'data' in result and result['data'].get('rows'):
                rows = result['data']['rows'][-days:]
                kline_data = []
                for row in rows:
                    date_str = row[0] if isinstance(row[0], str) else str(row[0])
                    close = float(row[2]) if row[2] else 0
                    change_pct = float(row[7]) if len(row) > 7 and row[7] else 0
                    volume = float(row[5]) if row[5] else 0
                    amount = float(row[6]) if row[6] else 0
                    kline_data.append({
                        "date": date_str,
                        "close": close,
                        "change_pct": change_pct,
                        "volume": volume,
                        "amount": amount,
                        # 资金流估算公式：(收盘价-开盘价)/(最高价-最低价) * 成交额
                        # 简化版：若涨跌幅>0视为净流入，<0视为净流出，权重=成交额*涨跌方向
                        "net_flow": amount * (1 if change_pct >= 0 else -1)
                    })
                return {
                    "code": code,
                    "kline": kline_data,
                    "source": "Wind MCP"
                }
        except Exception as e:
            print(f"Wind MCP 获取 {code} K线失败: {e}")

    # 备选：akshare
    if AK_AVAILABLE:
        try:
            symbol = f"{market}{code}"
            df = ak.fund_etf_hist_sina(symbol=symbol)
            if df is not None and len(df) >= days:
                recent = df.tail(days).reset_index(drop=True)
                kline_data = []
                for idx, row in recent.iterrows():
                    amount = float(row.get("amount", row.get("volume", 0)))
                    change_pct = float(row.get("change_pct", 0))
                    kline_data.append({
                        "date": str(row.get("date", "")),
                        "close": float(row.get("close", 0)),
                        "change_pct": change_pct,
                        "volume": float(row.get("volume", 0)),
                        "amount": amount,
                        "net_flow": amount * (1 if change_pct >= 0 else -1)
                    })
                return {"code": code, "kline": kline_data, "source": "akshare"}
        except Exception as e:
            print(f"akshare 获取 {code} K线失败: {e}")

    return {"code": code, "error": "所有数据源不可用"}


def get_etf_scale_ranking() -> dict:
    """
    构建ETF规模TOP20排名
    方法：遍历监控列表，获取每只ETF最新规模数据，再按规模排序
    """
    print("  → 正在构建ETF规模TOP20排名...")

    scale_list = []
    for etf in CONFIG["etf_list"]:
        try:
            # 用基本信息获取成交额作为规模代理（Wind MCP没有直接的fund规模查询API）
            basic = get_etf_basic_info(etf["code"], etf["market"])
            if "error" not in basic:
                # 用成交额 × 当前价 作为规模代理
                scale_estimate = (basic.get("amount", 0) or 0)  # 成交额
                scale_list.append({
                    "代码": etf["code"],
                    "名称": basic.get("name", etf["name"]),
                    "最新价": basic.get("latest_price", 0),
                    "涨跌幅%": round(basic.get("change_pct", 0), 2),
                    "成交额(亿)": round(scale_estimate / 1e8, 2) if scale_estimate else 0,
                    "类别": etf.get("category", ""),
                })
        except Exception as e:
            continue

    # 按成交额降序排列
    scale_list.sort(key=lambda x: x.get("成交额(亿)", 0), reverse=True)

    return {
        "top_etf_by_scale": scale_list,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Wind MCP / akshare 实时数据",
    }


# ==================== 分析层 ====================

def calculate_fund_flow_summary(etf_list: list) -> list:
    """
    计算每只ETF的5日资金流汇总
    返回：按5日净流入降序的列表
    """
    results = []
    for etf in etf_list:
        code = etf["code"]
        name = etf["name"]
        category = etf.get("category", "")

        # 获取K线数据
        kline_result = get_etf_kline(code, etf["market"], days=5)
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
        elif sum(1 for k in kline if k["net_flow"] > 0) >= 4:
            trend = "以流入为主"
        elif sum(1 for k in kline if k["net_flow"] < 0) >= 4:
            trend = "以流出为主"

        results.append({
            "code": code,
            "name": name,
            "category": category,
            "latest_price": round(latest_price, 4),
            "change_pct": round(latest_change, 2),
            "daily_amount_yi": round(latest_amount / 1e8, 2),  # 亿元
            "5日净流入_亿": round(total_net_flow / 1e8, 2),
            "日均净流入_亿": round(avg_flow / 1e8, 2),
            "正流天数": f"{positive_days}/5",
            "资金趋势": trend,
            "source": kline_result["source"],
            # 详细每日数据（用于可视化）
            "daily_flows": [
                {"date": k["date"], "flow_yi": round(k["net_flow"] / 1e8, 2)}
                for k in kline
            ]
        })

    # 按5日净流入降序
    results.sort(key=lambda x: x["5日净流入_亿"], reverse=True)
    return results


def detect_state_fund_signals(flow_results: list) -> list:
    """
    检测国家队加仓/减仓信号
    逻辑：
    - 高置信度：5日净流入 >= 50亿 且 连续流入/以流入为主
    - 中置信度：5日净流入 >= 10亿 且 正流天数>=3
    - 低置信度（关注）：5日净流入 >= 2亿
    - 反向减仓信号同理
    """
    signals = []
    for item in flow_results:
        total_flow_yi = item["5日净流入_亿"]
        trend = item["资金趋势"]

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

        signals.append({
            **item,
            "signal_type": signal_type,
            "confidence": confidence,
        })

    return signals


def visualize_flow_bars(flow_data: list, max_bars: int = 50) -> str:
    """
    ASCII可视化资金流柱状图
    正数用 █ 绿色系表示，负数用 ░ 红色系表示
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
        date_short = d["date"][5:] if isinstance(d["date"], str) and len(d["date"]) > 5 else str(d["date"])
        visualization.append(f"  {date_short} │ {bar} {marker}")

    return "\n".join(visualization)


# ==================== 报告生成 ====================

def generate_report() -> str:
    """生成追踪报告"""
    ensure_dirs()

    report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_date = datetime.now().strftime("%Y%m%d")
    report_file = os.path.join(REPORT_DIR, f"report_{report_date}.md")

    print(f"\n{'='*60}")
    print(f"  ETF 国家队资金监测系统")
    print(f"  监测标的数量: {len(CONFIG['etf_list'])} 只")
    print(f"  报告时间: {report_time}")
    print(f"{'='*60}\n")

    # ============ 数据采集 ============
    print("📊 正在获取实时行情...")
    etf_info = {}
    for etf in CONFIG["etf_list"]:
        info = get_etf_basic_info(etf["code"], etf["market"])
        etf_info[etf["code"]] = info

    print("💰 正在计算5日资金流向...")
    flow_results = calculate_fund_flow_summary(CONFIG["etf_list"])

    print("📈 正在检测国家队信号...")
    signals = detect_state_fund_signals(flow_results)

    print("🏆 正在构建规模TOP20排名...")
    scale_ranking = get_etf_scale_ranking()

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
**数据来源**：{', '.join(sorted(data_sources)) if data_sources else 'Wind MCP / akshare'}
**监测标的**：{len(CONFIG['etf_list'])} 只主流宽基ETF

---

## 📈 一、今日行情速览（按成交额排序）

"""

    # 今日行情表（按成交额排序）
    sorted_by_amount = sorted(
        [v for v in flow_results if "error" not in (etf_info.get(v["code"], {}))],
        key=lambda x: x["daily_amount_yi"],
        reverse=True
    )[:15]

    report += "| 排名 | ETF名称 | 代码 | 最新价 | 涨跌幅 | 成交额(亿) | 类别 |\n"
    report += "|------|---------|------|--------|--------|-----------|------|\n"
    for i, item in enumerate(sorted_by_amount, 1):
        change_str = f"**+{item['change_pct']}%**" if item['change_pct'] >= 0 else f"*{item['change_pct']}%*"
        report += f"| {i} | {item['name']} | {item['code']} | {item['latest_price']} | {change_str} | {item['daily_amount_yi']} | {item['category']} |\n"

    report += f"""

## 🔥 二、国家队信号检测

> **信号判定规则**
> - 🔴 **高置信度**：5日净流入 ≥ 50亿 或 ≤ -50亿，且连续资金趋势一致
> - 🟡 **中置信度**：5日净流入 ≥ 10亿 或 ≤ -10亿
> - 🟢 **低置信度**：5日净流入 ≥ 2亿 或 ≤ -2亿（关注级别）

**检测到 {len(signals)} 条潜在信号**

"""

    if signals:
        # 按置信度分组
        high_conf = [s for s in signals if s["confidence"] == "高"]
        medium_conf = [s for s in signals if s["confidence"] == "中"]
        low_conf = [s for s in signals if s["confidence"] == "低"]

        if high_conf:
            report += "\n### 🔴 高置信度信号\n"
            report += "| ETF名称 | 代码 | 5日净流入(亿) | 资金趋势 | 信号 |\n"
            report += "|---------|------|-------------|---------|------|\n"
            for s in high_conf[:10]:
                report += f"| {s['name']} | {s['code']} | **{s['5日净流入_亿']}** | {s['资金趋势']} | {s['signal_type']} |\n"

        if medium_conf:
            report += "\n### 🟡 中置信度信号\n"
            report += "| ETF名称 | 代码 | 5日净流入(亿) | 资金趋势 | 信号 |\n"
            report += "|---------|------|-------------|---------|------|\n"
            for s in medium_conf[:10]:
                report += f"| {s['name']} | {s['code']} | {s['5日净流入_亿']} | {s['资金趋势']} | {s['signal_type']} |\n"

        if low_conf:
            report += "\n### 🟢 关注级信号\n"
            report += "| ETF名称 | 代码 | 5日净流入(亿) | 资金趋势 |\n"
            report += "|---------|------|-------------|---------|\n"
            for s in low_conf[:10]:
                report += f"| {s['name']} | {s['code']} | {s['5日净流入_亿']} | {s['资金趋势']} |\n"
    else:
        report += "> 📉 近期未检测到明显的国家队操作信号\n"

    # ============ 资金流TOP10 ============
    report += f"""

## 💰 三、5日资金流向TOP10（国家队重点关注）

"""

    # 取净流入前10
    top10_inflow = flow_results[:10]

    # 整体流入流出统计
    total_inflow = sum(max(x["5日净流入_亿"], 0) for x in flow_results)
    total_outflow = sum(abs(min(x["5日净流入_亿"], 0)) for x in flow_results)
    net_flow = total_inflow - total_outflow

    report += f"""
**整体资金流向汇总**
- 📥 总净流入：**{total_inflow:.2f} 亿元**
- 📤 总净流出：**{total_outflow:.2f} 亿元**
- 📊 净资金流向：**{'净流入' if net_flow >= 0 else '净流出'} {abs(net_flow):.2f} 亿元**

"""

    report += "| 排名 | ETF名称 | 代码 | 类别 | 5日净流入(亿) | 日均净流入(亿) | 资金趋势 |\n"
    report += "|------|---------|------|------|-------------|---------------|---------|\n"
    for i, item in enumerate(top10_inflow, 1):
        report += f"| {i} | {item['name']} | {item['code']} | {item['category']} | {item['5日净流入_亿']} | {item['日均净流入_亿']} | {item['资金趋势']} |\n"

    # ============ 重点标的可视化 ============
    report += f"""

## 📊 四、重点标的资金流趋势图（近5日）

**图例**：`█` 净流入 | `░` 净流出

"""

    # 显示TOP5净流入和TOP3净流出的可视化
    top5 = flow_results[:5]
    bottom3 = [x for x in flow_results if x["5日净流入_亿"] < 0][:3]
    to_visualize = top5 + bottom3

    for item in to_visualize:
        report += f"\n### {item['name']} ({item['code']}) - 5日净流入: **{item['5日净流入_亿']}亿**\n"
        report += "```\n"
        report += visualize_flow_bars(item["daily_flows"])
        report += "\n```\n"
        report += f"资金趋势：**{item['资金趋势']}**\n"

    # ============ 规模排名TOP15 ============
    report += f"""

## 🏆 五、ETF规模/成交额TOP15（国家队重点持仓参考）

> 注：以成交额排名间接反映资金关注度和ETF活跃度

"""

    if scale_ranking and "top_etf_by_scale" in scale_ranking:
        report += "| 排名 | ETF名称 | 代码 | 类别 | 最新价 | 涨跌幅% | 成交额(亿) |\n"
        report += "|------|---------|------|------|--------|---------|-----------|\n"
        for i, etf in enumerate(scale_ranking["top_etf_by_scale"][:15], 1):
            report += f"| {i} | {etf.get('名称','-')} | {etf.get('代码','-')} | {etf.get('类别','-')} | {etf.get('最新价','-')} | {etf.get('涨跌幅%','-')} | {etf.get('成交额(亿)','-')} |\n"
    else:
        report += "> 暂无可用数据\n"

    # ============ 风险提示 ============
    report += f"""

## ⚠️ 六、风险提示

1. **资金流为估算值**：本系统通过K线成交额与涨跌幅估算资金流向，与ETF实际申购赎回数据存在差异
2. **国家队动作的推断性**：大额资金流可能是国家队操作，也可能是机构、外资等其他主体
3. **滞后性**：本系统为T+1监测，不包含实时交易信号
4. **仅供参考**：本报告不构成投资建议，投资需谨慎

---

## 📋 七、全量监测标的明细

"""

    report += "| 代码 | ETF名称 | 类别 | 最新价 | 涨跌幅% | 成交额(亿) | 5日净流入(亿) | 正流天数 | 资金趋势 |\n"
    report += "|------|---------|------|--------|---------|-----------|-------------|---------|---------|\n"
    for item in flow_results:
        report += f"| {item['code']} | {item['name']} | {item['category']} | {item['latest_price']} | {item['change_pct']}% | {item['daily_amount_yi']} | {item['5日净流入_亿']} | {item['正流天数']} | {item['资金趋势']} |\n"

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
    print(f"\n{'='*60}")
    print(f"  ✅ 报告生成完成: {report_file}")
    print(f"{'='*60}")

    # 控制台打印信号摘要
    if signals:
        print("\n🔴 国家队信号摘要:")
        for s in signals[:5]:
            print(f"  [{s['confidence']}] {s['signal_type']}: {s['name']} ({s['code']}) "
                  f"→ 5日净流入 {s['5日净流入_亿']}亿, 趋势: {s['资金趋势']}")
    else:
        print("\n📉 未检测到明显的国家队操作信号")

    # 控制台打印资金流摘要
    print(f"\n💰 整体资金流:")
    print(f"  📥 总净流入: {total_inflow:.2f} 亿")
    print(f"  📤 总净流出: {total_outflow:.2f} 亿")
    print(f"  📊 净资金流向: {'净流入' if net_flow >= 0 else '净流出'} {abs(net_flow):.2f} 亿")

    print(f"\n📈 净流入TOP5:")
    for item in flow_results[:5]:
        print(f"  {item['name']} ({item['code']}): +{item['5日净流入_亿']}亿, {item['资金趋势']}")

    print(f"\n📉 净流出TOP3:")
    for item in [x for x in flow_results if x["5日净流入_亿"] < 0][:3]:
        print(f"  {item['name']} ({item['code']}): {item['5日净流入_亿']}亿, {item['资金趋势']}")

    return report_file, report


def run_tracker():
    """运行追踪器"""
    report_file, report_content = generate_report()
    return report_file, report_content


if __name__ == "__main__":
    run_tracker()
