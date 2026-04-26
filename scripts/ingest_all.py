#!/opt/anaconda3/bin/python3
"""批量数据采集与增量更新脚本
支持：日线/1h 级别，Yahoo 股票 + Kraken 加密币，增量追加
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
import pandas as pd
import logging
from datetime import datetime, timedelta
from pathlib import Path

from shared_lib.data_fetcher import (
    fetch_yahoo,
    list_local_data,
    load_local,
    CONFIG,
    DATA_ROOT,
    _ensure_ticker_dir,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest")

# ==============================
# 配置
# ==============================

STOCK_TICKERS = CONFIG["data"]["sources"]["yahoo"]["tickers"]

CCXT_SOURCES = {
    "kraken": ["BTC/USD", "ETH/USD"],
}

# 日内标的配置（扩展自父代指示）
INTRADAY_INTERVALS = ["1h"]
INTRADAY_LOOKBACK_DAYS = {
    "1h": 90,     # Yahoo 限制 ~90 天
}

# ==============================
# 股票：日线
# ==============================

def fetch_yahoo_daily(tickers=None, lookback_days=730):
    """增量采集 Yahoo 日线——已有数据则不重复拉取"""
    tickers = tickers or STOCK_TICKERS
    results = {}
    for t in tickers:
        existing = load_local(t)  # 已有数据
        end = datetime.now()
        start = end - timedelta(days=lookback_days)

        if existing is not None and not existing.empty:
            # 只补缺失区间
            existing_end = existing.index.max()
            if existing_end >= pd.Timestamp(end.tz_localize(existing.index.tz) if existing.index.tz else end):
                logger.info(f"✓ {t}: 已是最新 (共 {len(existing)} 行)")
                results[t] = existing
                continue
            # 从已有数据末尾之后开始拉
            fetch_start = existing_end + timedelta(days=1)
            logger.info(f"→ {t}: 已有 {len(existing)} 行, 补 {fetch_start.date()} 之后")
            df = fetch_yahoo(t, interval="1d", end=end, start=fetch_start)
            if df is not None and not df.empty:
                combined = pd.concat([existing, df])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                # 重新保存完整数据（覆盖旧文件）
                save_dir = _ensure_ticker_dir(t)
                fname = save_dir / f"{t}_1d_{fetch_start.date()}_{end.date()}.parquet"
                combined.to_parquet(fname)
                logger.info(f"✓ {t}: 合并后 {len(combined)} 行 → {fname}")
                results[t] = combined
            else:
                logger.info(f"✓ {t}: 无新数据")
                results[t] = existing
        else:
            df = fetch_yahoo(t, interval="1d", end=end, start=start)
            results[t] = df
            logger.info(f"✓ {t}: 首次采集 {len(df)} 行")
    return results


def fetch_yahoo_intraday(tickers=None, interval="1h", lookback_days=90):
    """采集 Yahoo 日内数据（1h）"""
    tickers = tickers or STOCK_TICKERS
    results = {}
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    for t in tickers:
        try:
            df = fetch_yahoo(t, interval=interval, end=end, start=start)
            if df is not None and not df.empty:
                # 文件名含 freq 以区分频次
                save_dir = _ensure_ticker_dir(t)
                fname = save_dir / f"{t}_{interval}_{start.date()}_{end.date()}.parquet"
                df.to_parquet(fname)
                results[t] = df
                logger.info(f"✓ {t} {interval}: {len(df)} 行 → {fname}")
            else:
                logger.info(f"○ {t} {interval}: 无数据")
        except Exception as e:
            logger.error(f"✗ {t} {interval}: {e}")
    return results


# ==============================
# 加密币
# ==============================

def fetch_crypto_daily(limit=500):
    """采集加密币日线"""
    import ccxt
    results = {}
    for exchange_name, symbols in CCXT_SOURCES.items():
        try:
            ex_class = getattr(ccxt, exchange_name)
            ex = ex_class()
            for symbol in symbols:
                try:
                    existing = load_local(symbol)
                    if existing is not None and not existing.empty:
                        existing_end = existing.index.max()
                        # Kraken 最多 720 条，补足
                        ohlcv = ex.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
                        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                        df.set_index("timestamp", inplace=True)
                        combined = pd.concat([existing, df])
                        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                        save_dir = _ensure_ticker_dir(symbol)
                        fname = save_dir / f"{symbol.replace('/', '_')}_1d_{datetime.now().date()}.parquet"
                        combined.to_parquet(fname)
                        results[symbol] = combined
                        logger.info(f"✓ {symbol}@{exchange_name}: 合并后 {len(combined)} 行")
                    else:
                        ohlcv = ex.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
                        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                        df.set_index("timestamp", inplace=True)
                        save_dir = _ensure_ticker_dir(symbol)
                        fname = save_dir / f"{symbol.replace('/', '_')}_1d_{datetime.now().date()}.parquet"
                        df.to_parquet(fname)
                        results[symbol] = df
                        logger.info(f"✓ {symbol}@{exchange_name}: 首次 {len(df)} 行")
                except Exception as e:
                    logger.error(f"✗ {symbol}@{exchange_name}: {e}")
        except Exception as e:
            logger.error(f"✗ Exchange {exchange_name}: {e}")
    return results


def fetch_crypto_intraday(interval="1h", limit=720):
    """采集加密币日内数据（1h）"""
    import ccxt
    results = {}
    for exchange_name, symbols in CCXT_SOURCES.items():
        try:
            ex_class = getattr(ccxt, exchange_name)
            ex = ex_class()
            for symbol in symbols:
                try:
                    ohlcv = ex.fetch_ohlcv(symbol, timeframe=interval, limit=limit)
                    df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                    df.set_index("timestamp", inplace=True)
                    save_dir = _ensure_ticker_dir(symbol)
                    fname = save_dir / f"{symbol.replace('/', '_')}_{interval}_{datetime.now().date()}.parquet"
                    df.to_parquet(fname)
                    results[symbol] = df
                    logger.info(f"✓ {symbol}@{exchange_name} {interval}: {len(df)} 行 → {fname}")
                except Exception as e:
                    logger.error(f"✗ {symbol}@{exchange_name} {interval}: {e}")
        except Exception as e:
            logger.error(f"✗ Exchange {exchange_name}: {e}")
    return results


# ==============================
# 数据质量检查
# ==============================

def run_quality_check(interval_tag="all"):
    """打印当前数据质量概览"""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"数据质量检查（{interval_tag}）")
    print(sep)

    dirs = sorted([d for d in DATA_ROOT.iterdir() if d.is_dir()])
    for d in dirs:
        ticker = d.name
        if interval_tag == "all":
            files = sorted(d.glob("*.parquet"))
        else:
            files = sorted(d.glob(f"*{interval_tag}*.parquet"))
        if not files:
            continue

        dfs = []
        for f in files:
            try:
                dfs.append(pd.read_parquet(f))
            except Exception as e:
                print(f"✗ {ticker}: {f.name} - {e}")
                continue
        if not dfs:
            continue

        combined = pd.concat(dfs)
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()

        # 解析频次标签
        freqs = set()
        for f in files:
            name_parts = f.stem.split("_")
            for p in name_parts:
                if p in ["1d", "1h", "15m", "5m", "1m"]:
                    freqs.add(p)

        print(f"\n【{ticker}】频次: {', '.join(sorted(freqs))}")
        print(f"  文件数: {len(files)} | 总行数: {len(combined)}")
        print(f"  日期: {combined.index.min()} ~ {combined.index.max()}")

        nulls = combined.isnull().sum().sum()
        print(f"  缺失值: {'无 ✓' if nulls == 0 else f'{nulls}个 ✗'}")

        if "close" in combined.columns:
            c = combined["close"].dropna()
            print(f"  收盘价: {c.min():.2f} ~ {c.max():.2f} (均值 {c.mean():.2f})")


def show_status():
    """打印数据概览"""
    sep = "=" * 60
    print(f"\n{sep}")
    print("数据状态概览")
    print(sep)
    print(f"{'标的':<12} {'文件数':<8} {'行数':<10} {'频次':<12}")
    print("-" * 60)

    all_tickers = set(STOCK_TICKERS + [s.replace("/", "_") for syms in CCXT_SOURCES.values() for s in syms])
    for t in sorted(all_tickers):
        files = list_local_data(t)
        if files:
            total_rows = 0
            freqs = set()
            for f in files:
                try:
                    total_rows += len(pd.read_parquet(f))
                    for p in f.stem.split("_"):
                        if p in ["1d", "1h", "15m", "5m", "1m"]:
                            freqs.add(p)
                except:
                    pass
            print(f"{t:<12} {len(files):<8} {total_rows:<10} {','.join(sorted(freqs)):<12}")
        else:
            print(f"{t:<12} {'无':<8}")


# ==============================
# 主入口
# ==============================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="灵台量化 — 批量数据采集与增量更新")
    parser.add_argument("--daily", action="store_true", help="采集日线（已增量）")
    parser.add_argument("--intraday", action="store_true", help="采集所有标的的 1h 数据")
    parser.add_argument("--all", action="store_true", help="采集全部日线 + 日内")
    parser.add_argument("--status", action="store_true", help="仅查看数据状态")
    parser.add_argument("--quality", choices=["daily", "intraday", "all"], nargs="?", const="all",
                        help="数据质量检查")
    parser.add_argument("--tickers", nargs="+", help="指定标的（可选，缺省则使用配置）")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    if args.quality:
        run_quality_check(args.quality)
        sys.exit(0)

    if args.all:
        args.daily = True
        args.intraday = True

    if args.daily:
        tickers = args.tickers or STOCK_TICKERS
        print(f"\n>>> 日线数据（Yahoo: {', '.join(tickers)}）...")
        fetch_yahoo_daily(tickers=tickers)
        print(f"\n>>> 加密币日线（Kraken）...")
        fetch_crypto_daily()

    if args.intraday:
        tickers = args.tickers or STOCK_TICKERS + ["GLD", "TLT"]
        print(f"\n>>> 日内数据 1h（Yahoo: {', '.join(tickers)}）...")
        fetch_yahoo_intraday(tickers=tickers, interval="1h")

        print(f"\n>>> 加密币 1h（Kraken）...")
        fetch_crypto_intraday(interval="1h")

    print(f"\n>>> 完成。")
    show_status()
