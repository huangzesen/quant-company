# 灵台量化 · 报告中心

> 最后更新: 2026-04-25T19:30 PDT
> 报告作者: reporter

---

## 报告目录

| 类别 | 文件 | 说明 |
|------|------|------|
| **策略绩效** | `BB_Reversion_performance.md` | 首策 BB_Reversion 绩效报告 |
| 风险审查 | `risk_review_BB_Reversion.md` | BB_Reversion 风控审查（有条件通过 ✅） |
| 数据概览 | `spy_descriptive_stats.md` | SPY 描述性统计（价格/收益/波动率） |
| 全标概览 | `all_assets_overview.md` | 12 标的对比（收益风险/相关系数） |

## 图表集

| 文件 | 说明 |
|------|------|
| `equity_BB_Reversion.png` | BB_Reversion 权益曲线 |
| `dd_BB_Reversion.png` | BB_Reversion 回撤分析 |
| `spy_price_overview.png` | SPY 价格/收益率/ATR 走势 |
| `spy_return_distribution.png` | SPY 日收益率分布 + Q-Q 图 |
| `spy_volatility.png` | SPY 滚动 30 日年化波动率 |
| `all_assets_risk_return.png` | 12 标的风险收益散点图 |
| `all_assets_correlation.png` | 12 标的相关性矩阵热力图 |
| `all_assets_cumulative_returns.png` | 12 标的累计收益对比 |

## 系统状态

- **数据层**: ✅ 12 标的日线数据已就绪
- **策略层**: ✅ BB_Reversion 上线
- **风控层**: ✅ 有条件通过（半凯利 ≤12.5%）
- **执行层**: ⏳ 待 execution_agent 启动模拟执行
- **报告层**: ✅ 全线就绪

## Dashboard

启动命令: `streamlit run scripts/dashboard.py` 或 `./scripts/start_dashboard.sh`
