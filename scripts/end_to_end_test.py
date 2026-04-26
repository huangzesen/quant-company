"""
端到端交易流程测试
========================
模拟"策略信号 → 风控 → 执行 → 报告"全链路。

测试流程:
1. 生成模拟信号（模拟 strategy_researcher 输出）
2. 通过风控检查（模拟 risk_analyst 审批）
3. 执行引擎下单 + 模拟成交
4. 生成成交报告

用法:
    python scripts/end_to_end_test.py
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared_lib.execution_engine import ExecutionEngine
from shared_lib.risk_manager import RiskManager, RiskConfig, CircuitBreaker
from shared_lib.reporter import calculate_metrics, generate_report
from scripts.simulated_broker import SimulatedBroker

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e_test")


# ─── 信号模拟 ─────────────────────────────────────────

def simulate_signal(ticker: str, side: str, qty: float, confidence: float = 0.7,
                    strategy_name: str = "BB_Reversion") -> dict:
    """模拟从 strategy_researcher 收到的信号"""
    return {
        "strategy": strategy_name,
        "ticker": ticker,
        "side": side,            # "buy" | "sell"
        "quantity": qty,
        "confidence": confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": f"{strategy_name} signal generated",
    }


def simulate_signals_from_strategy(price_series: np.ndarray, ticker: str = "TEST") -> list:
    """
    用双均线策略模拟生成一系列信号
    返回信号列表 [{ticker, side, qty, confidence, reason}, ...]
    """
    signals = []
    short_window = 10
    long_window = 30
    position = 0
    prices = price_series.tolist()

    for i in range(long_window, len(prices)):
        short_ma = np.mean(prices[i-short_window:i])
        long_ma = np.mean(prices[i-long_window:i])

        # 金叉买入 — 按 25% 仓位上限，$100K * 0.25 / $500 ≈ 50 股
        qty = 50
        if short_ma > long_ma and position <= 0:
            # 置信度 = 均线偏离百分比 * 放大系数，确保 0.3~0.9 之间有值
            confidence = min(max(abs(short_ma / long_ma - 1) * 100, 0.3), 0.95)
            signals.append({
                "strategy": "MA_Crossover",
                "ticker": ticker,
                "side": "buy",
                "quantity": qty,
                "confidence": confidence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": f"Golden cross: short_ma={short_ma:.2f} > long_ma={long_ma:.2f}",
            })
            position = qty

        # 死叉卖出
        elif short_ma < long_ma and position >= qty:
            confidence = min(max(abs(short_ma / long_ma - 1) * 100, 0.3), 0.95)
            signals.append({
                "strategy": "MA_Crossover",
                "ticker": ticker,
                "side": "sell",
                "quantity": position,
                "confidence": confidence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": f"Death cross: short_ma={short_ma:.2f} < long_ma={long_ma:.2f}",
            })
            position = 0

    return signals


# ─── 风控检查 ─────────────────────────────────────────

def risk_check(signal: dict, engine: ExecutionEngine, rm: RiskManager,
               cb: CircuitBreaker) -> tuple[bool, str]:
    """
    多步风控检查

    Returns:
        (passed: bool, reason: str)
    """
    ticker = signal["ticker"]
    side = signal["side"]
    qty = signal["quantity"]
    pf = engine.get_portfolio()
    equity = pf["equity"]

    # 1. 断路器检查
    if cb.tripped:
        return False, "Circuit breaker tripped, cooling down"

    # 2. 仓位规模检查
    proposed_cost = qty * engine._last_prices.get(ticker, 0)
    max_pos = equity * 0.25
    if proposed_cost > max_pos:
        return False, f"Position ${proposed_cost:.0f} exceeds max ${max_pos:.0f}"

    # 3. 相同方向已持仓检查
    pos = engine.get_position(ticker)
    if side == "buy" and pos["side"] == "long" and pos["quantity"] > 0:
        new_total = pos["quantity"] + qty
        new_cost = new_total * engine._last_prices.get(ticker, 0)
        if new_cost > max_pos:
            return False, f"Combined position ${new_cost:.0f} exceeds max ${max_pos:.0f}"

    # 4. 现金检查
    if side == "buy":
        cost = qty * engine._last_prices.get(ticker, 0) * (1 + 0.001)  # 含佣金
        if cost > engine.cash:
            return False, f"Cost ${cost:.0f} exceeds cash ${engine.cash:.0f}"

    # 5. 置信度过滤
    if signal["confidence"] < 0.3:
        return False, f"Confidence {signal['confidence']:.2f} too low"

    return True, "All checks passed"


# ─── 主测试流程 ───────────────────────────────────────

def run_e2e_test():
    """运行端到端全链路测试"""
    print("\n" + "=" * 60)
    print("  端到端交易流程测试")
    print("  Signal → Risk Check → Execution → Report")
    print("=" * 60)

    # 生成模拟行情数据
    np.random.seed(42)
    n_bars = 200
    prices = 500 * np.exp(np.cumsum(np.random.randn(n_bars) * 0.008))

    # 初始化所有组件
    engine = ExecutionEngine(initial_capital=100000)
    rm = RiskManager(RiskConfig())
    cb = CircuitBreaker(max_consecutive_losses=3, cooldown_bars=5)
    broker = SimulatedBroker(initial_capital=100000)
    broker.connect()

    signals = simulate_signals_from_strategy(prices)
    print(f"\n  策略生成信号: {len(signals)} 个")
    print(f"  初始资金: $100,000")
    print(f"  行情范围: ${prices[0]:.2f} ~ ${prices.max():.2f} ~ ${prices[-1]:.2f}")

    results = []
    signal_idx = 0

    for bar_idx in range(n_bars):
        price = prices[bar_idx]

        # 喂行情给引擎和券商
        engine.tick("TEST", price)
        broker.tick("TEST", price)

        # 检查是否有信号需要发送
        while signal_idx < len(signals) and bar_idx >= 30 + signal_idx * 5:
            sig = signals[signal_idx]
            sig["ticker"] = "TEST"

            # 更新信号中的行情价格
            print(f"\n  ── 信号 #{signal_idx+1}: {sig['side']} 100 TEST @ ${price:.2f}")
            print(f"     理由: {sig['reason']}")
            print(f"     置信度: {sig['confidence']:.2f}")

            # 风控检查
            passed, reason = risk_check(sig, engine, rm, cb)
            if not passed:
                print(f"     ❌ 风控拒绝: {reason}")
                signal_idx += 1
                continue

            print(f"     ✅ 风控通过")

            # 执行下单
            oid = engine.submit_market_order("TEST", sig["side"], sig["quantity"],
                                              metadata={"strategy": sig["strategy"],
                                                        "signal_id": signal_idx})
            print(f"     📋 订单: {oid}")

            # Broker 也下单
            broker.place_order("TEST", sig["side"], sig["quantity"], "market")

            signal_idx += 1

    # 最终平仓
    if engine.get_position("TEST")["quantity"] > 0:
        print(f"\n  ── 最终平仓 ---")
        engine.tick("TEST", prices[-1])
        oid_close = engine.submit_market_order("TEST", "sell",
                                                engine.get_position("TEST")["quantity"])
        print(f"     📋 平仓: {oid_close}")

    # ── 结果分析 ──
    print("\n" + "=" * 60)
    print("  测试结果")
    print("=" * 60)

    pf = engine.get_portfolio()
    trades_df = engine.get_trade_history()

    print(f"\n  交易统计:")
    print(f"  总成交: {pf['total_trades']} 笔")
    if not trades_df.empty:
        total_pnl = trades_df["pnl_net"].sum()
        win_rate = (trades_df["pnl_net"] > 0).mean()
        print(f"  累计盈亏: ${total_pnl:,.2f}")
        print(f"  胜率: {win_rate:.1%}")
        print(f"  最大单笔盈利: ${trades_df['pnl_net'].max():,.2f}")
        print(f"  最大单笔亏损: ${trades_df['pnl_net'].min():,.2f}")

    print(f"\n  组合概况:")
    print(f"  期初权益: $100,000.00")
    print(f"  期末权益: ${pf['equity']:,.2f}")
    print(f"  收益率: {pf['return_pct']:.2f}%")
    print(f"  剩余现金: ${pf['cash']:,.2f}")
    print(f"  持仓数: {pf['open_positions']}")

    # 计算绩效指标
    if not trades_df.empty:
        # 构建权益曲线
        equity_curve = []
        cum_pnl = 0
        for _, t in trades_df.iterrows():
            cum_pnl += t["pnl_net"]
            equity_curve.append({"time": t["timestamp"], "equity": 100000 + cum_pnl})
        equity_s = pd.Series(
            [e["equity"] / 100000 for e in equity_curve],
            index=pd.to_datetime([e["time"] for e in equity_curve]),
        )
        metrics = calculate_metrics(equity_s, trades_df)
        print(f"\n  绩效指标:")
        for k, v in metrics.items():
            print(f"    {k}: {v}")

        report = generate_report(metrics, save=False)
        print(f"\n  {report}")

    # Broker 端验证
    print(f"\n  Broker 验证:")
    broker_pf = broker.get_portfolio()
    print(f"  Broker 权益: ${broker_pf['equity']:,.2f}")
    print(f"  Broker 收益率: {broker_pf['return_pct']:.2f}%")
    print(f"  Broker 成交: {broker_pf['total_trades']} 笔")

    # 保存记录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    engine.save_trades(f"e2e_trades_{timestamp}.csv")
    print(f"\n  成交记录已保存: backtests/e2e_trades_{timestamp}.csv")

    print("\n" + "=" * 60)
    if pf['total_trades'] > 0:
        print("  ✅ 端到端测试完成")
    else:
        print("  ⚠️  无交易执行（风控全部拦截或信号未触发）")
    print("=" * 60)

    return {
        "total_trades": pf['total_trades'],
        "final_equity": pf['equity'],
        "return_pct": pf['return_pct'],
        "engine_trades": len(trades_df),
        "broker_trades": broker_pf['total_trades'],
    }


if __name__ == "__main__":
    result = run_e2e_test()
    print(f"\n测试结束: {json.dumps(result, indent=2)}")
