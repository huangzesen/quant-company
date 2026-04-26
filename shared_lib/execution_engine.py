"""
执行引擎 — 下单执行、仓位管理、交易记录
当前模式: paper (模拟成交)

支持:
- 本地模拟成交引擎（缺省，无需API）
- Alpaca paper trading（需配置 API 凭证）
- CCXT 加密币（待配置）
"""

import os
import json
import yaml
import pandas as pd
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
import logging

logger = logging.getLogger("quant.execution")

_CONFIG_PATH = Path(__file__).parent.parent / "config/config.yaml"
with open(_CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

TRADES_DIR = Path(__file__).parent.parent / "backtests"
TRADES_DIR.mkdir(parents=True, exist_ok=True)


# ─── 数据类 ─────────────────────────────────────────────

@dataclass
class Order:
    """订单"""
    order_id: str
    ticker: str
    side: str                 # "buy" | "sell" | "short"
    quantity: float
    order_type: str           # "market" | "limit"
    limit_price: Optional[float] = None
    status: str = "pending"   # pending | filled | partial | cancelled | rejected
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at: str = ""
    filled_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class Fill:
    """成交回报"""
    order_id: str
    ticker: str
    side: str
    quantity: float
    price: float
    commission: float = 0.0
    timestamp: str = ""


# ─── 执行引擎 ───────────────────────────────────────────

class ExecutionEngine:
    """
    执行引擎 — 管理下单、模拟成交、仓位追踪

    用法:
        engine = ExecutionEngine(initial_capital=100000)
        engine.submit_market_order("AAPL", "buy", 10)
        engine.tick("AAPL", current_price=180.5)
    """

    def __init__(self, initial_capital: float = None, commission: float = None,
                 slippage: float = None, mode: str = "simulation"):
        self.mode = mode  # "simulation" | "alpaca" | "ccxt"
        self.initial_capital = initial_capital or CONFIG["backtest"].get("default_capital", 100000)
        self.commission = commission or CONFIG["backtest"].get("commission", 0.001)
        self.slippage = slippage or CONFIG["backtest"].get("slippage", 0.001)

        # 账户状态
        self.cash = self.initial_capital
        self.equity = self.initial_capital
        self.positions: Dict[str, Dict] = {}   # ticker -> {quantity, avg_price, side}
        self.orders: Dict[str, Order] = {}      # order_id -> Order
        self.trades: List[dict] = []            # 已完成的交易记录
        self.order_counter = 0

        # 最新行情缓存
        self._last_prices: Dict[str, float] = {}

        logger.info(
            f"ExecutionEngine initialized | mode={mode} "
            f"capital={self.initial_capital:.0f} "
            f"commission={self.commission:.3f} "
            f"slippage={self.slippage:.3f}"
        )

    # ── 下单 ──

    def _next_order_id(self) -> str:
        self.order_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"ORD-{ts}-{self.order_counter:04d}"

    def submit_order(self, ticker: str, side: str, quantity: float,
                     order_type: str = "market", limit_price: float = None,
                     metadata: dict = None) -> str:
        """提交订单，返回 order_id"""
        order_id = self._next_order_id()
        order = Order(
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            metadata=metadata or {},
        )
        self.orders[order_id] = order
        logger.info(f"Order submitted: {order_id} | {side} {quantity} {ticker} @ {order_type}")

        # 市价单立即尝试模拟成交
        if order_type == "market":
            if ticker in self._last_prices:
                self._fill_order(order_id, self._last_prices[ticker])
            else:
                logger.warning(f"{ticker}: no price data, order {order_id} pending")
        elif order_type == "limit" and limit_price is not None:
            # 限价单等待价格匹配
            pass

        return order_id

    def submit_market_order(self, ticker: str, side: str, quantity: float,
                            metadata: dict = None) -> str:
        """快捷：市价单"""
        return self.submit_order(ticker, side, quantity, "market", metadata=metadata)

    # ── 模拟成交 ──

    def _fill_order(self, order_id: str, market_price: float) -> Optional[dict]:
        """模拟订单成交"""
        order = self.orders.get(order_id)
        if not order or order.status in ("filled", "cancelled", "rejected"):
            return None

        # 计算成交价格（加滑点）
        if order.order_type == "limit" and order.limit_price is not None:
            if order.side == "buy" and market_price > order.limit_price:
                return None  # 限价单未到价
            if order.side == "sell" and market_price < order.limit_price:
                return None
            fill_price = order.limit_price
        else:
            # 市价单：加滑点
            slippage_factor = 1 + (self.slippage if order.side == "buy" else -self.slippage)
            fill_price = market_price * slippage_factor

        fill_qty = order.quantity
        gross_value = fill_qty * fill_price
        commission = gross_value * self.commission

        # 检查资金
        if order.side in ("buy",):
            total_cost = gross_value + commission
            if total_cost > self.cash:
                # 资金不足，部分成交
                max_qty = int((self.cash) / (fill_price * (1 + self.commission)))
                if max_qty <= 0:
                    order.status = "rejected"
                    logger.warning(f"{order_id}: insufficient funds, rejected")
                    return None
                fill_qty = max_qty
                gross_value = fill_qty * fill_price
                commission = gross_value * self.commission
                total_cost = gross_value + commission

        # 更新仓位
        self._update_position(order.ticker, order.side, fill_qty, fill_price, commission)

        # 更新现金
        if order.side == "buy":
            self.cash -= (gross_value + commission)
        elif order.side == "sell":
            self.cash += (gross_value - commission)
        elif order.side == "short":
            self.cash += (gross_value - commission)

        # 更新订单状态
        order.status = "filled"
        order.filled_qty = fill_qty
        order.avg_fill_price = round(fill_price, 4)
        order.filled_at = datetime.now(timezone.utc).isoformat()

        self.equity = self._calc_equity()
        logger.info(
            f"Filled: {order_id} | {order.side} {fill_qty} {order.ticker} "
            f"@ {fill_price:.2f} | cash={self.cash:.2f} equity={self.equity:.2f}"
        )

        return {"order_id": order_id, "ticker": order.ticker, "side": order.side,
                "qty": fill_qty, "price": fill_price, "commission": commission}

    def _update_position(self, ticker: str, side: str, qty: float,
                         price: float, commission: float):
        """更新持仓"""
        if ticker not in self.positions:
            self.positions[ticker] = {"quantity": 0, "avg_price": 0.0, "side": "long"}

        pos = self.positions[ticker]

        if side == "buy":
            # 加多仓
            total_cost = pos["quantity"] * pos["avg_price"] + qty * price
            pos["quantity"] += qty
            pos["avg_price"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else 0
            pos["side"] = "long"

        elif side == "sell":
            # 减多仓 / 平多
            trade_pnl = qty * (price - pos["avg_price"]) if pos["side"] == "long" else 0
            pos["quantity"] -= qty
            if pos["quantity"] <= 0:
                pos["quantity"] = 0
                pos["avg_price"] = 0
                pos["side"] = "flat"
            # 记录交易
            self._record_trade(ticker, "sell", qty, price, pos["avg_price"], trade_pnl, commission)

        elif side == "short":
            # 开空仓（简化处理）
            total_cost = pos["quantity"] * pos["avg_price"] + qty * price
            pos["quantity"] += qty
            pos["avg_price"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else 0
            pos["side"] = "short"

    def _record_trade(self, ticker: str, side: str, qty: float, price: float,
                      avg_cost: float, pnl: float, commission: float):
        """记录完成交易"""
        trade = {
            "ticker": ticker,
            "side": side,
            "quantity": qty,
            "price": round(price, 4),
            "avg_cost": round(avg_cost, 4),
            "pnl": round(pnl, 2),
            "commission": round(commission, 2),
            "pnl_net": round(pnl - commission, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.trades.append(trade)

    # ── 行情喂入 ──

    def tick(self, ticker: str, price: float):
        """喂入最新行情，触发限价单检查"""
        self._last_prices[ticker] = price
        # 检查是否有待成交的限价单
        for oid, order in list(self.orders.items()):
            if order.ticker == ticker and order.status == "pending":
                if order.order_type == "limit":
                    if order.side == "buy" and price <= order.limit_price:
                        self._fill_order(oid, price)
                    elif order.side == "sell" and price >= order.limit_price:
                        self._fill_order(oid, price)
                elif order.order_type == "market" and order.status == "pending":
                    self._fill_order(oid, price)

    # ── 查询 ──

    def get_position(self, ticker: str) -> dict:
        """查询某标的持仓"""
        return self.positions.get(ticker, {"quantity": 0, "avg_price": 0.0, "side": "flat"})

    def get_portfolio(self) -> dict:
        """查询组合概况"""
        pos_value = sum(
            p["quantity"] * self._last_prices.get(t, p["avg_price"])
            for t, p in self.positions.items()
        )
        self.equity = self.cash + pos_value
        return {
            "cash": round(self.cash, 2),
            "position_value": round(pos_value, 2),
            "equity": round(self.equity, 2),
            "return_pct": round((self.equity / self.initial_capital - 1) * 100, 4),
            "open_positions": len([p for p in self.positions.values() if p["quantity"] > 0]),
            "total_trades": len(self.trades),
        }

    def _calc_equity(self) -> float:
        pos_value = sum(
            p["quantity"] * self._last_prices.get(t, p["avg_price"])
            for t, p in self.positions.items()
        )
        return self.cash + pos_value

    def get_open_orders(self) -> List[Order]:
        return [o for o in self.orders.values() if o.status == "pending"]

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if order_id in self.orders and self.orders[order_id].status == "pending":
            self.orders[order_id].status = "cancelled"
            logger.info(f"Order cancelled: {order_id}")
            return True
        return False

    def get_trade_history(self) -> pd.DataFrame:
        """获取交易历史"""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame(self.trades)

    # ── 持久化 ──

    def save_trades(self, filename: str = None):
        """保存交易记录到 CSV"""
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"trades_{ts}.csv"

        path = TRADES_DIR / filename
        df = self.get_trade_history()
        if not df.empty:
            df.to_csv(path, index=False)
            logger.info(f"Trades saved: {path} ({len(df)} rows)")
        else:
            logger.info("No trades to save")

    def summary(self) -> str:
        """生成执行摘要"""
        pf = self.get_portfolio()
        lines = [
            "=" * 50,
            "  执行引擎摘要",
            "=" * 50,
            f"  模式:      {self.mode}",
            f"  初始资金:  ${self.initial_capital:,.2f}",
            f"  当前权益:  ${pf['equity']:,.2f}",
            f"  现金:      ${pf['cash']:,.2f}",
            f"  收益率:    {pf['return_pct']:.2f}%",
            f"  总交易:    {pf['total_trades']}",
            f"  持仓数:    {pf['open_positions']}",
            "-" * 50,
        ]

        if self.trades:
            df = self.get_trade_history()
            lines.append(f"  累计盈亏:  ${df['pnl_net'].sum():,.2f}")
            lines.append(f"  胜率:      {(df['pnl_net'] > 0).mean():.1%}")

        lines.append("=" * 50)
        return "\n".join(lines)


# ─── 便捷工厂 ──────────────────────────────────────────

def create_engine(mode: str = "simulation") -> ExecutionEngine:
    """
    创建执行引擎实例

    Args:
        mode: "simulation" | "alpaca" | "ccxt"

    Returns:
        ExecutionEngine 实例
    """
    config = CONFIG.get("execution", {})
    mode = mode or config.get("mode", "paper")

    if mode == "live":
        # 实盘模式 — 需要 API 凭证
        logger.warning("Live mode selected but not yet configured")
        return ExecutionEngine(mode="simulation")

    # paper / simulation 模式
    return ExecutionEngine(
        initial_capital=CONFIG["backtest"].get("default_capital", 100000),
        commission=CONFIG["backtest"].get("commission", 0.001),
        slippage=CONFIG["backtest"].get("slippage", 0.001),
        mode="simulation",
    )
