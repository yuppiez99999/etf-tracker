# ETF 国家队资金监测系统

追踪中央汇金等国家队 ETF 持仓变化，实时监测资金流向信号

**数据来源**: Wind MCP (优先，自动探测) / akshare (备选) / 模拟数据 (兜底演示)

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- 推荐使用虚拟环境

### 2. 安装依赖

```bash
pip install akshare pandas
```

或通过 pyproject.toml：

```bash
pip install -e .
```

### 3. 运行程序

```bash
# 默认运行（自动数据源降级 + 5日窗口 + 归档）
python etf_tracker.py

# 指定数据源与窗口
python etf_tracker.py --source akshare --days 10

# 演示模式（不访问网络，用于自检）
python etf_tracker.py --source mock --no-archive
```

### 4. 查看报告

报告自动生成在 `reports/` 目录下：
- `latest.md` - 最新报告
- `report_YYYYMMDD.md` - 按日归档报告

默认归档至 `reports/archive/YYYY-MM-DD/`，可通过 `--archive-dir` 或环境变量 `ETF_TRACKER_ARCHIVE_DIR` 重定向。

---

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--days` | 5 | 资金流监测窗口天数 |
| `--source` | auto | 数据源模式：`auto`（按优先级降级）/ `wind` / `akshare` / `mock`（强制演示） |
| `--top` | 15 | 报告展示的排名条数 |
| `--no-archive` | 关闭 | 不归档到每日报告目录 |
| `--archive-dir` | 环境变量 > `reports/archive` | 归档根目录 |

---

## 功能说明

| 功能 | 说明 |
|------|------|
| 实时行情 | 监控列表中ETF的最新价格和涨跌幅 |
| 资金流向 | 分析最近N天净流入/流出情况（涨跌幅方向 × 成交额估算） |
| 信号监测 | 当净流入超过10亿时标记为潜在国家队信号 |
| 规模排名 | 展示ETF成交额排名（国家队偏好大盘ETF）|

---

## 监测的ETF列表

24 只主流标的，覆盖宽基核心 / 蓝筹核心 / 成长科技 / 小盘风格 / 防御红利 / 金融 / 医药 / 科技 / 新能源 / 避险资产（详见 `etf_tracker.py` CONFIG 区）。

核心标的：

| 代码 | 名称 | 市场 |
|------|------|------|
| 510300 | 沪深300ETF华泰柏瑞 | SH |
| 510500 | 中证500ETF南方 | SH |
| 510050 | 上证50ETF华夏 | SH |
| 159915 | 创业板ETF易方达 | SZ |
| 588000 | 科创50ETF华夏 | SH |

---

## 国家队信号阈值

| 信号类型 | 阈值 | 置信度 |
|----------|------|--------|
| 加仓信号 | 窗口净流入 > 10亿 | 中 |
| 加仓信号 | 窗口净流入 > 50亿 且趋势连续 | 高 |
| 减仓信号 | 窗口净流出 > 10亿 / 50亿 | 中 / 高 |
| 关注信号 | 窗口净流入(出) > 2亿 | 低 |

---

## 配置修改

编辑 `etf_tracker.py` 中的 `CONFIG` 区域：

```python
CONFIG = {
    "etf_list": [
        {"code": "510300", "name": "沪深300ETF", "market": "sh", "category": "宽基核心"},
        # 添加更多ETF...
    ],
    "state_keywords": ["中央汇金", "证金", "社保", "国家队"],
}
```

可修改内容：
- 添加/删除要追踪的ETF
- 修改信号阈值（默认10亿）
- 监测窗口天数通过 CLI `--days` 调整

---

## 数据源优先级

1. **Wind MCP** - 优先数据源，HTTP 直连 `mcp.wind.com.cn`（需 `WIND_API_KEY` 环境变量或 `~/.wind-aifinmarket/config`，前复权 qfq）
2. **akshare** - 备选数据源（新浪 ETF 历史行情，涨跌幅由相邻收盘价计算）
3. **模拟数据** - 兜底方案，所有数据源不可用时保证报告仍可生成（标记"模拟数据"来源）

---

## 开发

```bash
# lint + format
pip install ruff
ruff check etf_tracker.py
ruff format etf_tracker.py
```

ruff 规则配置见 `pyproject.toml`（BLE001/DTZ005/PLW1510 为该工具的设计选择豁免）。

---

## 报告示例

```
# 📊 ETF 国家队资金监测报告
生成时间：2026-06-06 09:21:02
数据来源：Wind MCP

## 一、今日行情速览（按成交额排序）

| ETF名称 | 代码 | 最新价 | 涨跌幅 |
|---------|------|--------|--------|
| 沪深300ETF华泰柏瑞 | 510300 | 4.843 | -1.68% |
| 中证500ETF南方 | 510500 | 8.339 | -1.29% |

## 二、国家队信号检测

> 检测到 4 条潜在信号：
> - **加仓信号**：科创50ETF（588000），净流入 171.86亿，置信度：高
```

仅作为学习使用 不作为投资意见 望周知

---

*本报告由 ETF 国家队监测系统自动生成*
*数据来源于万得 Wind 金融数据服务 / akshare*
*数据仅供参考，不构成投资建议*
