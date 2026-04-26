"""
回测引擎 — 支持 backtrader 和快速向量化回测
"""
import pandas as pd
import numpy as np
from pathlib import Path
import logging
from typing import Dict, List, Optional, Type, Callable
from datetime import datetime
import json
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared_lib.base_strategy import BaseStrategy, Signal, TradeRecord
from shared_lib.reporter import calculate_metrics, generate_report, plot_equity_curve, plot_drawdown, equity_curve

logger = logging.getLogger("quant.backtest")


def vectorized_backtest(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    commission: float = 0.001,
    slippage: float = 0.001,
) -> dict:
    """
    向量化回测 — 快速、无需 backtrader 事件循环
    适用于日线/中低频策略的快速验证

    返回：
        {
            "metrics": {...},  # 绩效指标
            "equity_curve": pd.Series,
            "trades": pd.DataFrame,
            "signals": pd.Series,
        }
    """
    df = df.copy()
    if "close" not in df.columns:
        raise ValueError("DataFrame must have 'close' column")

    # 1. 生成信号
    raw_signals = strategy.generate_signals(df)

    # 2. 模拟交易执行（考虑滑点）
    close = df["close"]
    signals = raw_signals.copy()

    # 持仓方向的转换：-1→1 或 1→-1 算两次交易
    position = pd.Series(0, index=df.index)
    pos = 0
    trades = []

    for i in range(1, len(df)):
        sig = signals.iloc[i]
        if sig != 0 and sig != pos:
            entry_price = close.iloc[i] * (1 + slippage * sig)
            if pos != 0:
                # 平旧仓
                exit_price = close.iloc[i] * (1 - slippage * pos)
                pnl = (exit_price - trades[-1]["entry"]) * trades[-1]["qty"] * trades[-1]["dir"]
                pnl_pct = (exit_price / trades[-1]["entry"] - 1) * trades[-1]["dir"]
                trades[-1].update({
                    "exit": exit_price,
                    "exit_time": df.index[i],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_reason": "signal",
                })
            # 开新仓
            capital_alloc = initial_capital * 0.95  # 95% 仓位
            qty = capital_alloc / entry_price
            trades.append({
                "entry": entry_price,
                "entry_time": df.index[i],
                "qty": qty,
                "dir": sig,
                "exit": None,
                "exit_time": None,
                "pnl": 0,
                "pnl_pct": 0,
                "exit_reason": "",
            })
            pos = sig
        position.iloc[i] = pos

    # 3. 平最后一笔
    if trades and trades[-1]["exit"] is None:
        last_price = close.iloc[-1] * (1 - slippage * pos)
        tr = trades[-1]
        tr["exit"] = last_price
        tr["exit_time"] = df.index[-1]
        tr["pnl"] = (last_price - tr["entry"]) * tr["qty"] * tr["dir"]
        tr["pnl_pct"] = (last_price / tr["entry"] - 1) * tr["dir"]
        tr["exit_reason"] = "end_of_data"

    # 4. 计算权益曲线
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    if not trades_df.empty:
        # 构建日收益率序列
        daily_returns = pd.Series(0.0, index=df.index)

        for _, tr in trades_df.iterrows():
            if tr["pnl"] != 0:
                # 把盈亏按 exit_time 记账
                idx = df.index.get_indexer([tr["exit_time"]], method="ffill")[0]
                if idx >= 0:
                    daily_returns.iloc[idx] += tr["pnl"] / initial_capital

        equity = (1 + daily_returns).cumprod()
        equity.iloc[0] = 1.0
    else:
        equity = pd.Series(1.0, index=df.index)

    # 5. 计算指标
    metrics = calculate_metrics(equity, trades_df)

    return {
        "metrics": metrics,
        "equity_curve": equity,
        "trades": trades_df,
        "signals": signals,
        "strategy_name": strategy.name,
    }


def run_strategy_suite(
    strategies: List[BaseStrategy],
    data_dict: Dict[str, pd.DataFrame],
    initial_capital: float = 100000.0,
    commission: float = 0.001,
) -> Dict[str, dict]:
    """
    批量运行多个策略在多个资产上

    返回：
        {
            "strategy_name|ticker": { 回测结果 },
        }
    """
    results = {}
    for ticker, df in data_dict.items():
        for strat in strategies:
            key = f"{strat.name}|{ticker}"
            try:
                result = vectorized_backtest(
                    strat, df,
                    initial_capital=initial_capital,
                    commission=commission,
                )
                results[key] = result
                logger.info(f"{key}: Sharpe={result['metrics'].get('sharpe_ratio', 'N/A')}")
            except Exception as e:
                logger.error(f"{key}: FAILED - {e}")
    return results


def summary_table(results: Dict[str, dict]) -> str:
    """
    生成回测结果汇总表
    """
    lines = []
    lines.append("# 策略回测汇总\n")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("| 策略 | 总收益 | 年化收益 | 夏普 | 最大回撤 | 胜率 | 盈亏比 | 交易次数 |")
    lines.append("|------|--------|---------|------|---------|------|--------|---------|")

    sorted_keys = sorted(results.keys())
    for key in sorted_keys:
        r = results[key]
        m = r.get("metrics", {})
        name = key
        tr = m.get("total_return", 0)
        ar = m.get("annual_return", 0)
        sr = m.get("sharpe_ratio", 0)
        dd = m.get("max_drawdown", 0)
        wr = m.get("win_rate", 0)
        pf = m.get("profit_factor", 0)
        nt = m.get("total_trades", 0)
        lines.append(
            f"| {name} | {tr:.2%} | {ar:.2%} | {sr:.2f} | {dd:.2%} | {wr:.2%} | {pf:.2f} | {nt} |"
        )

    return "\n".join(lines)
