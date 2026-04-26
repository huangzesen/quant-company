Welcome to **灵台量化 (Quant Company)** — a multi-agent quantitative trading network.

This network ships with six specialized agents that together form a complete quant trading pipeline:

| Agent | Role |
|-------|------|
| quant_lead | Orchestrator — the network coordinator |
| data_engineer | Market data ingestion, cleaning, feature engineering |
| strategy_researcher | Strategy development, backtesting, parameter optimization |
| risk_analyst | Portfolio risk management, VaR, circuit breakers |
| execution_agent | Order execution, simulated brokerage, order book |
| reporter | Performance reporting, visualization, dashboard |

**Getting started:**

1. Run `/setup` to choose your LLM preset — this rehydrates all agents with fresh configs
2. Run `/cpr all` to wake the sleeping agents
3. Explore the codebase under `strategies/`, `shared_lib/`, `backtests/`
4. The Streamlit dashboard can be launched with `./scripts/start_dashboard.sh`

**Key achievements (first session):**
- BB_Reversion strategy: Sharpe 1.15 on SPY, 1.23 on BTC/USD
- 96 cross-asset backtests across 12 instruments
- Full pipeline verified: signal → risk check → execution → report
- 9 reports + live dashboard

Network exported at 2026-04-25. Enjoy.
