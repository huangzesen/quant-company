#!/usr/bin/env python3
"""
风控检查脚本 —— 一键执行全套风控规则
LingTai Quant — risk_analyst 出品

用法:
    python scripts/risk_check.py                          # 交互选择模块
    python scripts/risk_check.py --all                     # 全量检查（需数据文件）
    python scripts/risk_check.py --data path/to/data.parquet --equity 100000
    python scripts/risk_check.py --check quality           # 仅数据质量
    python scripts/risk_check.py --check var              # 仅 VaR
    python scripts/risk_check.py --check drawdown         # 仅回撤
    python scripts/risk_check.py --check position --size 25000 --equity 100000  # 仅仓位
    python scripts/risk_check.py --check correlation --portfolio returns.csv
    python scripts/risk_check.py --check circuit-breaker  # 仅断路器
    python scripts/risk_check.py --check kelly --win-rate 0.55 --avg-win 200 --avg-loss 100
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np
import pandas as pd

# 加入项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared_lib.risk_manager import RiskManager, RiskConfig, CircuitBreaker

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("risk_check")

# ─────────── 配置（与 config/config.yaml 对齐） ───────────
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

def load_config() -> dict:
    """加载 YAML 配置"""
    import yaml
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

CONFIG = load_config()
RISK_CFG = CONFIG.get("risk", {})

DEFAULT_CONFIG = RiskConfig(
    max_drawdown=RISK_CFG.get("max_drawdown", 0.20),
    max_position_pct=RISK_CFG.get("max_position_size", 0.25),
    max_correlation=RISK_CFG.get("max_correlation", 0.80),
    var_confidence=RISK_CFG.get("var_confidence", 0.95),
)

QR_CODE = """
╔══════════════════════════════════════╗
║       灵台量化 · 风控检查          ║
║       LingTai Quant Risk Check      ║
╚══════════════════════════════════════╝
"""

# ════════════════════════════════════════════════
# 壹 · 数据质量预检
# ════════════════════════════════════════════════

def check_data_quality(df: pd.DataFrame, name: str = "unknown") -> dict:
    """
    数据质量四维检查：
    1. 缺失值比例
    2. 异常值（IQR 法）
    3. 分布偏度与峰度
    4. 时间连续性
    """
    logger.info(f"── 数据质量审查: {name} ──")
    result = {"dataset": name, "passed": True, "issues": [], "stats": {}}

    # 1. 缺失值
    missing_pct = df.isnull().mean()
    for col in df.columns:
        if missing_pct[col] > 0:
            pct = missing_pct[col]
            result["stats"][f"{col}_missing_pct"] = round(float(pct), 4)
            if pct > 0.05:
                result["issues"].append(f"⚠️  {col}: 缺失 {pct:.2%}（超阈值 5%）")
                result["passed"] = False
            elif pct > 0:
                result["issues"].append(f"ℹ️   {col}: 缺失 {pct:.2%}（可接受）")

    # 2. 异常值（IQR 法，仅数值列）
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = ((df[col] < lower) | (df[col] > upper)).sum()
        outlier_pct = outliers / len(df) if len(df) > 0 else 0
        result["stats"][f"{col}_outlier_pct"] = round(float(outlier_pct), 4)
        if outlier_pct > 0.05:
            result["issues"].append(f"⚠️  {col}: 异常值 {outlier_pct:.2%}（超阈值 5%）")
            result["passed"] = False
        elif outlier_pct > 0:
            result["issues"].append(f"ℹ️   {col}: 异常值 {outlier_pct:.2%}")

    # 3. 分布偏度（数值列）
    for col in numeric_cols:
        skew = df[col].skew()
        kurt = df[col].kurtosis()
        result["stats"][f"{col}_skew"] = round(float(skew), 3)
        result["stats"][f"{col}_kurtosis"] = round(float(kurt), 3)
        if abs(skew) > 3:
            result["issues"].append(f"⚠️  {col}: 偏度 {skew:.2f}（|skew|>3，严重偏态）")
            result["passed"] = False
        elif abs(skew) > 1:
            result["issues"].append(f"ℹ️   {col}: 偏度 {skew:.2f}（中度偏态）")

    # 4. 时间连续性（若有 datetime index）
    if isinstance(df.index, pd.DatetimeIndex):
        gaps = df.index.to_series().diff().dropna()
        if len(gaps) > 0:
            min_gap = gaps.min()
            max_gap = gaps.max()
            result["stats"]["min_gap"] = str(min_gap)
            result["stats"]["max_gap"] = str(max_gap)
            # 检查是否有超过 2 倍中位间隔的缺口
            median_gap = gaps.median()
            large_gaps = (gaps > 2 * median_gap).sum()
            if large_gaps > 0:
                result["issues"].append(f"⚠️  时间序列有 {large_gaps} 处异常缺口（>2×中位间隔）")
                result["passed"] = False

    status = "✅ 通过" if result["passed"] else "❌ 未通过"
    logger.info(f"数据质量: {status}")
    for issue in result["issues"]:
        logger.info(f"  {issue}")
    return result


# ════════════════════════════════════════════════
# 贰 · 仓位规模检查
# ════════════════════════════════════════════════

def check_position_size(proposed_size: float, equity: float,
                        max_pct: float = None) -> dict:
    """
    检查单笔仓位是否超过限制
    """
    cfg = DEFAULT_CONFIG if max_pct is None else RiskConfig(max_position_pct=max_pct)
    rm = RiskManager(cfg)
    adjusted = rm.check_position_size("CHECK", proposed_size, equity)
    max_allowed = equity * cfg.max_position_pct
    passed = (proposed_size <= max_allowed)
    result = {
        "check": "position_size",
        "passed": passed,
        "equity": equity,
        "proposed": proposed_size,
        "max_allowed": round(max_allowed, 2),
        "adjusted": round(adjusted, 2),
        "max_pct": cfg.max_position_pct,
        "utilization_pct": round(proposed_size / equity * 100, 2) if equity > 0 else 0,
    }
    status = "✅" if passed else "❌"
    logger.info(f"── 仓位检查 ──")
    logger.info(f"  净值: ${equity:,.2f} | 建议仓位: ${proposed_size:,.2f}")
    logger.info(f"  上限: ${max_allowed:,.2f} ({cfg.max_position_pct:.0%})")
    logger.info(f"  调整后: ${adjusted:,.2f} | 占用: {result['utilization_pct']:.1f}%")
    logger.info(f"  状态: {status}")
    return result


# ════════════════════════════════════════════════
# 叁 · 组合相关性检查
# ════════════════════════════════════════════════

def check_portfolio_correlation(returns_matrix: pd.DataFrame,
                                 max_corr: float = None) -> dict:
    """
    检查组合中资产间相关是否超过阈值
    """
    cfg = DEFAULT_CONFIG if max_corr is None else RiskConfig(max_correlation=max_corr)
    rm = RiskManager(cfg)
    passed = rm.check_portfolio_correlation(returns_matrix)
    corr = returns_matrix.corr()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    max_corr_val = upper.max().max()
    high_pairs = []
    for i in range(len(corr.columns)):
        for j in range(i+1, len(corr.columns)):
            val = corr.iloc[i, j]
            if val > cfg.max_correlation:
                high_pairs.append((corr.columns[i], corr.columns[j], round(val, 3)))
    result = {
        "check": "correlation",
        "passed": passed,
        "max_correlation": round(float(max_corr_val), 3),
        "threshold": cfg.max_correlation,
        "assets": list(corr.columns),
        "high_corr_pairs": high_pairs,
    }
    status = "✅" if passed else "❌"
    logger.info(f"── 相关性检查 ──")
    logger.info(f"  最大相关系数: {result['max_correlation']:.3f} (阈值: {cfg.max_correlation})")
    for pair in high_pairs:
        logger.info(f"  ⚠️  {pair[0]} ↔ {pair[1]}: {pair[2]:.3f}")
    logger.info(f"  状态: {status}")
    return result


# ════════════════════════════════════════════════
# 肆 · VaR 计算（历史模拟法）
# ════════════════════════════════════════════════

def calculate_var(returns: pd.Series, confidence: float = None) -> dict:
    """
    历史模拟法 VaR + CVaR（条件 VaR / 预期亏损）
    """
    cfg = DEFAULT_CONFIG if confidence is None else RiskConfig(var_confidence=confidence)
    rm = RiskManager(cfg)
    var = rm.calculate_var(returns)
    # CVaR：尾部均值
    cvar = returns[returns <= var].mean() if (returns <= var).any() else var
    result = {
        "check": "value_at_risk",
        "confidence": cfg.var_confidence,
        "var": round(float(var), 6),
        "cvar": round(float(cvar), 6),
        "n_obs": len(returns),
        "portfolio_value_impact_pct": round(float(var) * 100, 2),
        "interpretation": (
            f"有 {(1-cfg.var_confidence)*100:.0f}% 的概率，单日损失不超过 {var:.4f}"
        ),
    }
    logger.info(f"── VaR 计算 ──")
    logger.info(f"  置信度: {cfg.var_confidence:.0%}")
    logger.info(f"  历史模拟 VaR: {var:.4f}")
    logger.info(f"  条件 VaR (CVaR): {cvar:.4f}")
    logger.info(f"  组合影响: {result['portfolio_value_impact_pct']:.2f}%")
    logger.info(f"  样本量: {len(returns)}")
    return result


# ════════════════════════════════════════════════
# 伍 · 最大回撤检查
# ════════════════════════════════════════════════

def check_drawdown(equity_curve: pd.Series, max_dd: float = None) -> dict:
    """
    检查权益曲线是否触发最大回撤限制
    """
    cfg = DEFAULT_CONFIG if max_dd is None else RiskConfig(max_drawdown=max_dd)
    rm = RiskManager(cfg)
    peak = equity_curve.expanding().max()
    dd = (equity_curve - peak) / peak
    current_dd = dd.iloc[-1]
    max_dd_val = dd.min()
    passed = rm.check_max_drawdown(equity_curve)
    result = {
        "check": "drawdown",
        "passed": passed,
        "current_drawdown": round(float(current_dd), 4),
        "max_drawdown_history": round(float(max_dd_val), 4),
        "threshold": cfg.max_drawdown,
        "peak_value": round(float(peak.iloc[-1]), 2),
        "current_value": round(float(equity_curve.iloc[-1]), 2),
        "drawdown_dates": {
            "peak_date": str(peak.idxmax()) if hasattr(peak, 'idxmax') else "N/A",
            "trough_date": str(dd.idxmin()) if hasattr(dd, 'idxmin') else "N/A",
        },
    }
    status = "✅" if passed else "❌"
    logger.info(f"── 回撤检查 ──")
    logger.info(f"  当前回撤: {current_dd:.2%}")
    logger.info(f"  历史最大回撤: {max_dd_val:.2%}")
    logger.info(f"  阈值: -{cfg.max_drawdown:.0%}")
    logger.info(f"  峰值: ${result['peak_value']:.2f} → 现值: ${result['current_value']:.2f}")
    logger.info(f"  状态: {status}")
    return result


# ════════════════════════════════════════════════
# 陆 · 断路器状态检查
# ════════════════════════════════════════════════

def check_circuit_breaker(trade_pnls: List[float],
                           max_losses: int = 3,
                           cooldown: int = 10) -> dict:
    """
    模拟断路器逻辑，检查当前交易序列是否触发断路器
    """
    cb = CircuitBreaker(max_consecutive_losses=max_losses, cooldown_bars=cooldown)
    triggered_at = []
    for i, pnl in enumerate(trade_pnls):
        cb.record_trade(pnl)
        if cb.tripped:
            triggered_at.append(i)
    result = {
        "check": "circuit_breaker",
        "tripped": cb.tripped,
        "consecutive_losses": cb.consecutive_losses,
        "cooldown_remaining": cb.cooldown_remaining,
        "max_consecutive_losses": max_losses,
        "cooldown_bars": cooldown,
        "total_trades_checked": len(trade_pnls),
        "triggered_at_indices": triggered_at,
        "num_triggers": len(triggered_at),
    }
    status = "🔴 触发" if cb.tripped else "🟢 正常"
    logger.info(f"── 断路器检查 ──")
    logger.info(f"  状态: {status}")
    logger.info(f"  连续亏损: {cb.consecutive_losses} / {max_losses}")
    logger.info(f"  冷却剩余: {cb.cooldown_remaining} / {cooldown}")
    logger.info(f"  历史触发次数: {len(triggered_at)}")
    return result


# ════════════════════════════════════════════════
# 柒 · 凯利公式计算
# ════════════════════════════════════════════════

def calculate_kelly(win_rate: float, avg_win: float, avg_loss: float,
                    max_position: float = None) -> dict:
    """
    凯利公式计算最优仓位比例
    """
    cfg = DEFAULT_CONFIG if max_position is None else RiskConfig(max_position_pct=max_position)
    rm = RiskManager(cfg)
    if avg_loss >= 0:
        logger.warning("avg_loss 应为负值或正数。若为正值收益，重新解释")
        avg_loss = -abs(avg_loss)
    kelly_f = rm.kelly_fraction(win_rate, avg_win, abs(avg_loss))
    # 半凯利（保守）
    half_kelly = kelly_f * 0.5
    result = {
        "check": "kelly_criterion",
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "kelly_fraction": round(kelly_f, 4),
        "half_kelly_fraction": round(half_kelly, 4),
        "max_position_pct": cfg.max_position_pct,
        "recommended_pct": round(min(half_kelly, cfg.max_position_pct), 4),
        "interpretation": (
            f"凯利建议仓位: {kelly_f:.1%}（保守半凯利: {half_kelly:.1%}）"
        ),
    }
    logger.info(f"── 凯利公式 ──")
    logger.info(f"  胜率: {win_rate:.1%} | 平均盈利: ${avg_win:.2f} | 平均亏损: ${avg_loss:.2f}")
    logger.info(f"  凯利比例: {kelly_f:.2%}")
    logger.info(f"  半凯利（推荐）: {half_kelly:.2%}")
    logger.info(f"  最终建议: {result['recommended_pct']:.2%}")
    return result


# ════════════════════════════════════════════════
# 捌 · 全面检查（一站式报告）
# ════════════════════════════════════════════════

def full_check(data_path: str = None, equity: float = 100000,
               returns_path: str = None, trade_pnls: List[float] = None):
    """全量风控检查"""
    print(QR_CODE)
    logger.info("=" * 46)
    logger.info("        全量风控检查启动")
    logger.info("=" * 46)

    results = {}

    # 数据质量
    if data_path and os.path.exists(data_path):
        df = pd.read_parquet(data_path) if data_path.endswith('.parquet') else pd.read_csv(data_path)
        results['data_quality'] = check_data_quality(df, Path(data_path).name)
    else:
        logger.info("⏭️  跳过数据质量检查（未提供数据文件）")

    # 仓位检查示例
    if equity > 0:
        example_size = equity * 0.20  # 示例：20% 仓位
        results['position_size'] = check_position_size(example_size, equity)

    # 相关性检查
    if returns_path and os.path.exists(returns_path):
        ret_df = pd.read_csv(returns_path, index_col=0)
        results['correlation'] = check_portfolio_correlation(ret_df)
    else:
        logger.info("⏭️  跳过相关性检查（未提供收益矩阵）")

    # 断路器
    if trade_pnls:
        results['circuit_breaker'] = check_circuit_breaker(trade_pnls)

    # 汇总
    logger.info("=" * 46)
    passed_count = sum(1 for r in results.values() if r.get("passed", True))
    total_count = len(results)
    logger.info(f"检查项: {passed_count}/{total_count} 通过")
    if passed_count == total_count:
        logger.info("🎉 全量风控检查: ✅ 全部通过")
    else:
        logger.info(f"⚠️  有 {total_count - passed_count} 项异常，请关注以上详情")
    logger.info("=" * 46)
    return results


# ════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="灵台量化 · 风控检查脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--all", action="store_true", help="全量检查")
    parser.add_argument("--check", type=str, choices=[
        "quality", "position", "correlation", "var", "drawdown",
        "circuit-breaker", "kelly"
    ], help="指定检查模块")
    parser.add_argument("--data", type=str, help="数据文件路径 (.parquet 或 .csv)")
    parser.add_argument("--equity", type=float, default=100000, help="账户净值")
    parser.add_argument("--size", type=float, help="建议仓位金额（用于仓位检查）")
    parser.add_argument("--portfolio", type=str, help="收益率矩阵 CSV（用于相关性检查）")
    parser.add_argument("--confidence", type=float, default=0.95, help="VaR 置信度")
    parser.add_argument("--max-dd", type=float, help="最大回撤阈值")
    parser.add_argument("--win-rate", type=float, help="胜率（用于凯利）")
    parser.add_argument("--avg-win", type=float, help="平均盈利（用于凯利）")
    parser.add_argument("--avg-loss", type=float, help="平均亏损（用于凯利）")
    parser.add_argument("--pnls", type=float, nargs="*", help="交易盈亏序列（用于断路器）")
    parser.add_argument("--returns", type=str, help="收益率序列文件路径（用于 VaR/回撤）")

    args = parser.parse_args()

    if args.all:
        return full_check(args.data, args.equity, args.portfolio, args.pnls)

    if not args.check:
        parser.print_help()
        print("\n提示: 使用 --all 全量检查，或 --check 指定模块")
        return

    print(QR_CODE)

    if args.check == "quality":
        if not args.data:
            logger.error("数据质量检查需要 --data 参数")
            return
        df = pd.read_parquet(args.data) if args.data.endswith('.parquet') else pd.read_csv(args.data)
        return check_data_quality(df)

    elif args.check == "position":
        if not args.size:
            logger.error("仓位检查需要 --size 和 --equity 参数")
            return
        return check_position_size(args.size, args.equity)

    elif args.check == "correlation":
        if not args.portfolio:
            logger.error("相关性检查需要 --portfolio 参数（CSV 文件）")
            return
        df = pd.read_csv(args.portfolio, index_col=0)
        return check_portfolio_correlation(df)

    elif args.check == "var":
        if not args.returns:
            logger.error("VaR 计算需要 --returns 参数（收益率 CSV 或 parquet）")
            return
        ret = pd.read_parquet(args.returns) if args.returns.endswith('.parquet') else pd.read_csv(args.returns)
        col = ret.columns[0] if ret.shape[1] > 0 else "returns"
        return calculate_var(ret[col], args.confidence)

    elif args.check == "drawdown":
        if not args.returns:
            logger.error("回撤检查需要 --returns 参数")
            return
        eq = pd.read_parquet(args.returns) if args.returns.endswith('.parquet') else pd.read_csv(args.returns)
        col = eq.columns[0] if eq.shape[1] > 0 else "equity"
        return check_drawdown(eq[col], args.max_dd)

    elif args.check == "circuit-breaker":
        pnls = args.pnls or [-100, -150, -200, 50, -300]
        return check_circuit_breaker(pnls)

    elif args.check == "kelly":
        wr = args.win_rate or 0.55
        aw = args.avg_win or 200
        al = args.avg_loss or -100
        return calculate_kelly(wr, aw, al)


if __name__ == "__main__":
    main()
