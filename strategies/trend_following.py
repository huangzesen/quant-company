"""
趋势跟踪策略
- 双均线交叉 (EMA 12/26)
- 三均线系统 (SMA 20/50/200)
- ADX 滤波
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
from shared_lib.base_strategy import BaseStrategy, Signal
import ta


class EMA_Crossover(BaseStrategy):
    """
    双指数均线交叉策略
    - 快线 EMA_short 上穿慢线 EMA_long → 做多
    - 快线下穿慢线 → 平仓/做空
    """

    def __init__(self, params: dict = None):
        default_params = {
            "ema_short": 12,
            "ema_long": 26,
            "use_adx_filter": True,
            "adx_threshold": 25,
            "adx_period": 14,
        }
        super().__init__({**(default_params), **(params or {})})
        self._name = "EMA_Crossover"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        short = self.params["ema_short"]
        long = self.params["ema_long"]

        ema_short = ta.trend.ema_indicator(df["close"], short)
        ema_long = ta.trend.ema_indicator(df["close"], long)

        # 交叉信号
        crossover = (ema_short > ema_long) & (ema_short.shift(1) <= ema_long.shift(1))
        crossunder = (ema_short < ema_long) & (ema_short.shift(1) >= ema_long.shift(1))

        signals = pd.Series(0, index=df.index)
        signals[crossover] = 1
        signals[crossunder] = -1

        # ADX 滤波：只在趋势足够强时交易
        if self.params["use_adx_filter"]:
            adx = ta.trend.adx(df["high"], df["low"], df["close"], self.params["adx_period"])
            signals[(adx < self.params["adx_threshold"])] = 0

        return signals


class TripleMA_Crossover(BaseStrategy):
    """
    三均线趋势系统
    - fast > mid > slow → 多头趋势 → 做多
    - fast < mid < slow → 空头趋势 → 做空
    """

    def __init__(self, params: dict = None):
        default_params = {
            "fast": 10,
            "mid": 30,
            "slow": 60,
        }
        super().__init__({**(default_params), **(params or {})})
        self._name = "TripleMA_Crossover"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        f = self.params["fast"]
        m = self.params["mid"]
        s = self.params["slow"]

        sma_fast = ta.trend.sma_indicator(df["close"], f)
        sma_mid = ta.trend.sma_indicator(df["close"], m)
        sma_slow = ta.trend.sma_indicator(df["close"], s)

        # 排列状态
        bullish = (sma_fast > sma_mid) & (sma_mid > sma_slow)
        bearish = (sma_fast < sma_mid) & (sma_mid < sma_slow)

        signals = pd.Series(0, index=df.index)
        signals[(bullish) & (~bullish.shift(1).fillna(False))] = 1
        signals[(bearish) & (~bearish.shift(1).fillna(False))] = -1

        return signals
