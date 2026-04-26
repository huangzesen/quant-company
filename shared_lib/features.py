"""
技术指标与特征工程
基于 ta-lib + 自定义指标
"""

import pandas as pd
import numpy as np
import ta

# ta 库提供常用技术指标，咱直接包装一层方便用

def add_all_indicators(df):
    """为一 DataFrame 添加全套常用技术指标"""
    df = df.copy()
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']

    # 均线
    df['sma_20'] = ta.trend.sma_indicator(c, 20)
    df['sma_50'] = ta.trend.sma_indicator(c, 50)
    df['sma_200'] = ta.trend.sma_indicator(c, 200)
    df['ema_12'] = ta.trend.ema_indicator(c, 12)
    df['ema_26'] = ta.trend.ema_indicator(c, 26)

    # MACD
    macd = ta.trend.MACD(c)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()

    # RSI
    df['rsi_14'] = ta.momentum.rsi(c, 14)

    # 布林带
    bb = ta.volatility.BollingerBands(c)
    df['bb_high'] = bb.bollinger_hband()
    df['bb_mid'] = bb.bollinger_mavg()
    df['bb_low'] = bb.bollinger_lband()
    df['bb_width'] = (df['bb_high'] - df['bb_low']) / df['bb_mid']

    # ATR（波动率）
    df['atr_14'] = ta.volatility.average_true_range(h, l, c, 14)

    # 成交量指标
    df['volume_sma_20'] = v.rolling(20).mean()
    df['volume_ratio'] = v / df['volume_sma_20']

    # OBV
    df['obv'] = ta.volume.on_balance_volume(c, v)

    # 价格变化率
    df['returns_1d'] = c.pct_change(1)
    df['returns_5d'] = c.pct_change(5)
    df['returns_20d'] = c.pct_change(20)
    df['log_return'] = np.log(c / c.shift(1))
    df['volatility_20d'] = df['returns_1d'].rolling(20).std()

    return df


def add_crypto_specific(df):
    """加密货币特有指标"""
    if 'close' not in df.columns:
        return df
    df = df.copy()
    c = df['close']
    
    # 币市常用的指标
    df['vwap'] = (df['close'] * df['volume']).rolling(20).sum() / df['volume'].rolling(20).sum()
    
    # 资金费率模拟（用价格偏离程度）
    df['funding_implied'] = (c - df['sma_20']) / df['sma_20']
    
    return df
