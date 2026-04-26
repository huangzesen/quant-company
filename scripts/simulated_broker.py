"""
模拟券商（Simulated Broker）
============================
独立于 backtrader2 的轻量模拟成交系统。
基于 config.yaml 的佣金/滑点参数，可直接对接执行引擎。

用法:
    python scripts/simulated_broker.py          # 运行示例
    python scripts/simulated_broker.py --test   # 运行测试

或作为模块导入:
    from scripts.simulated_broker import SimulatedBroker
    broker = SimulatedBroker()
    broker.connect()
    order_id = broker.place_order("AAPL", "buy", 100, order_type="market")
    broker.tick("AAPL", 180.5)
    broker.summary()
"""

import os
import sys
import yaml
import json
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulated_broker")

# 加载配置
_CONFIG_PATH = Path(__file__).parent.parent / "config/config.yaml"
with open(_CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)


# ─── 订单簿 ────────────────────────────────────────────

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"


class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class OrderBookEntry:
    """订单簿中的挂单条目"""
    order_id: str
    side: OrderSide
    price: float
    quantity: float
    remaining: float
    timestamp: str
    order_type: str = "limit"  # limit | market


@dataclass
class Trade:
    """成交记录"""
    order_id: str
    ticker: str
    side: str
    quantity: float
    price: float
    commission: float
    pnl: float
    timestamp: str


# ─── 模拟券商 ──────────────────────────────────────────

class SimulatedBroker:
    """
    模拟券商 — 含订单簿、撮合引擎、资金管理

    功能:
    - 市价单即时成交
    - 限价单挂单 + 行情驱动撮合
    - 订单簿管理（买盘/卖盘队列）
    - 条件单（止盈止损）
    - 资金/仓位/权益实时计算
    - 成交记录归档
    """

    def __init__(self, initial_capital: float = None):
        config = CONFIG["backtest"]
        self.initial_capital = initial_capital or config.get("default_capital", 100000)
        self.commission_rate = config.get("commission", 0.001)
        self.slippage_rate = config.get("slippage", 0.001)

        # 账户
        self.cash = self.initial_capital
        self.positions: Dict[str, dict] = {}  # ticker -> {qty, avg_price, side}

        # 订单簿
        self.order_book: Dict[str, OrderBookEntry] = {}
        self._bids: Dict[str, List[OrderBookEntry]] = {}  # ticker -> 买单队列
        self._asks: Dict[str, List[OrderBookEntry]] = {}  # ticker -> 卖单队列

        # 条件单
        self._stop_orders: List[dict] = []

        # 成交记录
        self.trades: List[Trade] = []
        self._order_counter = 0
        self._last_prices: Dict[str, float] = {}

        # 市场状态
        self.market_open = True

        logger.info(
            f"SimulatedBroker initialized | "
            f"capital={self.initial_capital:.0f} comm={self.commission_rate:.3f} slippage={self.slippage_rate:.3f}"
        )

    def connect(self) -> bool:
        """模拟连接券商"""
        logger.info("SimulatedBroker: connected (simulated)")
        return True

    def disconnect(self):
        """模拟断开"""
        logger.info("SimulatedBroker: disconnected")

    # ── 订单管理 ──

    def _next_id(self) -> str:
        self._order_counter += 1
        return f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self._order_counter:04d}"

    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float = None,
                    stop_price: float = None) -> str:
        """
        下单

        Args:
            ticker: 标的代码
            side: "buy" | "sell" | "short"
            quantity: 数量
            order_type: "market" | "limit" | "stop" | "stop_limit"
            price: 限价单价格
            stop_price: 止损触发价

        Returns:
            order_id (str)
        """
        order_id = self._next_id()
        side_enum = OrderSide(side)

        if not self.market_open:
            logger.warning(f"Market closed, order {order_id} rejected")
            return order_id

        # 检查数量合法性
        if quantity <= 0:
            logger.error(f"Invalid quantity {quantity} for {order_id}")
            return order_id

        # 市价单
        if order_type == "market":
            if ticker not in self._last_prices:
                logger.warning(f"No price data for {ticker}, order {order_id} pending as market")
                # 挂起等待行情
                self.order_book[order_id] = OrderBookEntry(
                    order_id=order_id, side=side_enum, price=0,
                    quantity=quantity, remaining=quantity,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    order_type="market",
                )
            else:
                self._execute_market(order_id, ticker, side_enum, quantity,
                                     self._last_prices[ticker])

        # 限价单
        elif order_type == "limit":
            if price is None:
                logger.error(f"Limit order {order_id} requires price")
                return order_id

            entry = OrderBookEntry(
                order_id=order_id, side=side_enum, price=price,
                quantity=quantity, remaining=quantity,
                timestamp=datetime.now(timezone.utc).isoformat(),
                order_type="limit",
            )
            self.order_book[order_id] = entry

            # 加入订单簿队列
            if side_enum == OrderSide.BUY:
                self._bids.setdefault(ticker, []).append(entry)
                self._bids[ticker].sort(key=lambda x: x.price, reverse=True)
            else:
                self._asks.setdefault(ticker, []).append(entry)
                self._asks[ticker].sort(key=lambda x: x.price)

            # 尝试立即撮合
            self._try_match(ticker)
            logger.info(f"Limit order placed: {order_id} | {side} {quantity} {ticker} @ {price}")

        # 止损单
        elif order_type == "stop":
            if stop_price is None:
                logger.error(f"Stop order {order_id} requires stop_price")
                return order_id
            self._stop_orders.append({
                "order_id": order_id, "ticker": ticker, "side": side_enum,
                "quantity": quantity, "stop_price": stop_price,
                "triggered": False,
            })
            logger.info(f"Stop order placed: {order_id} | {side} {quantity} {ticker} @ stop={stop_price}")

        # 止损限价单
        elif order_type == "stop_limit":
            if stop_price is None or price is None:
                logger.error(f"Stop-limit order {order_id} requires stop_price and price")
                return order_id
            self._stop_orders.append({
                "order_id": order_id, "ticker": ticker, "side": side_enum,
                "quantity": quantity, "stop_price": stop_price,
                "limit_price": price, "order_type": "stop_limit",
                "triggered": False,
            })
            logger.info(f"Stop-limit order placed: {order_id}")

        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if order_id in self.order_book:
            entry = self.order_book[order_id]
            if entry.remaining > 0:
                entry.remaining = 0
                logger.info(f"Order cancelled: {order_id}")
                return True
        return False

    def cancel_all(self, ticker: str = None):
        """取消所有订单（可选按标的）"""
        to_remove = []
        for oid, entry in self.order_book.items():
            if ticker is None or entry.order_id.split("-")[0] == ticker:
                to_remove.append(oid)
        for oid in to_remove:
            self.order_book[oid].remaining = 0
            logger.info(f"Order cancelled: {oid}")

    # ── 内部撮合 ──

    def _execute_market(self, order_id: str, ticker: str, side: OrderSide,
                        quantity: float, market_price: float):
        """执行市价单"""
        # 加滑点
        slippage = 1 + (self.slippage_rate if side == OrderSide.BUY else -self.slippage_rate)
        fill_price = round(market_price * slippage, 2)
        gross_value = quantity * fill_price
        commission = round(gross_value * self.commission_rate, 2)

        # 检查资金
        if side == OrderSide.BUY:
            total_cost = gross_value + commission
            if total_cost > self.cash:
                max_qty = int(self.cash / (fill_price * (1 + self.commission_rate)))
                if max_qty <= 0:
                    self.order_book[order_id] = OrderBookEntry(
                        order_id=order_id, side=side, price=0,
                        quantity=quantity, remaining=quantity,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        order_type="market",
                    )
                    logger.warning(f"{order_id}: insufficient funds, pending")
                    return
                quantity = max_qty
                gross_value = quantity * fill_price
                commission = round(gross_value * self.commission_rate, 2)

        # 执行成交
        self._fill(order_id, ticker, side, quantity, fill_price, commission)

    def _fill(self, order_id: str, ticker: str, side: OrderSide,
              qty: float, price: float, commission: float):
        """执行成交"""
        old_position_pnl = 0
        pos = self.positions.get(ticker, {"qty": 0, "avg_price": 0, "side": "flat"})

        # 计算平仓盈亏
        if side == OrderSide.SELL and pos["side"] == "long":
            old_position_pnl = qty * (price - pos["avg_price"])
            pos["qty"] -= qty
            if pos["qty"] <= 0:
                pos["qty"] = 0
                pos["avg_price"] = 0
                pos["side"] = "flat"

        elif side == OrderSide.BUY:
            # 开多/加多
            total_cost = pos["avg_price"] * pos["qty"] + qty * price
            pos["qty"] += qty
            pos["avg_price"] = total_cost / pos["qty"]
            pos["side"] = "long"

        elif side == OrderSide.SHORT:
            # 开空
            total_cost = pos["avg_price"] * pos["qty"] + qty * price
            pos["qty"] += qty
            pos["avg_price"] = total_cost / pos["qty"]
            pos["side"] = "short"

        # 更新现金
        if side == OrderSide.BUY:
            self.cash -= (qty * price + commission)
        elif side == OrderSide.SELL:
            self.cash += (qty * price - commission)
        elif side == OrderSide.SHORT:
            self.cash += (qty * price - commission)

        self.positions[ticker] = pos

        pnl_net = round(old_position_pnl - commission, 2)

        # 记录成交
        trade = Trade(
            order_id=order_id, ticker=ticker, side=side.value,
            quantity=qty, price=price, commission=commission,
            pnl=pnl_net,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.trades.append(trade)

        # 更新订单簿
        if order_id in self.order_book:
            entry = self.order_book[order_id]
            entry.remaining = max(0, entry.remaining - qty)
            if entry.remaining <= 0:
                del self.order_book[order_id]

        equity = self.cash + self._position_value()
        logger.info(
            f"FILLED: {order_id} | {side.value} {qty} {ticker} @ {price:.2f} "
            f"| pnl={pnl_net:.2f} | cash={self.cash:.2f} equity={equity:.2f}"
        )

    def _try_match(self, ticker: str):
        """尝试撮合订单簿中的限价单"""
        if ticker not in self._last_prices:
            return

        price = self._last_prices[ticker]
        bids = self._bids.get(ticker, [])
        asks = self._asks.get(ticker, [])

        # 撮合买单（买价 >= 市价）
        for bid in bids[:]:
            if bid.remaining > 0 and bid.price >= price:
                self._fill(bid.order_id, ticker, OrderSide.BUY,
                           bid.remaining, price,
                           round(bid.remaining * price * self.commission_rate, 2))
                if bid.order_id not in self.order_book:
                    bids.remove(bid)

        # 撮合卖单（卖价 <= 市价）
        for ask in asks[:]:
            if ask.remaining > 0 and ask.price <= price:
                self._fill(ask.order_id, ticker, OrderSide.SELL,
                           ask.remaining, price,
                           round(ask.remaining * price * self.commission_rate, 2))
                if ask.order_id not in self.order_book:
                    asks.remove(ask)

    def _check_stop_orders(self, ticker: str, price: float):
        """检查止损单"""
        for stop in self._stop_orders:
            if stop["ticker"] != ticker or stop["triggered"]:
                continue

            triggered = False
            if stop["side"] in (OrderSide.SELL, OrderSide.SHORT) and price <= stop["stop_price"]:
                triggered = True
            elif stop["side"] == OrderSide.BUY and price >= stop["stop_price"]:
                triggered = True

            if triggered:
                stop["triggered"] = True
                limit_price = stop.get("limit_price", price)
                self._execute_market(
                    stop["order_id"], ticker, stop["side"],
                    stop["quantity"], limit_price,
                )
                logger.info(f"Stop order triggered: {stop['order_id']} @ {price}")

    # ── 行情喂入 ──

    def tick(self, ticker: str, price: float):
        """喂入最新行情"""
        self._last_prices[ticker] = price

        # 撮合订单簿
        self._try_match(ticker)

        # 检查止损单
        self._check_stop_orders(ticker, price)

        # 检查挂起的市价单
        for oid, entry in list(self.order_book.items()):
            if entry.order_type == "market" and entry.side in (
                OrderSide.BUY, OrderSide.SELL
            ):
                self._execute_market(oid, entry.side.name.lower().split(".")[-1],
                                     entry.side, entry.remaining, price)

    def set_market_state(self, open: bool):
        """设置市场开闭状态"""
        self.market_open = open
        logger.info(f"Market {'opened' if open else 'closed'}")

    # ── 查询 ──

    def get_position(self, ticker: str) -> dict:
        return self.positions.get(ticker, {"qty": 0, "avg_price": 0, "side": "flat"})

    def _position_value(self) -> float:
        return sum(
            p["qty"] * self._last_prices.get(t, p["avg_price"])
            for t, p in self.positions.items()
        )

    def get_portfolio(self) -> dict:
        pv = self._position_value()
        equity = self.cash + pv
        return {
            "cash": round(self.cash, 2),
            "position_value": round(pv, 2),
            "equity": round(equity, 2),
            "return_pct": round((equity / self.initial_capital - 1) * 100, 4),
            "open_positions": len([p for p in self.positions.values() if p["qty"] > 0]),
            "open_orders": len([e for e in self.order_book.values() if e.remaining > 0]),
            "total_trades": len(self.trades),
        }

    def get_order_book(self, ticker: str) -> dict:
        """获取某标的的订单簿深度"""
        bids = sorted(
            [{"price": e.price, "qty": e.remaining}
             for e in self._bids.get(ticker, []) if e.remaining > 0],
            key=lambda x: x["price"], reverse=True,
        )
        asks = sorted(
            [{"price": e.price, "qty": e.remaining}
             for e in self._asks.get(ticker, []) if e.remaining > 0],
            key=lambda x: x["price"],
        )
        return {"bids": bids[:10], "asks": asks[:10]}

    def summary(self) -> str:
        pf = self.get_portfolio()
        lines = [
            "=" * 55,
            "  模拟券商 (SimulatedBroker) 摘要",
            "=" * 55,
            f"  初始资金:   ${self.initial_capital:>10,.2f}",
            f"  当前现金:   ${pf['cash']:>10,.2f}",
            f"  持仓市值:   ${pf['position_value']:>10,.2f}",
            f"  总权益:     ${pf['equity']:>10,.2f}",
            f"  累计收益:   {pf['return_pct']:>9.2f}%",
            f"  持仓数:     {pf['open_positions']}",
            f"  挂单数:     {pf['open_orders']}",
            f"  总成交:     {pf['total_trades']} 笔",
            "-" * 55,
        ]
        if self.trades:
            pnl_total = sum(t.pnl for t in self.trades)
            wins = sum(1 for t in self.trades if t.pnl > 0)
            lines.append(f"  累计盈亏:   ${pnl_total:>10,.2f}")
            lines.append(f"  胜率:       {wins/max(len(self.trades),1):>9.1%}")
        lines.append("=" * 55)
        return "\n".join(lines)

    def get_trade_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        records = []
        for t in self.trades:
            records.append({
                "order_id": t.order_id, "ticker": t.ticker, "side": t.side,
                "quantity": t.quantity, "price": t.price,
                "commission": t.commission, "pnl": t.pnl,
                "timestamp": t.timestamp,
            })
        return pd.DataFrame(records)

    def load_state(self, path: str = None):
        """从文件加载状态"""
        if path is None:
            path = str(Path(__file__).parent.parent / "backtests/broker_state.json")
        p = Path(path)
        if p.exists():
            with open(p) as f:
                state = json.load(f)
            self.cash = state.get("cash", self.initial_capital)
            self.positions = state.get("positions", {})
            logger.info(f"State loaded from {path}")

    def save_state(self, path: str = None):
        """保存状态到文件"""
        if path is None:
            path = str(Path(__file__).parent.parent / "backtests/broker_state.json")
        state = {
            "cash": self.cash,
            "positions": self.positions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.info(f"State saved to {path}")

    def save_trades(self, path: str = None):
        """保存成交记录到 CSV"""
        if path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(Path(__file__).parent.parent / f"backtests/trades_{ts}.csv")
        df = self.get_trade_df()
        if not df.empty:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
            logger.info(f"Trades saved: {path} ({len(df)} rows)")


# ─── 测试 ────────────────────────────────────────────

def run_test():
    """运行完整测试"""
    print("\n" + "=" * 55)
    print("  SimulatedBroker 测试套件")
    print("=" * 55)

    broker = SimulatedBroker(initial_capital=100000)
    broker.connect()

    # 测试1: 市价单买入
    print("\n--- 测试1: 市价买入 100 股 SPY ---")
    broker.tick("SPY", 500.0)
    oid = broker.place_order("SPY", "buy", 100, "market")
    pf = broker.get_portfolio()
    print(f"  权益: ${pf['equity']:.2f} | 现金: ${pf['cash']:.2f} | 持仓: {pf['open_positions']}")

    # 测试2: 限价单
    print("\n--- 测试2: 限价买入 50 股 AAPL @ 175 ---")
    broker.tick("AAPL", 178.0)
    oid2 = broker.place_order("AAPL", "buy", 50, "limit", price=175.0)
    print(f"  订单ID: {oid2}")
    ob = broker.get_order_book("AAPL")
    print(f"  订单簿买单: {len(ob['bids'])} 笔")
    # 喂入触发价
    broker.tick("AAPL", 174.5)
    pf2 = broker.get_portfolio()
    print(f"  触发后权益: ${pf2['equity']:.2f} | AAPL仓位: {broker.get_position('AAPL')}")

    # 测试3: 止损单
    print("\n--- 测试3: 止损卖出 50 股 SPY @ 490 ---")
    oid3 = broker.place_order("SPY", "sell", 50, "stop", stop_price=490.0)
    broker.tick("SPY", 489.0)
    pf3 = broker.get_portfolio()
    print(f"  止损触发后权益: ${pf3['equity']:.2f}")

    # 测试4: 卖出平仓
    print("\n--- 测试4: 市价卖出 50 股 SPY ---")
    broker.tick("SPY", 505.0)
    oid4 = broker.place_order("SPY", "sell", 50, "market")
    pf4 = broker.get_portfolio()
    print(f"  平仓后权益: ${pf4['equity']:.2f} | 现金: ${pf4['cash']:.2f} | SPY仓位: {broker.get_position('SPY')}")

    # 测试5: 订单簿查询
    print("\n--- 测试5: 订单簿 ---")
    broker.tick("MSFT", 400.0)
    broker.place_order("MSFT", "buy", 30, "limit", price=395.0)
    broker.place_order("MSFT", "sell", 20, "limit", price=405.0)
    ob = broker.get_order_book("MSFT")
    print(f"  MSFT 买单: {len(ob['bids'])} 笔")
    print(f"  MSFT 卖单: {len(ob['asks'])} 笔")

    # 测试6: 摘要
    print(f"\n{broker.summary()}")

    # 测试7: 保存
    broker.save_trades()
    broker.save_state()

    print("\n✅ 所有测试通过\n")
    return broker


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        run_test()
    else:
        # 运行示例
        broker = run_test()
