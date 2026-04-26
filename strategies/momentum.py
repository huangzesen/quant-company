"""
动量策略
- N日收益率排序
- 价格突破策略
- 趋势强度动量
"""
import pandas as pd
import numpy as np
from shared_lib.base_strategy import BaseStrategy, Signal
import ta


class PriceMomentum(BaseStrategy):
    """
    价格动量策略
    - N日涨幅超过 threshold → 做多
    - N日跌幅超过 threshold → 做空
    - 结合成交量过滤
    """

    def __init__(self, params: dict = None):
        default_params = {
            "momentum_period": 20,
            "entry_threshold": 0.05,   # 5%
            "exit_threshold": 0.02,    # 2%
            "volume_boost": True,
        }
        super().__init__({**(default_params), **(params or {})})
        self._name = "PriceMomentum"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        period = self.params["momentum_period"]

        # N日收益率
        returns = df["close"].pct_change(period)

        signals = pd.Series(0, index=df.index)

        # 强动量进入
        buy_entry = (returns > self.params["entry_threshold"])
        sell_entry = (returns < -self.params["entry_threshold"])

        # 动量衰减退出
        buy_exit = (returns < self.params["exit_threshold"])
        sell_exit = (returns > -self.params["exit_threshold"])

        # 成交量滤波
        if self.params["volume_boost"] and "volume" in df.columns:
            vol_ma = df["volume"].rolling(period).mean()
            high_vol = df["volume"] > vol_ma
            buy_entry = buy_entry & high_vol
            sell_entry = sell_entry & high_vol

        # 入场信号：只在新突破时
        signals[buy_entry & (~buy_entry.shift(1).fillna(False))] = 1
        signals[sell_entry & (~sell_entry.shift(1).fillna(False))] = -1

        return signals


class BreakoutStrategy(BaseStrategy):
    """
    突破策略
    - 价格突破近期最高/最低点
    - 结合 ATR 确认
    """

    def __init__(self, params: dict = None):
        default_params = {
            "lookback": 20,
            "atr_multiplier": 1.5,
            "atr_period": 14,
        }
        super().__init__({**(default_params), **(params or {})})
        self._name = "Breakout"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        lb = self.params["lookback"]
        atr = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], self.params["atr_period"]
        )

        roll_high = df["high"].rolling(lb).max().shift(1)
        roll_low = df["low"].rolling(lb).min().shift(1)

        signals = pd.Series(0, index=df.index)

        # 向上突破
        up_break = (df["close"] > roll_high) & (df["close"] > roll_high.shift(1))
        # 向下突破
        dn_break = (df["close"] < roll_low) & (df["close"] < roll_low.shift(1))

        # ATR 确认：突破幅度需超过 ATR 的 multiplier 倍
        atr_conf = (df["close"] - roll_high).abs() > atr * self.params["atr_multiplier"]
        up_break = up_break & (df["close"] - roll_high > atr * self.params["atr_multiplier"])
        dn_break = dn_break & (roll_low - df["close"] > atr * self.params["atr_multiplier"])

        signals[up_break] = 1
        signals[dn_break] = -1

        return signals
