"""
风控模块
组合风控、头寸规模、回撤控制、VaR 计算
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import logging

logger = logging.getLogger("quant.risk")


@dataclass
class RiskConfig:
    max_drawdown: float = 0.20
    max_position_pct: float = 0.25
    max_leverage: float = 1.0
    max_correlation: float = 0.80
    var_confidence: float = 0.95
    min_win_rate: float = 0.40


class RiskManager:
    """组合级与策略级风控"""

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.positions: Dict[str, float] = {}
        self.returns_log: Dict[str, pd.Series] = {}

    def check_position_size(self, ticker: str, proposed_size: float, equity: float) -> float:
        """检查头寸是否超过最大限制，返回调整后的头寸"""
        max_allowed = equity * self.config.max_position_pct
        if proposed_size > max_allowed:
            logger.warning(
                f"{ticker}: {proposed_size:.2f} > max {max_allowed:.2f}, "
                f"capping at {max_allowed:.2f}"
            )
            return max_allowed
        return proposed_size

    def check_max_drawdown(self, equity_curve: pd.Series) -> bool:
        """检查是否触发最大回撤限制"""
        peak = equity_curve.expanding().max()
        dd = (equity_curve - peak) / peak
        current_dd = dd.iloc[-1]
        if current_dd < -self.config.max_drawdown:
            logger.warning(
                f"Max drawdown triggered: {current_dd:.2%} < -{self.config.max_drawdown:.0%}"
            )
            return False  # 风控触发，停止交易
        return True

    def calculate_var(self, returns: pd.Series) -> float:
        """历史模拟 VaR"""
        confidence = self.config.var_confidence
        var = returns.quantile(1 - confidence)
        return var

    def check_portfolio_correlation(self, returns_matrix: pd.DataFrame) -> bool:
        """检查组合中是否相关性过高"""
        corr = returns_matrix.corr()
        # 检查是否存在超过阈值的相关性对
        upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
        max_corr = upper.max().max()
        if max_corr > self.config.max_correlation:
            logger.warning(
                f"Portfolio correlation {max_corr:.2f} > {self.config.max_correlation}"
            )
            return False
        return True

    def kelly_fraction(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """凯利公式计算最优仓位比例"""
        if avg_loss == 0:
            return 0
        b = avg_win / abs(avg_loss)
        f = (win_rate * (b + 1) - 1) / b
        return max(0, min(f, self.config.max_position_pct))


class CircuitBreaker:
    """断路器——防止接连亏损时的条件触发"""

    def __init__(self, max_consecutive_losses: int = 3, cooldown_bars: int = 10):
        self.max_losses = max_consecutive_losses
        self.cooldown_bars = cooldown_bars
        self.consecutive_losses = 0
        self.cooldown_remaining = 0
        self.tripped = False

    def record_trade(self, pnl: float):
        if self.tripped:
            self.cooldown_remaining -= 1
            if self.cooldown_remaining <= 0:
                self.tripped = False
                self.consecutive_losses = 0
                logger.info("Circuit breaker reset")

        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_losses:
                self.tripped = True
                self.cooldown_remaining = self.cooldown_bars
                logger.warning(
                    f"Circuit breaker tripped after {self.consecutive_losses} consecutive losses"
                )
        else:
            self.consecutive_losses = 0
