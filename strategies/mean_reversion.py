"""
均值回归策略
- RSI 超买超卖
- 布林带回归
- 价格偏离均线
"""
import pandas as pd
import numpy as np
from shared_lib.base_strategy import BaseStrategy, Signal
import ta


class RSIMeanReversion(BaseStrategy):
    """
    RSI 均值回归
    - RSI < oversold → 做多
    - RSI > overbought → 做空
    """

    def __init__(self, params: dict = None):
        default_params = {
            "rsi_period": 14,
            "oversold": 30,
            "overbought": 70,
            "bb_filter": True,   # 结合布林带过滤
        }
        super().__init__({**(default_params), **(params or {})})
        self._name = "RSI_MeanReversion"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = ta.momentum.rsi(df["close"], self.params["rsi_period"])
        oversold = self.params["oversold"]
        overbought = self.params["overbought"]

        signals = pd.Series(0, index=df.index)

        # 从超卖区域反弹 → 做多
        buy_signal = (rsi > oversold) & (rsi.shift(1) <= oversold)
        # 从超买区域回调 → 做空
        sell_signal = (rsi < overbought) & (rsi.shift(1) >= overbought)

        if self.params["bb_filter"]:
            # 只在价格触及或超出布林带时交易
            bb = ta.volatility.BollingerBands(df["close"])
            bb_low = bb.bollinger_lband()
            bb_high = bb.bollinger_hband()
            buy_signal = buy_signal & (df["close"] <= bb_low)
            sell_signal = sell_signal & (df["close"] >= bb_high)

        signals[buy_signal] = 1
        signals[sell_signal] = -1

        return signals


class BollingerBandsReversion(BaseStrategy):
    """
    布林带均值回归（v2.0 泛化版）
    - 价格触及下轨 + 偏离中轨过大 → 做多
    - 价格触及上轨 + 偏离中轨过大 → 做空
    - v2.0 新增：ADX趋势过滤（震荡市启用，趋势市禁用）
              双阈值仓位控制（-2σ轻仓，-2.5σ加仓）
    """

    def __init__(self, params: dict = None):
        default_params = {
            "bb_period": 20,
            "bb_std": 2.0,
            "confirmation_volume": True,  # 成交量确认
            "use_adx_filter": False,      # ADX趋势过滤
            "adx_threshold": 25,          # ADX < 此值时允许交易
            "adx_period": 14,             # ADX 计算周期
            "dual_threshold": False,      # 双阈值模式
            "bb_std_heavy": 2.5,          # 加仓阈值
        }
        super().__init__({**(default_params), **(params or {})})
        self._name = "BB_Reversion"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        bb = ta.volatility.BollingerBands(
            df["close"],
            window=self.params["bb_period"],
            window_dev=self.params["bb_std"],
        )
        bb_low = bb.bollinger_lband()
        bb_high = bb.bollinger_hband()
        bb_mid = bb.bollinger_mavg()

        signals = pd.Series(0, index=df.index)

        # ADX 过滤：只在震荡市中交易
        allow_trade = pd.Series(True, index=df.index)
        if self.params["use_adx_filter"]:
            adx = ta.trend.adx(df["high"], df["low"], df["close"], self.params["adx_period"])
            allow_trade = adx < self.params["adx_threshold"]

        # 基础信号：价格触轨
        touch_lower = df["close"] <= bb_low
        touch_higher = df["close"] >= bb_high

        buy_signal = touch_lower & (df["close"].shift(1) > bb_low.shift(1))
        sell_signal = touch_higher & (df["close"].shift(1) < bb_high.shift(1))

        # 双阈值模式：深触(-2.5σ)加仓信号更强
        if self.params["dual_threshold"]:
            bb_heavy = ta.volatility.BollingerBands(
                df["close"],
                window=self.params["bb_period"],
                window_dev=self.params["bb_std_heavy"],
            )
            bb_low_heavy = bb_heavy.bollinger_lband()
            bb_high_heavy = bb_heavy.bollinger_hband()

            # 深触重仓区 → 置信度更高
            heavy_buy = df["close"] <= bb_low_heavy
            heavy_sell = df["close"] >= bb_high_heavy

            # 双阈值叠加
            buy_signal = buy_signal | (heavy_buy & allow_trade)
            sell_signal = sell_signal | (heavy_sell & allow_trade)

        # 成交量确认
        if self.params["confirmation_volume"] and "volume" in df.columns:
            volume_ma = df["volume"].rolling(20).mean()
            buy_signal = buy_signal & (df["volume"] > volume_ma * 0.8)
            sell_signal = sell_signal & (df["volume"] > volume_ma * 0.8)

        signals[buy_signal & allow_trade] = 1
        signals[sell_signal & allow_trade] = -1

        return signals
