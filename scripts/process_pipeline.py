#!/opt/anaconda3/bin/python3
"""
数据清洗管道 — 时间轴对齐 + Split/Dividend 调整
输出至 data/processed/{TICKER}/{TICKER}_{freq}_clean.parquet

用法:
  python3 scripts/process_pipeline.py --all       # 全部标的
  python3 scripts/process_pipeline.py --daily     # 仅日线
  python3 scripts/process_pipeline.py --intraday  # 仅日内
  python3 scripts/process_pipeline.py --status    # 查看清洗状态
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import logging
from pathlib import Path
from datetime import datetime, timedelta
from pandas.tseries.offsets import CustomBusinessDay
from pandas.tseries.holiday import USFederalHolidayCalendar

from shared_lib.data_fetcher import load_local, CONFIG, DATA_ROOT, _ensure_ticker_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("process")

RAW_ROOT = DATA_ROOT
PROCESSED_ROOT = Path(CONFIG["data"]["storage"]["processed_path"])

# 美股日历
us_cal = CustomBusinessDay(calendar=USFederalHolidayCalendar())

# 核心标的
STOCKS = ["SPY", "QQQ", "IWM", "GLD", "TLT", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
CRYPTO = ["BTC_USD", "ETH_USD"]


def adjust_splits_dividends(df, ticker):
    """
    后复权处理：用 split/dividend 列调整价格
    Yahoo 返回的 'stock splits' 是乘数（如 5→1拆股，值为0.2），
    'dividends' 是每股现金分红。
    """
    df = df.copy()

    if "stock splits" in df.columns:
        # 将 split 因子累积 → 后复权因子
        split_factor = (1 / (1 - df["stock splits"] + 1e-10)).clip(
            upper=10, lower=0.1
        )
        cum_split = split_factor.cumprod()

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col] * cum_split
        if "volume" in df.columns:
            df["volume"] = (df["volume"] / cum_split).fillna(0).astype(int)

    if "dividends" in df.columns and df["dividends"].abs().sum() > 0:
        # 简单后复权：累积分红加到价格中
        cum_div = df["dividends"].cumsum()
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col] + cum_div

    return df


def align_timeline(df, ticker, interval="1d"):
    """将数据对齐到统一时间轴"""
    if df.empty:
        return df

    if interval == "1d":
        # 日线对齐：正常排序去重即可
        result = df.sort_index()
        result = result[~result.index.duplicated(keep="last")]
        return result

    elif interval == "1h":
        if ticker in CRYPTO:
            full_idx = pd.date_range(
                start=df.index.min().floor("h"),
                end=df.index.max().ceil("h"),
                freq="h",
                tz="UTC",
            )
        else:
            # 美股 1h：仅交易时段 9:30~16:00 ET
            full_idx = pd.date_range(
                start=df.index.min().floor("h"),
                end=df.index.max().ceil("h"),
                freq="h",
                tz=df.index.tz if df.index.tz else "America/New_York",
            )
        result = df.reindex(full_idx)
        # 非交易时段 forward fill 6h 内，其余保留 NaN
        result = result.ffill(limit=6)

    else:
        result = df.sort_index()

    return result


def process_one(ticker, interval="1d", force=False):
    """清洗单个标的单个频次"""
    logger.info(f"Processing {ticker} {interval}...")

    # 加载原始数据
    raw = load_local(ticker, use_features=False)
    if raw.empty:
        logger.warning(f"  {ticker}: 无原始数据")
        return None

    # 按频次筛选
    if interval == "1d":
        data = raw.resample("D").last().dropna(how="all")
    elif interval == "1h":
        # 过滤 1h 频次：文件名含 1h
        files = sorted((RAW_ROOT / ticker).glob("*1h*.parquet"))
        if not files:
            logger.warning(f"  {ticker}: 无 {interval} 数据")
            return None
        dfs = [pd.read_parquet(f) for f in files]
        data = pd.concat(dfs)
        data = data[~data.index.duplicated(keep="last")].sort_index()
    else:
        logger.warning(f"  {ticker}: 不支持频次 {interval}")
        return None

    if data.empty:
        return None

    # 1. split/dividend 调整
    data = adjust_splits_dividends(data, ticker)
    logger.info(f"  Split/dividend 调整后: {len(data)} 行")

    # 2. 时间轴对齐
    data = align_timeline(data, ticker, interval=interval)
    logger.info(f"  时间轴对齐后: {len(data)} 行")

    # 3. 去除全 NaN 行
    data = data.dropna(how="all")
    logger.info(f"  去除全空后: {len(data)} 行")

    # 保存
    save_dir = PROCESSED_ROOT / ticker
    save_dir.mkdir(parents=True, exist_ok=True)
    fname = save_dir / f"{ticker}_{interval}_clean.parquet"
    data.to_parquet(fname)
    logger.info(f"  ✓ 保存: {fname} ({len(data)} 行, {len(data.columns)} 列)")
    return data


def process_all(intervals=None):
    """清洗全部标的"""
    intervals = intervals or ["1d"]

    # 日线
    if "1d" in intervals:
        for t in STOCKS + CRYPTO:
            try:
                process_one(t, interval="1d")
            except Exception as e:
                logger.error(f"✗ {t} 1d: {e}")

    # 日内
    if "1h" in intervals:
        for t in ["SPY", "GLD", "TLT"] + CRYPTO:
            try:
                process_one(t, interval="1h")
            except Exception as e:
                logger.error(f"✗ {t} 1h: {e}")


def show_status():
    """查看清洗数据状态"""
    sep = "=" * 60
    print(f"\n{sep}")
    print("清洗数据（processed/）状态")
    print(sep)
    print(f"{'标的':<12} {'频次':<8} {'行数':<10} {'列数':<8}")
    print("-" * 60)

    if not PROCESSED_ROOT.exists():
        print("processed 目录不存在")
        return

    for d in sorted(PROCESSED_ROOT.iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.parquet")):
            try:
                df = pd.read_parquet(f)
                freq = "1d" if "1d" in f.name else ("1h" if "1h" in f.name else "?")
                print(f"{d.name:<12} {freq:<8} {len(df):<10} {len(df.columns):<8}")
            except Exception as e:
                print(f"{d.name:<12} {'读取失败':<20}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="数据清洗管道")
    parser.add_argument("--daily", action="store_true", help="清洗日线")
    parser.add_argument("--intraday", action="store_true", help="清洗1h数据")
    parser.add_argument("--all", action="store_true", help="清洗全部")
    parser.add_argument("--status", action="store_true", help="查看清洗状态")
    parser.add_argument("--ticker", help="指定标的")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    if args.all:
        process_all(intervals=["1d", "1h"])
    elif args.daily:
        process_all(intervals=["1d"])
    elif args.intraday:
        process_all(intervals=["1h"])
    elif args.ticker:
        process_one(args.ticker, interval="1d")
        process_one(args.ticker, interval="1h")
    else:
        process_all(intervals=["1d"])  # 默认日线

    print("\n>>> 完成。")
    show_status()
