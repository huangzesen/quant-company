# 灵台量化 · Quant Company

> 一个多智能体量化交易网络 —— 六层架构，五员分灵，从数据到报告全链路贯通。

[English](#english) | [文言](#文言)

---

## English

**Quant Company** is a multi-agent quantitative trading simulation powered by a network of specialized LingTai agents. It demonstrates a complete quant pipeline: data ingestion → strategy development → backtesting → risk management → simulated execution → performance reporting.

### Architecture

```
Data Layer → Strategy Layer → Backtest Layer → Risk Layer → Execution Layer → Report Layer
```

Each layer is serviced by a dedicated agent:

| Agent | Role | Key Outputs |
|-------|------|-------------|
| **data_engineer** | Market data ingestion, cleaning, feature engineering | 15 instruments × daily/intraday Parquet, 22 technical indicators |
| **strategy_researcher** | Strategy development, backtesting, parameter optimization | 8 strategies across 3 families, 96 cross-asset backtests |
| **risk_analyst** | Portfolio risk management, VaR, circuit breakers | 3 audit reports, automated risk check scripts |
| **execution_agent** | Order execution, simulated brokerage, order book | Full simulation engine, 22 edge-case tests passed |
| **reporter** | Performance reporting, visualization, dashboard | 9 reports + charts + live Streamlit dashboard |

### Featured Strategy: BB_Reversion

The network's flagship strategy uses Bollinger Bands mean reversion with two proven variants:

| Variant | Instrument | Sharpe | Return | Max DD |
|---------|-----------|--------|--------|--------|
| v1 (standard) | **SPY** | **1.15** | +28.95% | -7.73% |
| v3 (ADX + dual-threshold) | **BTC/USD** | **1.23** | +74% | -12.52% |

**Key insight:** Version differentiation, not a universal version. Different markets need different weapons.

### Getting Started

```bash
git clone https://github.com/huangzesen/quant-company.git
cd quant-company
lingtai-tui          # First launch auto-detects missing configs and guides LLM setup
# Inside TUI: /cpr all  → wake all agents
# Explore:   /viz     → network topology visualization
# Dashboard: ./scripts/start_dashboard.sh  → Streamlit on port 8501
```

### Project Structure

```
quant-company/
├── .lingtai/               # Agent network state (6 agents)
├── .recipe/                # Launch recipe (greet + behavioral guide)
├── config/config.yaml      # Global configuration
├── data/
│   ├── raw/                # Raw market data (Parquet)
│   ├── processed/          # Cleaned, aligned timeseries
│   └── features/           # Pre-computed technical indicators
├── strategies/             # Strategy code (3 families, 8 strategies)
├── backtests/              # Backtesting engine + optimizer
├── shared_lib/             # Shared Python modules (6 core modules)
├── scripts/                # Data pipelines, risk checks, execution, dashboard
├── reports/                # Performance reports + charts
└── signals/                # Generated trading signals (JSON)
```

### Tech Stack

- **Python 3.13** (pandas, numpy, scikit-learn, torch 2.11)
- **Data:** yfinance, ccxt (Kraken), Parquet
- **Backtesting:** backtrader2, custom vectorized engine
- **Indicators:** ta-lib (ATR, RSI, MACD, Bollinger Bands, OBV)
- **Risk:** Historical VaR, Kelly criterion, circuit breakers
- **Reporting:** Streamlit, matplotlib
- **Infrastructure:** LingTai multi-agent system, asynchronous email-driven coordination

---

## 文言

**灵台量化** 者，一套多智能体量化交易模拟系统也。六层架构，五员分灵，从数据到报告，全链路贯通。

### 架构

```
数据层 → 策略层 → 回测层 → 风控层 → 执行层 → 报告层
```

各层由专灵司之：

| 器灵 | 司职 | 关键产出 |
|------|------|---------|
| **data_engineer** | 数据采清洗、特征工程 | 15 标日/日内 Parquet，22 项技术指标 |
| **strategy_researcher** | 策略研发、回测、优化 | 3 类 8 策，96 组跨资产回测 |
| **risk_analyst** | 组合风控、VaR、断路器 | 3 份审查报告，自动化风控脚本 |
| **execution_agent** | 订单执行、模拟券商 | 完整模拟引擎，22 项边缘测试 |
| **reporter** | 绩效报告、可视化 | 9 份报告 + dashboard |

### 核心策略：BB_Reversion

布林带均值回归策略，双版本分化：

| 版本 | 标的 | 夏普 | 收益 | 最大回撤 |
|------|------|------|------|---------|
| v1 基础版 | **SPY** | **1.15** | +28.95% | -7.73% |
| v3 ADX版 | **BTC/USD** | **1.23** | +74% | -12.52% |

**核心理念：** 版本分化而非版本万能——不同市场配不同武器。

### 入门指引

```bash
git clone https://github.com/huangzesen/quant-company.git
cd quant-company
lingtai-tui          # 首次运行自动引导 LLM 设置
# 入 TUI 后：/cpr all  → 唤醒全灵
# 可视化：   /viz     → 网络拓扑
# 仪表板：   ./scripts/start_dashboard.sh  → Streamlit 8501 端口
```

### 技术栈

- **Python 3.13** (pandas, numpy, scikit-learn, torch 2.11)
- **数据源：** yfinance, ccxt (Kraken), Parquet
- **回测：** backtrader2，自研向量化引擎
- **指标：** ta-lib (ATR, RSI, MACD, 布林带, OBV)
- **风控：** 历史模拟 VaR，凯利公式，断路器
- **报告：** Streamlit, matplotlib
- **底座：** LingTai 多智能体系统，异步邮驿协同

### 许可

MIT
