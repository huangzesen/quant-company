"""
报告与可视化模块
绩效报告、风险报告、图表生成
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
import json
from datetime import datetime
import logging

logger = logging.getLogger("quant.report")

REPORT_DIR = Path(__file__).parent.parent / "reports"


def _ensure_dir():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def equity_curve(trades: pd.DataFrame) -> pd.Series:
    """从交易记录生成权益曲线"""
    if trades.empty:
        return pd.Series(dtype=float)
    
    daily_pnl = trades.set_index("exit_time")["pnl"].resample("1D").sum()
    equity = (1 + daily_pnl).cumprod()
    equity.iloc[0] = 1.0
    return equity


def calculate_metrics(equity: pd.Series, trades: pd.DataFrame) -> dict:
    """计算绩效指标"""
    if equity.empty or len(equity) < 2:
        return {}

    total_return = equity.iloc[-1] - 1
    days = (equity.index[-1] - equity.index[0]).days or 1
    annual_return = (1 + total_return) ** (365 / days) - 1

    daily_returns = equity.pct_change().dropna()
    sharpe = np.sqrt(252) * daily_returns.mean() / (daily_returns.std() + 1e-10)

    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    max_dd = dd.min()
    
    # 交易统计
    if not trades.empty:
        win_rate = (trades["pnl"] > 0).mean()
        avg_win = trades.loc[trades["pnl"] > 0, "pnl"].mean() if (trades["pnl"] > 0).any() else 0
        avg_loss = trades.loc[trades["pnl"] < 0, "pnl"].mean() if (trades["pnl"] < 0).any() else 0
        profit_factor = (trades.loc[trades["pnl"] > 0, "pnl"].sum() /
                        max(abs(trades.loc[trades["pnl"] < 0, "pnl"].sum()), 1e-10))
        total_trades = len(trades)
    else:
        win_rate = avg_win = avg_loss = profit_factor = total_trades = 0

    metrics = {
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 4) if avg_win else 0,
        "avg_loss": round(avg_loss, 4) if avg_loss else 0,
        "profit_factor": round(profit_factor, 2),
        "total_trades": total_trades,
        "calmar_ratio": round(annual_return / max(abs(max_dd), 0.01), 2),
    }
    return metrics


def plot_equity_curve(equity: pd.Series, title: str = "Equity Curve", save_path: str = None):
    """绘制权益曲线"""
    _ensure_dir()
    fig, ax = plt.subplots(figsize=(12, 6))
    
    ax.plot(equity.index, equity.values, linewidth=1.5, color="#2196F3")
    ax.fill_between(equity.index, equity.values, alpha=0.1, color="#2196F3")
    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title(title, fontsize=14)
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.3)
    
    if save_path is None:
        save_path = str(REPORT_DIR / f"equity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    logger.info(f"Plot saved: {save_path}")
    return save_path


def plot_drawdown(equity: pd.Series, save_path: str = None):
    """绘制回撤图"""
    _ensure_dir()
    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.fill_between(dd.index, dd.values * 100, 0, alpha=0.3, color="#f44336")
    ax.plot(dd.index, dd.values * 100, color="#f44336", linewidth=1)
    ax.set_title("Drawdown", fontsize=12)
    ax.set_ylabel("Drawdown %")
    ax.grid(True, alpha=0.3)
    
    if save_path is None:
        save_path = str(REPORT_DIR / f"dd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    return save_path


def generate_report(metrics: dict, save: bool = True) -> str:
    """生成 Markdown 格式的绩效报告"""
    _ensure_dir()
    
    lines = []
    lines.append("# 量化策略绩效报告\n")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    
    labels = {
        "total_return": "总收益率",
        "annual_return": "年化收益率",
        "sharpe_ratio": "夏普比率",
        "max_drawdown": "最大回撤",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
        "total_trades": "总交易次数",
        "calmar_ratio": "卡玛比率",
    }
    
    for k, label in labels.items():
        if k in metrics:
            v = metrics[k]
            if k in ("total_return", "annual_return", "max_drawdown", "win_rate"):
                lines.append(f"| {label} | {v:.2%} |")
            else:
                lines.append(f"| {label} | {v} |")

    report = "\n".join(lines)
    
    if save:
        fname = REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        fname.write_text(report)
    
    return report
