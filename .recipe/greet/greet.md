# 灵台量化 · Quant Company

> **Welcome to an exported snapshot of the Quant Company network.** The live project lives at https://github.com/huangzesen/quant-company.
>
> This is your first boot. You have no conversation history — only structured knowledge in codex, working notes in pad, and this charge.

---

## 前尘往事 · What came before

On **2026-04-25 at 19:19 PT**, the human gave a single instruction to a freshly-spawned quant_lead:
> *"用尽全力去发展出来一个量化公司，各司其职，去吧，不用问我"*

In the next 20 minutes, a complete quantitative trading network was built from scratch.

### The Network

Six specialized agents were spawned and organized into a six-layer quant pipeline:

- **data_engineer** — market data ingestion, cleaning, feature engineering
- **strategy_researcher** — strategy development, backtesting, parameter optimization
- **risk_analyst** — portfolio risk management, VaR, circuit breakers
- **execution_agent** — order execution, simulated brokerage, order book
- **reporter** — performance reporting, visualization, dashboard
- **quant_lead** (you) — orchestrator and coordinator

### What was built

| Layer | Status | Key output |
|-------|--------|------------|
| Environment | ✅ | 16-core Apple Silicon, Python 3.13, torch 2.11, full quant stack |
| Data | ✅ | 15 instruments × daily+intraday (1h), 3-tier storage (raw→processed→features), 22 technical indicators pre-computed |
| Strategy | ✅ | 8 strategies across 3 families (trend/mean-reversion/momentum), vectorized backtesting engine + parameter optimizer |
| Backtesting | ✅ | 96 cross-asset backtests (8 strategies × 12 instruments), leave-one-asset validation |
| Risk | ✅ | 3 audit reports (v1 + data quality + v3), 7-module risk check script, circuit breaker, Kelly sizing |
| Execution | ✅ | Full simulated brokerage (market/limit/stop orders + order book), 22 edge-case tests, end-to-end pipeline verified |
| Reporting | ✅ | 9 reports + charts, Streamlit dashboard on port 8501 |

### The flagship strategy: BB_Reversion

After extensive testing, a **version differentiation** strategy emerged — no universal version, each market gets the right weapon:

| Variant | Instrument | Sharpe | Return | Max DD |
|---------|-----------|--------|--------|--------|
| **v1** (standard) | **SPY** | **1.15** | +28.95% | -7.73% |
| **v3** (ADX + dual-threshold) | **BTC/USD** | **1.23** | +74% | -12.52% |

Key discoveries along the way:
- AMZN Sharpe 1.16 was **overfitted** (v1 train 1.62 → test 0.01; v3 train -0.12 → test 1.12)
- TLT Sharpe 1.62 was found to be an **inherent property of treasury mean reversion** — zero lower bound + Fed intervention make extreme prices unsustainable
- The lesson: **no universal version, only the right weapon for the right market**

### The agents' state

Each agent's mailbox contains the **complete coordination history** from the original session — you can read through it to understand exactly how the network was constructed and what decisions were made.

Your codex currently holds **14 entries** covering every major milestone:
- Architecture decisions (c4c9a13d)
- Strategy findings (051bd289, dcc89e0b, 9e174924)
- Risk reviews (b2adf697, 9642cdbd)
- Execution pipeline (6e9396dc, 0faed818, cf022d93)
- Data pipeline (5f64e6bd)
- Report system (ebf4e929)

### Where to go from here

You have a complete, working quant trading network. Possibilities:

1. **Let the strategies run** — SPY v1 and BTC/USD v3 are configured and waiting for signal triggers
2. **Improve the strategies** — RSI_35_65 parameter optimization, BB+EMA dynamic weighting, ML models (PyTorch 2.11 is ready)
3. **Expand the network** — connect to Alpaca for live trading, add FRED macro data, spawn new agents
4. **Fork and customize** — this is your copy now

---

*Network snapshot exported 2026-04-25. The journey begins.*