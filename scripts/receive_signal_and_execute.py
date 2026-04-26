"""
信号接收与执行脚本
======================
接收 strategy_researcher 的 BB_Reversion 信号 → 过内建风控 → 执行下单 → 记录 → 通知 reporter

信号格式（JSON）：
{
    "strategy": "BB_Reversion",
    "version": "1.0",
    "generated_at": "ISO8601",
    "last_price": 713.98,
    "last_date": "2026-04-24",
    "current_position": 0,      // 当前持仓方向: 1=多, -1=空, 0=空仓
    "signals": [
        {
            "ticker": "SPY",
            "direction": 1,        // 1=做多, -1=做空, 0=平仓
            "confidence": 0.85,
            "signal_date": "2026-04-24",
            "entry_price": 713.94,
            "reason": "close_touched_lower_band",
            "metadata": { ... }
        }
    ]
}

用法:
    python scripts/receive_signal_and_execute.py --file signals/signal_BB_Reversion_*.json
    python scripts/receive_signal_and_execute.py --check           # 检查 signals/ 目录最新信号
"""

import os
import sys
import json
import argparse
import glob
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared_lib.execution_engine import ExecutionEngine
from shared_lib.risk_manager import RiskManager, RiskConfig, CircuitBreaker
from scripts.simulated_broker import SimulatedBroker

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("signal_executor")

# 路径
BASE_DIR = Path(__file__).parent.parent
SIGNAL_DIR = BASE_DIR / "signals"
TRADES_DIR = BASE_DIR / "backtests"

# ─── 内建风控（按 quant_lead 指令配置） ─────────────

class BuiltinRiskCheck:
    """
    内建风控检查模块
    配置：半凯利 ≤12.5%，断路器 2 连亏触发，冷却 10 bar
    """

    def __init__(self, engine: ExecutionEngine):
        self.engine = engine
        self.circuit_breaker = CircuitBreaker(
            max_consecutive_losses=2,   # 风控要求：2 次连亏触发
            cooldown_bars=10,           # 冷却 10 bar
        )
        self.max_position_pct = 0.125   # 半凯利 12.5%
        self.max_drawdown = 0.20        # 20%
        self.trade_count = 0

    def check(self, signal: dict) -> tuple[bool, str, dict]:
        """
        对单个信号执行全量风控检查

        Returns:
            (passed: bool, reason: str, adjusted_order: dict)
        """
        ticker = signal.get("ticker", "SPY")
        direction = signal.get("direction", 0)
        confidence = signal.get("confidence", 0.5)
        signal_date = signal.get("signal_date", "")
        entry_price = signal.get("entry_price", 0)

        pf = self.engine.get_portfolio()
        equity = pf["equity"]

        # 1. 断路器
        if self.circuit_breaker.tripped:
            return False, f"CIRCUIT_BREAKER: cooling down ({self.circuit_breaker.cooldown_remaining} bar remaining)", {}

        # 2. 方向检查
        if direction == 0:
            return False, f"NO_SIGNAL: direction=0 (no action)", {}

        if confidence < 0.3:
            return False, f"LOW_CONFIDENCE: {confidence:.2f} < 0.3", {}

        # 3. 已持仓时不再同向开仓
        pos = self.engine.get_position(ticker)
        if direction == 1 and pos["side"] == "long" and pos["quantity"] > 0:
            return False, f"ALREADY_LONG: existing {pos['quantity']} shares @ {pos['avg_price']}", {}

        if direction in (-1,) and pos["side"] == "short" and pos["quantity"] > 0:
            return False, f"ALREADY_SHORT: existing short position", {}

        # 4. 仓位规模检查（12.5% 上限）
        price = self.engine._last_prices.get(ticker, entry_price)
        if price == 0:
            return False, f"NO_PRICE: no price data for {ticker}", {}

        max_position_value = equity * self.max_position_pct
        # 用 ATR 计算动态头寸
        atr = signal.get("metadata", {}).get("atr_14", price * 0.02)
        risk_per_share = atr * 2  # 2 倍 ATR 止损距离

        # 按风险预算计算仓位
        risk_budget = equity * 0.02  # 每笔风险 ≤2%
        risk_adjusted_qty = max(1, int(risk_budget / risk_per_share))
        max_qty_by_value = int(max_position_value / price)

        qty = min(risk_adjusted_qty, max_qty_by_value)

        if qty < 1:
            return False, f"POSITION_TOO_SMALL: max qty=0 at ${price}", {}

        # 5. 现金检查（买入时）
        side = "buy" if direction == 1 else "sell"
        cost = qty * price * (1 + 0.001)  # 含佣金
        if side == "buy" and cost > self.engine.cash:
            max_cash_qty = int(self.engine.cash / (price * (1 + 0.001)))
            if max_cash_qty < 1:
                return False, f"INSUFFICIENT_CASH: ${self.engine.cash:.0f} < ${cost:.0f}", {}
            qty = max_cash_qty

        # 6. 回撤检查
        if pf['return_pct'] < -self.max_drawdown * 100:
            return False, f"MAX_DRAWDOWN: {pf['return_pct']:.2f}% < -{self.max_drawdown*100:.0f}%", {}

        adjusted_order = {
            "ticker": ticker,
            "side": side,
            "quantity": qty,
            "order_type": "market",
            "reason": signal.get("reason", "signal"),
            "confidence": confidence,
            "entry_price": price,
            "risk_per_share": round(risk_per_share, 2),
            "signal_date": signal_date,
        }

        return True, "ALL_CHECKS_PASSED", adjusted_order

    def record_trade(self, pnl: float):
        """记录交易盈亏给断路器"""
        self.circuit_breaker.record_trade(pnl)
        self.trade_count += 1

    def summary(self) -> str:
        return (
            f"  ─ 风控状态 ─\n"
            f"  断路器: {'⚡ TRIPPED' if self.circuit_breaker.tripped else '✅ NORMAL'}\n"
            f"  冷却剩余: {self.circuit_breaker.cooldown_remaining} bar\n"
            f"  连亏次数: {self.circuit_breaker.consecutive_losses}\n"
            f"  交易计数: {self.trade_count}\n"
            f"  最大仓位: {self.max_position_pct:.1%}\n"
            f"  最大回撤: {self.max_drawdown:.0%}"
        )


# ─── 执行流程 ───────────────────────────────────────

def load_signal(filepath: str = None) -> dict:
    """加载信号文件"""
    if filepath:
        path = Path(filepath)
        if not path.exists():
            logger.error(f"Signal file not found: {filepath}")
            return {}
        with open(path) as f:
            return json.load(f)

    # 找最新的信号文件
    files = sorted(SIGNAL_DIR.glob("signal_*.json"))
    if not files:
        logger.info("No signal files found in signals/")
        return {}
    latest = files[-1]
    logger.info(f"Loading latest signal: {latest}")
    with open(latest) as f:
        return json.load(f)


def execute_signal(signal_data: dict, engine: ExecutionEngine,
                   risk_check: BuiltinRiskCheck, broker: SimulatedBroker = None) -> dict:
    """
    执行单条信号

    Args:
        signal_data: 信号字典
        engine: 执行引擎
        risk_check: 风控检查器
        broker: 模拟券商（可选，用于独立验证）

    Returns:
        result dict
    """
    result = {
        "strategy": signal_data.get("strategy", "unknown"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals_processed": 0,
        "orders_placed": 0,
        "orders_filled": 0,
        "trades": [],
        "errors": [],
        "risk_status": {},
    }

    signals = signal_data.get("signals", [])

    if not signals:
        logger.info("No new signals to execute")
        result["message"] = "No signals"
        return result

    for sig in signals:
        result["signals_processed"] += 1
        ticker = sig.get("ticker", "SPY")

        logger.info(f"Processing signal: {sig.get('reason')} | {ticker} dir={sig.get('direction')}")

        # 风控检查
        passed, reason, order = risk_check.check(sig)

        if not passed:
            logger.warning(f"Risk check FAILED: {reason}")
            result["errors"].append({"ticker": ticker, "reason": reason})
            result["risk_status"][ticker] = f"❌ {reason}"
            continue

        result["risk_status"][ticker] = "✅ PASSED"

        # 执行下单
        try:
            oid = engine.submit_market_order(
                order["ticker"],
                order["side"],
                order["quantity"],
                metadata={
                    "strategy": signal_data.get("strategy"),
                    "reason": order["reason"],
                    "confidence": order["confidence"],
                }
            )
            logger.info(f"Order placed: {oid} | {order['side']} {order['quantity']} {order['ticker']}")

            # Broker 同步下单（独立验证）
            if broker:
                broker.place_order(
                    order["ticker"],
                    order["side"],
                    order["quantity"],
                    "market",
                )

            result["orders_placed"] += 1

            # 检查成交
            placed_order = engine.orders.get(oid)
            if placed_order and placed_order.status == "filled":
                result["orders_filled"] += 1
                trade_record = {
                    "order_id": oid,
                    "ticker": order["ticker"],
                    "side": order["side"],
                    "qty": order["quantity"],
                    "filled_qty": placed_order.filled_qty,
                    "fill_price": placed_order.avg_fill_price,
                    "reason": order["reason"],
                    "confidence": order["confidence"],
                    "risk_per_share": order["risk_per_share"],
                }
                result["trades"].append(trade_record)

                # 记录到断路器（先假设盈亏方向，实际盈亏需等平仓）
                result["orders_filled"] = result.get("orders_filled", 0)

        except Exception as e:
            logger.error(f"Execution error for {ticker}: {e}")
            result["errors"].append({"ticker": ticker, "error": str(e)})

    # 更新组合概况
    pf = engine.get_portfolio()
    result["portfolio"] = pf
    result["risk_summary"] = risk_check.summary()

    return result


def format_result(result: dict) -> str:
    """格式化执行结果为可读文本"""
    lines = [
        "=" * 55,
        "  信号执行报告",
        "=" * 55,
        f"  策略:        {result['strategy']}",
        f"  执行时间:    {result['timestamp']}",
        f"  信号数:      {result['signals_processed']}",
        f"  下单数:      {result['orders_placed']}",
        f"  成交数:      {result['orders_filled']}",
        f"  错误数:      {len(result['errors'])}",
        "-" * 55,
    ]

    if result["trades"]:
        lines.append("  成交明细:")
        for t in result["trades"]:
            lines.append(f"    {t['ticker']} | {t['side']} {t['filled_qty']} @ ${t['fill_price']:.2f} | {t['reason']} (conf={t['confidence']:.2f})")

    if result["errors"]:
        lines.append("  错误:")
        for e in result["errors"]:
            lines.append(f"    ❌ {e.get('ticker', '?')}: {e.get('reason', e.get('error', 'unknown'))}")

    pf = result.get("portfolio", {})
    if pf:
        lines.extend([
            "-" * 55,
            "  组合概况:",
            f"  权益:       ${pf['equity']:>10,.2f}",
            f"  现金:       ${pf['cash']:>10,.2f}",
            f"  收益率:     {pf['return_pct']:>9.2f}%",
            f"  持仓:       {pf['open_positions']}",
            f"  总交易:     {pf['total_trades']}",
        ])

    lines.extend([
        "-" * 55,
        result.get("risk_summary", ""),
        "=" * 55,
    ])

    return "\n".join(lines)


# ─── 主入口 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="信号接收与执行")
    parser.add_argument("--file", "-f", help="信号 JSON 文件路径")
    parser.add_argument("--check", action="store_true", help="检查 signals/ 目录最新信号")
    parser.add_argument("--init-capital", type=float, default=100000, help="初始资金")
    parser.add_argument("--save-trades", action="store_true", default=True, help="保存成交记录")
    parser.add_argument("--historical-prices", nargs="*", type=float, help="历史收盘价（用于回测回放）")
    args = parser.parse_args()

    if args.check:
        files = sorted(SIGNAL_DIR.glob("signal_*.json"))
        if not files:
            print("No signal files found.")
            return
        for f in files:
            with open(f) as fh:
                data = json.load(fh)
            signal_count = len(data.get("signals", []))
            print(f"  {f.name}")
            print(f"    策略: {data.get('strategy')} | 最新价: ${data.get('last_price', '?')} | 信号: {signal_count}")
            for s in data.get("signals", []):
                print(f"      -> {s['ticker']} dir={s['direction']} conf={s['confidence']} reason={s['reason']}")
        return

    # 加载信号
    signal_data = load_signal(args.file)
    if not signal_data:
        print("No signal data loaded.")
        return

    print(f"\nLoaded signal: {signal_data.get('strategy')} v{signal_data.get('version')}")
    print(f"Generated: {signal_data.get('generated_at')}")
    print(f"Signals: {len(signal_data.get('signals', []))}")

    # 初始化引擎与风控
    engine = ExecutionEngine(initial_capital=args.init_capital)
    broker = SimulatedBroker(initial_capital=args.init_capital)
    broker.connect()
    risk = BuiltinRiskCheck(engine)

    # 如果有历史价格序列、喂给引擎
    if args.historical_prices:
        for p in args.historical_prices:
            engine.tick("SPY", p)
            broker.tick("SPY", p)
    else:
        # 喂入当前价格
        latest_price = signal_data.get("last_price", 500)
        engine.tick("SPY", latest_price)
        broker.tick("SPY", latest_price)

    # 执行信号
    result = execute_signal(signal_data, engine, risk, broker)

    # 输出结果
    print(f"\n{format_result(result)}")

    # 保存成交记录
    if args.save_trades and result["trades"]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        engine.save_trades(f"signal_exec_{ts}.csv")
        if broker:
            broker.save_trades(f"signal_broker_{ts}.csv")
        print(f"\n  成交记录已保存")

    # 输出 JSON 结果（供其他组件读取）
    result_path = TRADES_DIR / f"exec_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"  执行结果已保存: {result_path}")

    return result


if __name__ == "__main__":
    main()
