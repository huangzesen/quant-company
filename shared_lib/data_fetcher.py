"""
数据获取层
支持 yfinance（股票）、ccxt（加密货币）、alpaca（美股全量）
"""

import os
import yaml
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger("quant.data")

# 加载配置
_CONFIG_PATH = Path(__file__).parent.parent / "config/config.yaml"
with open(_CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

DATA_ROOT = Path(CONFIG["data"]["storage"]["path"])
FEATURES_ROOT = Path(CONFIG["data"]["storage"]["features_path"])


def _ensure_ticker_dir(ticker):
    """确保 ticker 的 raw 数据目录存在"""
    d = DATA_ROOT / ticker.replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_yahoo(ticker, start=None, end=None, interval=None):
    """
    从 Yahoo Finance 获取日线/分钟线数据
    返回 DataFrame: [Open, High, Low, Close, Volume]
    """
    import yfinance as yf

    interval = interval or CONFIG["data"]["frequency"]["default"]
    end = end or datetime.now()
    start = start or (end - timedelta(days=365 * 2))

    logger.info(f"Yahoo: fetching {ticker} {interval} from {start.date()} to {end.date()}")
    t = yf.Ticker(ticker)
    df = t.history(start=start, end=end, interval=interval)

    if df.empty:
        logger.warning(f"Yahoo: no data for {ticker}")
        return df

    df.columns = [c.lower() for c in df.columns]
    # 保存到本地
    save_dir = _ensure_ticker_dir(ticker)
    fname = save_dir / f"{ticker}_{interval}_{start.date()}_{end.date()}.parquet"
    df.to_parquet(fname)
    logger.info(f"Saved {len(df)} rows → {fname}")
    return df


def fetch_ccxt(symbol, exchange="binance", timeframe="1d", limit=500, sandbox=None):
    """
    从 ccxt（加密货币交易所）获取数据
    """
    import ccxt

    sandbox = sandbox if sandbox is not None else CONFIG["data"]["sources"]["ccxt"].get("sandbox", True)

    exchange_class = getattr(ccxt, exchange)
    ex = exchange_class({
        "sandbox": sandbox,
    })

    logger.info(f"CCXT: fetching {symbol} {timeframe} from {exchange}")
    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    save_dir = _ensure_ticker_dir(symbol)
    fname = save_dir / f"{symbol.replace('/', '_')}_{timeframe}_{datetime.now().date()}.parquet"
    df.to_parquet(fname)
    logger.info(f"Saved {len(df)} rows → {fname}")
    return df


def add_yield_proxy(df, ticker):
    """为国债ETF添加收益率近似（price⁻¹ 作为利率趋势标记）"""
    df = df.copy()
    if ticker.upper() == "TLT" and "close" in df.columns:
        # TLT 为20年期国债ETF，价格与收益率反向
        # 近似：inv_yield = coupon_rate / price * 100
        # TLT 平均票息约 2.5-3.0%
        df["inv_yield"] = 2.75 / df["close"] * 100
        # 加趋势标记：较20日均值上行/下行
        df["yield_trend"] = df["inv_yield"] - df["inv_yield"].rolling(20).mean()
    return df


def load_local(ticker, interval=None, use_features=True):
    """
    加载本地数据

    参数
    ----
    ticker : str — 标的名称（如 'SPY', 'BTC_USD'）
    interval : str or None — 频次（如 '1d', '1h'），None=自动
    use_features : bool — True=加载特征，False=加载原始OHLCV

    返回
    ----
    pd.DataFrame
    """
    if use_features:
        return _load_features(ticker, interval)

    return _load_raw(ticker, interval)


# ====================
# 内部加载函数
# ====================

def _load_raw(ticker, interval=None):
    """加载原始 OHLCV 数据"""
    files = list_local_data(ticker)
    if not files:
        logger.warning(f"No local data for {ticker}")
        return pd.DataFrame()

    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"  skip {f}: {e}")
            continue

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    # 按频次过滤
    if interval:
        if interval == "1d":
            # 对日频，用 resample 过滤日内
            res = combined.resample("D").last().dropna()
            combined = res if len(res) > 0 else combined
        elif interval == "1h":
            res = combined.resample("h").last().dropna()
            combined = res if len(res) > 0 else combined

    return combined


def _load_features(ticker, interval=None):
    """加载特征数据"""
    ticker_dir = ticker.replace("/", "_")
    feat_dir = FEATURES_ROOT / ticker_dir
    if not feat_dir.exists():
        logger.info(f"No features for {ticker}, falling back to raw")
        return _load_raw(ticker, interval)

    # 全部特征文件
    files = sorted(feat_dir.glob("*.parquet"))

    # 按频次过滤：默认优先 1d
    if interval is None:
        # 先找 1d，没有则全取
        day_files = [f for f in files if "1d_features" in f.name]
        files = day_files if day_files else files
    else:
        files = [f for f in files if f"{interval}_features" in f.name]

    if not files:
        logger.info(f"No {interval or '1d'} features for {ticker}, falling back to raw")
        return _load_raw(ticker, interval)

    # 加载最新（最后一个）特征文件
    latest = files[-1]
    try:
        df = pd.read_parquet(latest)
        logger.info(f"Loaded features: {latest.name} ({len(df)} rows)")
        return df
    except Exception as e:
        logger.warning(f"Failed to load features {latest}: {e}")
        return _load_raw(ticker, interval)


def list_local_data(ticker=None):
    """列出本地已有的数据文件"""
    data_path = DATA_ROOT
    if ticker:
        data_path = data_path / ticker.replace("/", "_")
    
    if not data_path.exists():
        return []
    return sorted([str(p) for p in data_path.glob("*.parquet")])
