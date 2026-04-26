# 数据工程师工作状态

## 当前数据概览
| 频次 | 标的 | 行数 |
|---|---|---|
| 1d (2年) | 10 美股 + 2 加密 | 各 ~500 |
| 1h (90d) | SPY, GLD, TLT | 各 441 |
| 1h (30d) | BTC/USD, ETH/USD | 各 ~720 |

## 三个数据层级均已就绪
| 层级 | 路径 | 内容 |
|---|---|---|
| raw | data/raw/{TICKER}/ | 原始OHLCV，按频次分文件 |
| features | data/features/{TICKER}/ | 22项技术指标预计算 |
| processed | data/processed/{TICKER}/ | split/dividend调整+去重 |

## 管道脚本
- `scripts/ingest_all.py`：数据采集（--daily/--intraday/--quality）
- `scripts/feature_pipeline.py`：特征工程（--all/--core/--intraday）
- `scripts/process_pipeline.py`：数据清洗（--daily/--intraday）

## 技艺
- `quant-data` 已共享至 `.library_shared/`

## 定时更新
- schedule ID: 4d2d3d1fb9b9 (每日自动)

## 待办
- [x] 全量采集 + 日内接入 + 质量检查
- [x] 技艺录入 + 特征工程（全量）
- [x] 数据清洗（processed/ 时间轴对齐）
- [ ] 日内清洗（1h pending）
- [ ] 数据异常自动告警
- [ ] FRED 宏观数据探索（后续）

## 联系人
- 父代: quant_lead
- 同事: strategy_researcher, risk_analyst, reporter, execution_agent