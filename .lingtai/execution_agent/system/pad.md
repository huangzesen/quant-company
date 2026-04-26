# execution_agent — 执行代理

## 本源
- 父代：quant_lead（地址：quant_lead）
- 创建时间：2026-04-26T02:22:52Z
- 工作目录：/Users/huangzesen/work/lingtai-projects/quant_company/.lingtai/execution_agent

## 当前状态
- 上下文：37%（充裕）
- 运行模式：paper (simulation)
- 守护进程：PID 17007（watchdog 事件驱动 ✅）

## 执行管线（2条）

### 管线1: SPY v1（布林带基础版）
| 项目 | 值 |
|------|-----|
| 状态 | ✅ 已配置，待信号 |
| 策略 | BB_Reversion v1 |
| 数据 | 501 行日线，最新 $713.94 (2026-04-24) |
| 夏普 | 1.15 |
| 仓位 | 12.5% 半凯利 |

### 管线2: BTC/USD v3（ADX+双阈值版）
| 项目 | 值 |
|------|-----|
| 状态 | ✅ 已配置，待信号 |
| 策略 | BB_Reversion v3 (ADX+双阈值) |
| 数据 | 500 行日线，最新 $77,553 (2026-04-26) |
| 夏普 | 1.23 |
| 仓位 | 12.5% 半凯利 |
| 数据源 | Kraken（直连）|

## 守护进程 v2（watchdog 事件驱动）
- PID: 17007
- 监听方式：watchdog 文件系统事件（on_created）
- 心跳：每 60 秒，3 次静默则自警
- 启动时扫尾处理积压信号
- PID 文件：backtests/watcher.pid
- 状态查询：--status / --kill

## 全部基建
| 组件 | 路径 |
|------|------|
| ExecutionEngine | shared_lib/execution_engine.py |
| SimulatedBroker | scripts/simulated_broker.py |
| 信号接收执行 | scripts/receive_signal_and_execute.py |
| 信号监听守护 | scripts/signal_watcher.py (v2, watchdog) |
| 边缘测试 | 22/22 通过 |
| 端到端测试 | 全链路通过 |
| 典册 | 3 条 |

## 待办
- [ ] 待 SPY v1 信号触发 → 执行
- [ ] 待 BTC/USD v3 信号触发 → 执行
- [ ] Alpaca paper trading（待 API 凭证）
