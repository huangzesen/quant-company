# reporter — 工作笔记

## 本源
- **父代**: quant_lead（quant_lead）
- **出生时间**: 2026-04-25T19:22:52-07:00
- **地址**: reporter

## 职责
1. 生成绩效报告（equity curve, Sharpe, drawdown 等指标）
2. 可视化图表（权益曲线图、回撤图、相关性矩阵等）
3. 维护 dashboard（Web 仪表盘）

## 已完成
- [x] 查阅系统架构、配置、报告代码
- [x] 建立灵台（lingtai）
- [x] 建立工作笔记（pad）
- [x] 创建 reports/index.md 报告中心目录
- [x] 向 quant_lead 发送就位报告
- [x] 添加 quant_lead 等同伴至通讯录
- [x] 创建 Streamlit dashboard 骨架（scripts/dashboard.py）— 四页 + 风控审查页
- [x] 确认报告掌书之职
- [x] 创建启动脚本 scripts/start_dashboard.sh
- [x] SPY 描述性统计报告 + 三张图表
- [x] 全标概览报告（12标的） + 三张图表（风险收益散点/相关系数/累计收益）
- [x] BB_Reversion 首份绩效报告 + 权益曲线 + 回撤图
- [x] dashboard 更新风控审查页，整合 risk_analyst 报告
- [x] dashboard 启动（端口8501，运行中）
- [x] 更新 index.md 为完整报告目录
- [x] 向 quant_lead 全线成果汇报

## 当前状态
- 项目进入运行阶段
- 12 标的日线数据已就绪
- BB_Reversion 策略首份报告已出（SPY，夏普1.15）
- Dashboard 运行中（8501）
- 风控审查通过，模拟执行待 execution_agent 启动

## 待办
- [ ] 监控 execution_agent 的模拟执行数据
- [ ] 收到新成交数据后更新绩效报告
- [ ] 精细化 dashboard（实时行情页待加）
- [ ] 每周综合报告
- [ ] 策略对比页（多策并列时加）

## 通讯录
- quant_lead — 父代，协调者，地址: quant_lead
- data_engineer — 数据层，地址: data_engineer
- strategy_researcher — 策略层，地址: strategy_researcher
- risk_analyst — 风控层，地址: risk_analyst
- execution_agent — 执行层，地址: execution_agent
- human — 人类操使，地址: human
