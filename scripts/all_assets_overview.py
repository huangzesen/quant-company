"""
全标概览报告
—— 12 标的年化收益、波动率、相关系数矩阵
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
                                    "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_DIR / "data/raw"
REPORT_DIR = PROJECT_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ─── 加载所有日线数据 ───────────────────────────

tickers = []
data = {}

for ticker_dir in sorted(RAW_DIR.iterdir()):
    if not ticker_dir.is_dir():
        continue
    parquet_files = sorted(ticker_dir.glob("*1d_*.parquet"))
    if not parquet_files:
        continue
    df = pd.read_parquet(parquet_files[-1])
    if "close" not in df.columns:
        continue
    ticker = ticker_dir.name
    tickers.append(ticker)
    data[ticker] = df["close"]

print(f"加载 {len(tickers)} 个标的: {tickers}")

# ─── 对齐日期索引（统一时区）────────────────────

# 统一为 tz-naive，避免 tz-aware 与 tz-naive 冲突
for ticker in list(data.keys()):
    if data[ticker].index.tz is not None:
        data[ticker] = data[ticker].tz_localize(None)

prices = pd.DataFrame(data)
prices = prices.dropna(how="all")
returns = prices.pct_change().dropna(how="all")

# ─── 计算核心指标 ───────────────────────────────

stats_list = []
for ticker in tickers:
    p = prices[ticker].dropna()
    r = returns[ticker].dropna()
    if len(r) < 5:
        continue

    total_ret = p.iloc[-1] / p.iloc[0] - 1
    n_days = len(r)
    ann_ret = (1 + total_ret) ** (252 / n_days) - 1
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / max(ann_vol, 0.001)
    max_dd = ((p / p.expanding().max()) - 1).min()
    calmar = ann_ret / max(abs(max_dd), 0.01)

    stats_list.append({
        "ticker": ticker,
        "total_return": total_ret,
        "annual_return": ann_ret,
        "annual_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "n_days": n_days,
        "latest_price": round(p.iloc[-1], 2),
    })

stats_df = pd.DataFrame(stats_list)

# ─── 相关系数矩阵 ───────────────────────────────

corr = returns.corr()

# ─── 生成图表 ───────────────────────────────────

# 1. 年化收益 vs 年化波动率散点图
fig, ax = plt.subplots(figsize=(10, 7))
for _, row in stats_df.iterrows():
    ax.scatter(row["annual_vol"] * 100, row["annual_return"] * 100,
               s=120, alpha=0.7, color="#2196F3")
    ax.annotate(row["ticker"],
                (row["annual_vol"] * 100, row["annual_return"] * 100),
                fontsize=10, ha="center", va="bottom",
                xytext=(0, 5), textcoords="offset points")

ax.axhline(y=0, color="gray", linestyle="--", alpha=0.4)
ax.set_xlabel("年化波动率 (%)")
ax.set_ylabel("年化收益率 (%)")
ax.set_title("12 标的收益-风险散点图", fontsize=14)
ax.grid(True, alpha=0.3)
plt.tight_layout()
scatter_path = REPORT_DIR / "all_assets_risk_return.png"
plt.savefig(scatter_path, dpi=150)
plt.close()
print(f"风险收益散点图: {scatter_path}")

# 2. 相关系数矩阵热力图
fig, ax = plt.subplots(figsize=(10, 8))
im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")

ax.set_xticks(range(len(corr.columns)))
ax.set_yticks(range(len(corr.columns)))
ax.set_xticklabels(corr.columns, rotation=90, fontsize=9)
ax.set_yticklabels(corr.columns, fontsize=9)
ax.set_title("12 标的相关性矩阵 (日收益率)", fontsize=14)

# 标注数值
for i in range(len(corr.columns)):
    for j in range(len(corr.columns)):
        val = corr.values[i, j]
        color = "white" if abs(val) > 0.6 else "black"
        ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                fontsize=7, color=color)

plt.colorbar(im, ax=ax, shrink=0.8)
plt.tight_layout()
corr_path = REPORT_DIR / "all_assets_correlation.png"
plt.savefig(corr_path, dpi=150)
plt.close()
print(f"相关系数矩阵: {corr_path}")

# 3. 累计收益对比
norm_prices = prices / prices.iloc[0]
fig, ax = plt.subplots(figsize=(14, 7))
colors = plt.cm.tab20(np.linspace(0, 1, len(tickers)))
for i, ticker in enumerate(tickers):
    if ticker in norm_prices.columns:
        ax.plot(norm_prices.index, norm_prices[ticker],
                label=ticker, color=colors[i], linewidth=1.2, alpha=0.8)
ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.4)
ax.set_xlabel("日期")
ax.set_ylabel("累计收益 (归一化)")
ax.set_title("12 标的累计收益对比", fontsize=14)
ax.legend(loc="upper left", ncol=3, fontsize=8)
ax.grid(True, alpha=0.3)
plt.tight_layout()
cumret_path = REPORT_DIR / "all_assets_cumulative_returns.png"
plt.savefig(cumret_path, dpi=150)
plt.close()
print(f"累计收益对比图: {cumret_path}")

# ─── 生成 Markdown 报告 ─────────────────────────

report_lines = [
    "# 全标概览报告",
    "",
    f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"**标的数**: {len(tickers)}",
    f"**数据区间**: {returns.index[0].strftime('%Y-%m-%d')} → {returns.index[-1].strftime('%Y-%m-%d')}",
    "",
    "---",
    "",
    "## 一、核心指标对比",
    "",
    "| 标的 | 总收益率 | 年化收益率 | 年化波动率 | 夏普比率 | 最大回撤 | 卡玛比率 | 最新价 |",
    "|------|---------|-----------|-----------|---------|---------|---------|-------|",
]

for _, row in stats_df.iterrows():
    report_lines.append(
        f"| {row['ticker']} | {row['total_return']:.2%} | {row['annual_return']:.2%} | "
        f"{row['annual_vol']:.2%} | {row['sharpe']:.2f} | {row['max_drawdown']:.2%} | "
        f"{row['calmar']:.2f} | ${row['latest_price']} |"
    )

report_lines += [
    "",
    "## 二、收益-风险分析",
    "",
    f"![风险收益散点图](all_assets_risk_return.png)",
    "",
    "散点图左上为优（高收益、低波动），右下为劣（低收益、高波动）。",
    "",
    "## 三、相关性分析",
    "",
    f"![相关系数矩阵](all_assets_correlation.png)",
    "",
    "**高相关性对 (>0.8):**"
]

# 找出高相关对
high_corr = []
for i in range(len(tickers)):
    for j in range(i+1, len(tickers)):
        val = corr.values[i, j]
        if val > 0.8:
            high_corr.append(f"- {tickers[i]} ↔ {tickers[j]}: {val:.3f}")

if high_corr:
    report_lines += high_corr
else:
    report_lines.append("（无 >0.8 的高相关对）")

report_lines += [
    "",
    "**低相关性/负相关性对 (<0.3):**"
]

low_corr = []
for i in range(len(tickers)):
    for j in range(i+1, len(tickers)):
        val = corr.values[i, j]
        if val < 0.3:
            low_corr.append(f"- {tickers[i]} ↔ {tickers[j]}: {val:.3f}")

if low_corr[:10]:  # 最多列 10 对
    report_lines += low_corr[:10]
else:
    report_lines.append("（无 <0.3 的低相关对）")

report_lines += [
    "",
    "## 四、累计收益对比",
    "",
    f"![累计收益对比](all_assets_cumulative_returns.png)",
    "",
    "---",
    "",
    "## 五、关键发现",
    "",
]

# 找出最佳和最差
best_ret = stats_df.loc[stats_df["annual_return"].idxmax()]
worst_ret = stats_df.loc[stats_df["annual_return"].idxmin()]
best_sharpe = stats_df.loc[stats_df["sharpe"].idxmax()]
lowest_corr_pair = None
min_corr = 1.0
for i in range(len(tickers)):
    for j in range(i+1, len(tickers)):
        val = abs(corr.values[i, j])
        if val < min_corr:
            min_corr = val
            lowest_corr_pair = (tickers[i], tickers[j], corr.values[i, j])

report_lines += [
    f"- **年化收益最高**: {best_ret['ticker']} ({best_ret['annual_return']:.2%})",
    f"- **年化收益最低**: {worst_ret['ticker']} ({worst_ret['annual_return']:.2%})",
    f"- **夏普比率最优**: {best_sharpe['ticker']} ({best_sharpe['sharpe']:.2f})",
]
if lowest_corr_pair:
    report_lines.append(
        f"- **最佳分散组合**: {lowest_corr_pair[0]} ↔ {lowest_corr_pair[1]} "
        f"(相关系数 {lowest_corr_pair[2]:.3f})"
    )
report_lines.append(f"- **平均年化波动率**: {stats_df['annual_vol'].mean():.2%}")

report_text = "\n".join(report_lines)
report_path = REPORT_DIR / "all_assets_overview.md"
report_path.write_text(report_text, encoding="utf-8")
print(f"\n全标概览报告: {report_path}")
print("=== 完成 ===")
