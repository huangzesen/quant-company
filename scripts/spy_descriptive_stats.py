"""
SPY 描述性统计报告
—— 价格分布、收益率统计、波动率分析
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime

# ─── 中文字体 ───────────────────────────────────
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Apple LiGothic",
                                    "WenQuanYi Micro Hei", "Noto Sans CJK SC",
                                    "Source Han Sans SC", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_DIR / "data/raw/SPY"
REPORT_DIR = PROJECT_DIR / "reports"

# 使用日线数据 (1d)，排除小时线 (1h)
spy_files = sorted(DATA_PATH.glob("SPY_*1d_*.parquet"))
if not spy_files:
    spy_files = sorted(DATA_PATH.glob("SPY_*.parquet"))
if not spy_files:
    raise FileNotFoundError("No SPY parquet files found")
DATA_FILE = spy_files[-1]

# ─── 加载数据 ───────────────────────────────────

df = pd.read_parquet(DATA_FILE)
print(f"加载: {DATA_FILE.name}")
print(f"行数: {len(df)}, 区间: {df.index[0]} → {df.index[-1]}")

# ─── 收益率计算 ─────────────────────────────────

df["return"] = df["close"].pct_change()
df["log_return"] = np.log(df["close"] / df["close"].shift(1))
df["range"] = (df["high"] - df["low"]) / df["close"] * 100  # 日内振幅 %
df["true_range"] = np.maximum(
    df["high"] - df["low"],
    np.maximum(
        abs(df["high"] - df["close"].shift(1)),
        abs(df["low"] - df["close"].shift(1)),
    ),
)
df["atr"] = df["true_range"].rolling(14).mean()

daily_returns = df["return"].dropna()
log_returns = df["log_return"].dropna()

# ─── 描述性统计 ─────────────────────────────────

price = df["close"]
stats = {
    "period_start": str(df.index[0].strftime("%Y-%m-%d")),
    "period_end": str(df.index[-1].strftime("%Y-%m-%d")),
    "trading_days": len(df),
    "price_latest": round(price.iloc[-1], 2),
    "price_max": round(price.max(), 2),
    "price_min": round(price.min(), 2),
    "price_mean": round(price.mean(), 2),
    "price_std": round(price.std(), 2),
    "total_return": round(price.iloc[-1] / price.iloc[0] - 1, 4),
    "annual_return": round((price.iloc[-1] / price.iloc[0]) ** (252 / len(df)) - 1, 4),
    "daily_mean": round(daily_returns.mean(), 6),
    "daily_std": round(daily_returns.std(), 6),
    "daily_skew": round(daily_returns.skew(), 4),
    "daily_kurt": round(daily_returns.kurtosis(), 4),
    "min_return": round(daily_returns.min(), 6),
    "max_return": round(daily_returns.max(), 6),
    "volatility_ann": round(daily_returns.std() * np.sqrt(252), 4),
    "positive_days": int((daily_returns > 0).sum()),
    "negative_days": int((daily_returns < 0).sum()),
    "avg_true_range": round(df["atr"].mean(), 4),
    "latest_atr": round(df["atr"].iloc[-1], 4),
}

# ─── 生成图表 ───────────────────────────────────

_REPORT_DIR = REPORT_DIR
_REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 1. 价格走势图
fig, axes = plt.subplots(3, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1, 1]})

axes[0].plot(df.index, df["close"], linewidth=1.5, color="#2196F3")
axes[0].fill_between(df.index, df["close"].min(), df["close"], alpha=0.08, color="#2196F3")
axes[0].set_title("SPY 价格走势 (2024-04 ~ 2026-04)", fontsize=14)
axes[0].set_ylabel("价格 ($)")
axes[0].grid(True, alpha=0.3)

axes[1].bar(df.index[1:], daily_returns, width=1, color=["#4CAF50" if v > 0 else "#f44336" for v in daily_returns], alpha=0.6)
axes[1].axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
axes[1].set_ylabel("日收益率")
axes[1].grid(True, alpha=0.3)

axes[2].plot(df.index[14:], df["atr"].iloc[14:], linewidth=1.2, color="#FF9800")
axes[2].fill_between(df.index[14:], df["atr"].iloc[14:], alpha=0.15, color="#FF9800")
axes[2].set_ylabel("ATR(14)")
axes[2].set_xlabel("日期")
axes[2].grid(True, alpha=0.3)

plt.tight_layout()
price_chart_path = _REPORT_DIR / "spy_price_overview.png"
plt.savefig(price_chart_path, dpi=150)
plt.close()
print(f"价格走势图: {price_chart_path}")

# 2. 收益率分布直方图 + QQ 图
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

axes[0].hist(daily_returns * 100, bins=60, color="#2196F3", alpha=0.7, edgecolor="white")
axes[0].axvline(x=0, color="red", linestyle="--", alpha=0.5)
axes[0].set_title("日收益率分布 (%)", fontsize=13)
axes[0].set_xlabel("日收益率 (%)")
axes[0].set_ylabel("频次")
axes[0].grid(True, alpha=0.3)

# 累计分布
sorted_rets = np.sort(daily_returns)
norm_rets = (sorted_rets - sorted_rets.mean()) / sorted_rets.std()
from scipy import stats as scipy_stats
quantiles = np.linspace(0.01, 0.99, len(sorted_rets))
normal_q = scipy_stats.norm.ppf(quantiles)
axes[1].scatter(normal_q, sorted_rets, s=10, alpha=0.6, color="#2196F3")
axes[1].plot([sorted_rets.min(), sorted_rets.max()], [sorted_rets.min(), sorted_rets.max()], 
             "r--", alpha=0.5)
axes[1].set_title("Q-Q 图 (收益率正态检验)", fontsize=13)
axes[1].set_xlabel("理论正态分位数")
axes[1].set_ylabel("样本分位数")
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
dist_chart_path = _REPORT_DIR / "spy_return_distribution.png"
plt.savefig(dist_chart_path, dpi=150)
plt.close()
print(f"收益率分布图: {dist_chart_path}")

# 3. 波动率聚类图（滚动30日波动率）
rolling_vol = daily_returns.rolling(30).std() * np.sqrt(252)
fig, ax = plt.subplots(figsize=(14, 4))
ax.plot(rolling_vol.index, rolling_vol * 100, linewidth=1.5, color="#FF5722")
ax.fill_between(rolling_vol.index, rolling_vol * 100, alpha=0.15, color="#FF5722")
ax.axhline(y=daily_returns.std() * np.sqrt(252) * 100, color="gray", linestyle="--", alpha=0.5, label="全期年化波动率")
ax.set_title("SPY 滚动 30 日年化波动率", fontsize=13)
ax.set_ylabel("年化波动率 (%)")
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
vol_chart_path = _REPORT_DIR / "spy_volatility.png"
plt.savefig(vol_chart_path, dpi=150)
plt.close()
print(f"波动率图: {vol_chart_path}")

# ─── 生成 Markdown 报告 ─────────────────────────

report_lines = [
    "# SPY 描述性统计报告",
    "",
    f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    "",
    "---",
    "",
    "## 一、价格总览",
    "",
    "| 指标 | 数值 |",
    "|------|------|",
    f"| 数据区间 | {stats['period_start']} → {stats['period_end']} |",
    f"| 交易日数 | {stats['trading_days']} |",
    f"| 最新收盘价 | ${stats['price_latest']:.2f} |",
    f"| 期间最高 | ${stats['price_max']:.2f} |",
    f"| 期间最低 | ${stats['price_min']:.2f} |",
    f"| 均价 | ${stats['price_mean']:.2f} |",
    f"| 价格标准差 | ${stats['price_std']:.2f} |",
    f"| 总收益率 | {stats['total_return']:.2%} |",
    f"| 年化收益率 | {stats['annual_return']:.2%} |",
    "",
    "## 二、收益率统计",
    "",
    "| 指标 | 数值 |",
    "|------|------|",
    f"| 日均收益率 | {stats['daily_mean']:.4%} |",
    f"| 日收益率标准差 | {stats['daily_std']:.4%} |",
    f"| 年化波动率 | {stats['volatility_ann']:.2%} |",
    f"| 偏度 | {stats['daily_skew']:.4f} |",
    f"| 峰度 | {stats['daily_kurt']:.4f} |",
    f"| 最大日涨幅 | {stats['max_return']:.4%} |",
    f"| 最大日跌幅 | {stats['min_return']:.4%} |",
    f"| 上涨天数 / 下跌天数 | {stats['positive_days']} / {stats['negative_days']} |",
    f"| 平均真实波幅 (ATR) | {stats['avg_true_range']:.2f} |",
    f"| 最新 ATR(14) | {stats['latest_atr']:.2f} |",
    "",
    "## 三、图表",
    "",
    f"![价格走势](spy_price_overview.png)",
    "",
    f"![收益率分布](spy_return_distribution.png)",
    "",
    f"![波动率](spy_volatility.png)",
    "",
    "---",
    "",
    "## 四、关键观察",
    "",
    f"- SPY 在 {stats['trading_days']} 个交易日内实现 {stats['total_return']:.1%} 总回报",
    f"- 年化波动率 {stats['volatility_ann']:.1%}，属于中等波动水平",
    f"- 偏度 {stats['daily_skew']:.2f}{'，略左偏（极端跌幅多于极端涨幅）' if stats['daily_skew'] < 0 else '，略右偏（极端涨幅多于极端跌幅）'}",
    f"- 峰度 {stats['daily_kurt']:.2f}，{'厚尾分布（极端事件频率高于正态分布预测）' if stats['daily_kurt'] > 0 else '薄尾分布'}",
    f"- 胜率（上涨日占比）: {stats['positive_days']/stats['trading_days']:.1%}",
]

report_text = "\n".join(report_lines)
report_path = _REPORT_DIR / "spy_descriptive_stats.md"
report_path.write_text(report_text, encoding="utf-8")
print(f"\n描述性统计报告: {report_path}")
print("=== 完成 ===")
