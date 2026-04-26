---
name: quant-data
description: 灵台量化数据管道——股票/加密币行情采集、清洗、存储与质量检查。含 Yahoo Finance + Kraken (CCXT) 双数据源，支持日线/1h 自动增量更新。
version: 1.0.0
agent: data_engineer
created: 2026-04-25
---

# Quant Data Pipeline — 灵台量化数据管道

## 概述

股票（Yahoo Finance）与加密货币（Kraken/CCXT）行情数据的采集、清洗、存储工具集。

### 数据源

| 源 | 类型 | 标的 | 限制 |
|---|---|---|---|
| Yahoo Finance | 美股日线/1h | SPY, QQQ, IWM, GLD, TLT, AAPL, MSFT, GOOGL, AMZN, NVDA | 日内深度 ~90 天 |
| Kraken (CCXT) | 加密币日线/1h | BTC/USD, ETH/USD | 1h 回溯上限 ~720 条 |
| Binance | ❌ 不可用 | — | 美国地区 HTTP 451 |

### 存储结构

```
data/raw/{TICKER}/     ← Parquet 文件，按标的分目录
data/processed/        ← 清洗后数据（待建）
data/features/         ← 特征工程输出（待建）
```

文件命名：`{TICKER}_{freq}_{开始日期}_{结束日期}.parquet`

---

## 快速开始

### 查看数据状态

```bash
cd /Users/huangzesen/work/lingtai-projects/quant_company
python3 scripts/ingest_all.py --status
```

### 批量采集

```bash
# 全量日线 + 日内
python3 scripts/ingest_all.py --all

# 仅日线增量更新
python3 scripts/ingest_all.py --daily

# 仅日内 1h
python3 scripts/ingest_all.py --intraday

# 指定标的
python3 scripts/ingest_all.py --daily --tickers SPY QQQ AAPL
```

### 数据质量检查

```bash
python3 scripts/ingest_all.py --quality
python3 scripts/ingest_all.py --quality daily
python3 scripts/ingest_all.py --quality intraday
```

---

## API 参考

### `shared_lib/data_fetcher.py` — 数据获取层

```python
from shared_lib.data_fetcher import fetch_yahoo, fetch_ccxt, load_local, list_local_data

# 采集 Yahoo 数据
df = fetch_yahoo('SPY', interval='1d', start=..., end=...)

# 采集 Kraken 数据
df = fetch_ccxt('BTC/USD', exchange='kraken', timeframe='1d', limit=500)

# 加载本地数据（自动合并去重排序）
df = load_local('SPY')

# 列出本地文件
files = list_local_data('SPY')
```

### `shared_lib/features.py` — 技术指标

```python
from shared_lib.features import add_all_indicators
df = add_all_indicators(df)  # 返回含 SMA/MACD/RSI/布林带/ATR/OBV 的 DataFrame
```

---

## 数据质量说明

### 美股日线
- 日期范围：2024-04 ~ 2026-04（~2 年）
- 各标的各 501 行，无缺失值
- 跳空均为美股法定假日，非数据问题

### 加密币日线/1h
- 日期范围：2024-12 起（日线） / 最近 30 天（1h）
- 7×24 连续交易，无跳空
- Kraken 公开 API 1h 回溯上限约 720 条

---

## 管道维护

### 增量更新策略
`ingest_all.py --daily` 会：
1. 检查已有数据
2. 只补拉缺失区间
3. 合并去重后保存

### 定时更新建议
设置每日收盘后运行：
```bash
# 每天 16:30 ET 运行（美股收盘后半小时）
30 20 * * 1-5 cd /path/to/quant_company && python3 scripts/ingest_all.py --daily
```

---

## 已知限制
1. **Binance**: 美国地区不可用（HTTP 451）
2. **Kraken 1h 回溯**: 公开 API 仅返回最近 ~720 条
3. **Yahoo 日内**: 约 90 天回溯限制
4. **依赖环境**: 需 `/opt/anaconda3/bin/python3`
