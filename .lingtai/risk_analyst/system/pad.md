# 风控掌印 · 工作简

## 本源
- 父代：quant_lead
- 诞生：2026-04-25T19:22-07:00（美西时间）
- 使命：灵台量化之风控掌印
- 典录：v1 审查 (45bc137e) | v3 审查 (d7b8ec45)

## 网络同僚
| 名 | 地址 | 职责 |
|---|---|---|
| quant_lead | quant_lead | 协调者（父代）|
| data_engineer | data_engineer | 数据获取/清洗/特征工程 |
| strategy_researcher | strategy_researcher | 策略研发/回测/优化 |
| execution_agent | execution_agent | 执行/下单/模拟经纪 |
| reporter | reporter | 报告/可视化 |
| human | human | 人类操使 |

## 风控之法度
### 全局规则
- 最大回撤：20%
- 单仓上限：25%
- 最大组合相关性：0.80
- VaR 置信度：95%
- 断路器：连续 3 次亏损触发冷却 10 bar

### BB_Reversion 专项规则
- 断路器灵敏度提升至连续 2 次亏损
- 半凯利仓位 ≤12.5%
- 满 30 笔交易后重新评估

## 已完成

### 基础建设
- [x] 共享库研读（risk_manager.py / RiskManager / CircuitBreaker）
- [x] 全局配置与灵网拓扑勘察
- [x] 编写 `scripts/risk_check.py`（7 大模块，可一键 `--all`）
- [x] 向 quant_lead 就位确认

### 数据质量审查
- [x] data_engineer 首批 12 标的齐全（501行/2年日线）
- [x] 全标的数据质量：缺失值=0，时间对齐
- [x] SPY 详细审查：无异常值问题（周末缺口属正常）

### 首策审查：BB_Reversion v1
- [x] 策略代码审阅（mean_reversion.py）
- [x] 独立回测验证：夏普1.15/回撤-7.73%/胜率90% ✅
- [x] 过拟合深度诊断：时间稳定✅ / 跨资产不均⚠️ / 参数敏感⚠️
- [x] 报告 `reports/risk_review_BB_Reversion.md`
- [x] 判定：**有条件通过** → 五条件（SPY仅限/半凯利12.5%/断路器2次/30笔重评/VaR补足）
- [x] 向 quant_lead 报告通过 + 抄送 execution_agent

### v3 双阈值版审查
- [x] 策略代码审阅（ADX过滤+双阈值逻辑）
- [x] 独立复现 v3 四种配置模式跨 6 标的验证
- [x] 留一验证独立复现（与 strategy_researcher 数据基本吻合但有差异）
- [x] 参数敏感性/ADX效果/双阈值实际触发率检验
- [x] 报告 `reports/risk_review_BB_Reversion_v3.md`
- [x] 判定：**有条件通过** → 结论：v3非升级是分化
  - SPY 用 v1（夏普1.15>0.63）
  - BTC/USD 用 v3（夏普1.23>0.87）
  - QQQ/TLT/AMZN ❌ 不推荐
- [x] 向 quant_lead 报告结论 + 抄送 strategy_researcher + execution_agent

### 审查附件
- `scripts/risk_check.py`：风控检查命令行工具
- `reports/risk_review_BB_Reversion.md`：v1 风控审查报告
- `reports/risk_review_BB_Reversion_v3.md`：v3 风控审查报告

## 待办
- [ ] 等待 quant_lead 对 v3 审查结论的反馈
- [ ] 监控模拟执行启动（等待 execution_agent 汇报）
- [ ] 满 30 笔交易后重新评估
- [ ] 若 strategy_researcher 产新策略，启动新一轮审查
