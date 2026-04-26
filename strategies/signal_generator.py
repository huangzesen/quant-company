"""
信号生成器 — 按日生成交易信号供 execution_agent 使用

信号格式（JSON）：
{
    "strategy": "BB_Reversion",
    "version": "1.0",
    "generated_at": "2026-04-25T19:30:00Z",
    "signals": [
        {
            "ticker": "SPY",
            "direction": 1,        # 1=做多, -1=做空, 0=平仓/无操作
            "confidence": 0.85,    # 0.0 ~ 1.0
            "entry_price": 713.94, # 信号生成时的最新收盘价（参考）
            "reason": "close_touched_lower_band",
            "metadata": {
                "bb_lower": 680.0,
                "bb_upper": 740.0,
                "bb_mid": 710.0,
                "atr": 8.5,
            }
        }
    ]
}
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.mean_reversion import BollingerBandsReversion
from strategies.trend_following import EMA_Crossover
from shared_lib.data_fetcher import load_local

logger = logging.getLogger("quant.signal")


SIGNAL_DIR = Path(__file__).parent.parent / "signals"
SIGNAL_DIR.mkdir(exist_ok=True)


def generate_bb_signal(ticker: str = "SPY", params: dict = None) -> dict:
    """
    根据最新数据生成 BB_Reversion 信号

    返回结构化信号字典，可直接 json.dumps 传给 execution_agent
    """
    if params is None:
        params = {"bb_period": 15, "bb_std": 2.5, "confirmation_volume": False}

    # 读取最新数据（至少60天的窗口计算指标）
    df = load_local(ticker)
    if df.empty:
        logger.error(f"No data for {ticker}")
        return {"error": f"No data for {ticker}"}

    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()

    # 确保数据够用
    if len(df) < 60:
        logger.warning(f"{ticker}: only {len(df)} rows, may be insufficient")

    # 运行策略
    strat = BollingerBandsReversion(params=params)
    signals = strat.generate_signals(df)

    # 取最新一个信号
    last_sig_idx = signals[signals != 0].index
    latest_date = df.index[-1]
    latest_close = df["close"].iloc[-1]

    result_signals = []

    # 如果最近有信号
    if len(last_sig_idx) > 0 and last_sig_idx[-1] >= df.index[-5]:
        sig_date = last_sig_idx[-1]
        sig_val = signals.loc[sig_date]

        # 获取当日的布林带数据用于元数据
        import ta
        bb = ta.volatility.BollingerBands(
            df["close"],
            window=params["bb_period"],
            window_dev=params["bb_std"],
        )
        bb_lower = bb.bollinger_lband()
        bb_upper = bb.bollinger_hband()
        bb_mid = bb.bollinger_mavg()
        atr = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], 14
        )

        close_at_sig = df.loc[sig_date, "close"]
        bb_l_at_sig = bb_lower.loc[sig_date]
        bb_u_at_sig = bb_upper.loc[sig_date]
        bb_m_at_sig = bb_mid.loc[sig_date]

        # 置信度：基于偏离程度
        if sig_val == 1:
            deviation = (bb_m_at_sig - close_at_sig) / (bb_m_at_sig - bb_l_at_sig + 1e-10)
            confidence = min(1.0, max(0.5, deviation))
            reason = "close_touched_lower_band"
        else:
            deviation = (close_at_sig - bb_m_at_sig) / (bb_u_at_sig - bb_m_at_sig + 1e-10)
            confidence = min(1.0, max(0.5, deviation))
            reason = "close_touched_upper_band"

        result_signals.append({
            "ticker": ticker,
            "direction": int(sig_val),
            "confidence": round(confidence, 2),
            "signal_date": str(sig_date.date()),
            "entry_price": round(float(close_at_sig), 2),
            "reason": reason,
            "metadata": {
                "bb_lower": round(float(bb_l_at_sig), 2),
                "bb_upper": round(float(bb_u_at_sig), 2),
                "bb_mid": round(float(bb_m_at_sig), 2),
                "atr_14": round(float(atr.loc[sig_date]), 2),
            }
        })

    # 当前位置：是否在持仓中
    pos = signals.iloc[-1] if len(signals) > 0 else 0

    output = {
        "strategy": "BB_Reversion",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_price": round(float(latest_close), 2),
        "last_date": str(latest_date.date()),
        "current_position": int(pos),
        "signals": result_signals,
    }

    return output


def generate_ema_signal(ticker: str = "SPY") -> dict:
    """EMA_Crossover 信号"""
    df = load_local(ticker)
    if df.empty:
        return {"error": f"No data for {ticker}"}

    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()

    strat = EMA_Crossover()
    signals = strat.generate_signals(df)
    last_sig_idx = signals[signals != 0].index
    latest_close = df["close"].iloc[-1]
    pos = signals.iloc[-1] if len(signals) > 0 else 0

    result_signals = []
    if len(last_sig_idx) > 0 and last_sig_idx[-1] >= df.index[-5]:
        sig_date = last_sig_idx[-1]
        sig_val = signals.loc[sig_date]

        import ta
        ema_short = ta.trend.ema_indicator(df["close"], 12)
        ema_long = ta.trend.ema_indicator(df["close"], 26)

        result_signals.append({
            "ticker": ticker,
            "direction": int(sig_val),
            "confidence": 0.6,
            "signal_date": str(sig_date.date()),
            "entry_price": round(float(df.loc[sig_date, "close"]), 2),
            "reason": "ema_crossover",
            "metadata": {
                "ema_12": round(float(ema_short.loc[sig_date]), 2),
                "ema_26": round(float(ema_long.loc[sig_date]), 2),
            }
        })

    return {
        "strategy": "EMA_Crossover",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_price": round(float(latest_close), 2),
        "current_position": int(pos),
        "signals": result_signals,
    }


def playback_test(ticker: str = "SPY", days: int = 20) -> dict:
    """
    回放测试：从最后 days 天往前推，检查信号生成链路的正确性
    """
    df = load_local(ticker)
    if df.empty:
        return {"error": f"No data for {ticker}"}

    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()

    results = []
    for i in range(min(days, len(df) - 60)):
        # 只用到第 i 天为止的数据
        data_slice = df.iloc[:len(df) - days + i] if i < days else df

        strat = BollingerBandsReversion(params={
            "bb_period": 15, "bb_std": 2.5, "confirmation_volume": False
        })
        sigs = strat.generate_signals(data_slice)

        if not sigs.empty:
            last_sig = sigs.iloc[-1]
            last_close = data_slice["close"].iloc[-1]
            results.append({
                "date": str(data_slice.index[-1].date()),
                "close": round(float(last_close), 2),
                "signal": int(last_sig) if last_sig != 0 else 0,
                "position": int(last_sig),
            })

    return {
        "ticker": ticker,
        "playback_days": days,
        "results": results[-days:],  # 只返回最后 days 天
        "summary": {
            "total_signals": sum(1 for r in results if r["signal"] != 0),
            "long_signals": sum(1 for r in results if r["signal"] == 1),
            "short_signals": sum(1 for r in results if r["signal"] == -1),
        }
    }


def save_signal(signal: dict, filename: str = None):
    """将信号保存到 signals/ 目录供 execution_agent 读取"""
    if filename is None:
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"signal_{signal['strategy']}_{dt}.json"
    path = SIGNAL_DIR / filename
    with open(path, "w") as f:
        json.dump(signal, f, indent=2, default=str)
    logger.info(f"Signal saved: {path}")
    return str(path)
