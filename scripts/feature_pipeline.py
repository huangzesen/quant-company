#!/opt/anaconda3/bin/python3
"""
特征工程管道 — 预计算技术指标，按标的分层存储为 Parquet
调用: python3 scripts/feature_pipeline.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import logging
from pathlib import Path
from datetime import datetime

from shared_lib.data_fetcher import load_local, CONFIG
from shared_lib.features import add_all_indicators, add_crypto_specific
from shared_lib.data_fetcher import add_yield_proxy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("features")

FEATURES_ROOT = Path("data/features")
FREQUENCY_TAG = "1d"  # 当前仅日线

# 核心标的（父代确认）
CORE_TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "AMZN", "NVDA"]

# 扩展标的
EXTRA_TICKERS = ["GLD", "TLT", "MSFT", "GOOGL"]
CRYPTO_TICKERS = ["BTC_USD", "ETH_USD"]

# 日内标的配置（1h）
CORE_1H_TICKERS = ["SPY", "BTC_USD"]


def compute_and_save(ticker, df):
    """对单个标的计算特征并保存"""
    if df.empty:
        logger.warning(f"{ticker}: 无数据")
        return None

    # 计算特征
    result = add_all_indicators(df)

    # 加密币添加特有指标
    if ticker in CRYPTO_TICKERS:
        result = add_crypto_specific(result)

    # 国债ETF添加收益率代理列
    if ticker == "TLT":
        result = add_yield_proxy(result, ticker)

    # 保存
    save_dir = FEATURES_ROOT / ticker
    save_dir.mkdir(parents=True, exist_ok=True)
    fname = save_dir / f"{ticker}_{FREQUENCY_TAG}_features_{datetime.now().date()}.parquet"
    result.to_parquet(fname)

    # 信息
    col_count = len(result.columns)
    raw_cols = len(df.columns)
    feature_cols = [c for c in result.columns if c not in df.columns]

    logger.info(f"✓ {ticker}: {len(result)} 行 x {col_count} 列 "
                f"(原始 {raw_cols} + 特征 {len(feature_cols)}) → {fname}")
    return result


def main(tickers=None, hours=False):
    """主入口"""
    tickers = tickers or CORE_TICKERS

    results = {}
    for t in tickers:
        try:
            # 加载原始数据（不加载特征，因要重新计算）
            df = load_local(t, use_features=False)
            if df.empty:
                logger.warning(f"{t}: 本地无数据")
                continue

            if not hours:
                # 日线特征：按日期去重，保留日频
                df_daily = df[~df.index.duplicated(keep="last")]
                res = df_daily.resample('D').last().dropna()
                df_daily = res if len(res) > 0 else df_daily
                result = compute_and_save(t, df_daily)
            else:
                # 日内特征计算
                result = compute_and_save(t, df)
            if result is not None:
                results[t] = result
        except Exception as e:
            logger.error(f"✗ {t}: {e}")
            import traceback
            traceback.print_exc()

    return results


def main_intraday(tickers=None):
    """日内特征主入口"""
    tickers = tickers or CORE_1H_TICKERS
    global FREQUENCY_TAG
    FREQUENCY_TAG = "1h"

    from shared_lib.data_fetcher import DATA_ROOT

    results = {}
    for t in tickers:
        try:
            dir_path = DATA_ROOT / t
            if not dir_path.exists():
                logger.warning(f"{t}: 原始数据目录不存在")
                continue
            # 只加载1h文件
            files = sorted(dir_path.glob("*1h*.parquet"))
            if not files:
                logger.warning(f"{t}: 无1h数据")
                continue

            dfs = [pd.read_parquet(f) for f in files]
            df = pd.concat(dfs)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            logger.info(f"{t} 1h: 已加载 {len(df)} 行")

            result = compute_and_save(t, df)
            if result is not None:
                results[t] = result
        except Exception as e:
            logger.error(f"✗ {t} 1h: {e}")
            import traceback
            traceback.print_exc()

    return results


def show_status():
    """打印特征数据状态"""
    sep = "=" * 60
    print(f"\n{sep}")
    print("特征数据状态")
    print(sep)
    print(f"{'标的':<12} {'文件数':<8} {'行数':<10} {'特征列数':<10}")
    print("-" * 60)

    if not FEATURES_ROOT.exists():
        print("特征目录不存在")
        return

    for d in sorted(FEATURES_ROOT.iterdir()):
        if not d.is_dir():
            continue
        files = sorted(d.glob("*.parquet"))
        if not files:
            continue
        try:
            df = pd.read_parquet(files[-1])  # 最新文件
            print(f"{d.name:<12} {len(files):<8} {len(df):<10} {len(df.columns):<10}")
        except:
            print(f"{d.name:<12} {len(files):<8} {'读取失败':<10}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="灵台量化 — 特征工程管道")
    parser.add_argument("--all", action="store_true", help="核心+扩展+加密币（日线）")
    parser.add_argument("--core", action="store_true", help="仅核心6标的（日线）")
    parser.add_argument("--intraday", action="store_true", help="日内1h特征（SPY, BTC）")
    parser.add_argument("--status", action="store_true", help="查看特征数据状态")
    parser.add_argument("--hours", action="store_true", help="含日内数据（实验性）")
    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    if args.intraday:
        tickers = CORE_1H_TICKERS
        print(f">>> 日内特征工程 {tickers}...")
        results = main_intraday(tickers=tickers)
        print(f"\n>>> 完成。{len(results)}/{len(tickers)} 个标的日内特征已计算。")
        if results:
            print(f"\n{'标的':<12} {'行数':<8} {'特征列':<10}")
            print("-" * 30)
            for t, df in results.items():
                print(f"{t:<12} {len(df):<8} {len(df.columns):<10}")
        sys.exit(0)

    if args.all:
        tickers = CORE_TICKERS + EXTRA_TICKERS + CRYPTO_TICKERS
    elif args.core:
        tickers = CORE_TICKERS
    else:
        tickers = CORE_TICKERS  # 默认核心

    print(f">>> 特征工程 {'全部' if args.all else '核心6标的'}...")
    results = main(tickers=tickers, hours=args.hours)
    print(f"\n>>> 完成。{len(results)}/{len(tickers)} 个标的特征已计算。")

    # 打印摘要
    if results:
        print(f"\n{'标的':<12} {'行数':<8} {'特征列':<10}")
        print("-" * 30)
        for t, df in results.items():
            print(f"{t:<12} {len(df):<8} {len(df.columns):<10}")
