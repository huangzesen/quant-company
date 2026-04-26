"""
参数优化器 — 网格搜索 / 随机搜索
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Callable, Type
from itertools import product
import logging
from pathlib import Path
import json
from datetime import datetime

logger = logging.getLogger("quant.optimizer")


def grid_search(
    strategy_class: Type,
    df: pd.DataFrame,
    param_grid: Dict[str, List],
    backtest_fn: Callable,
    metric: str = "sharpe_ratio",
    maximize: bool = True,
    **backtest_kwargs,
) -> Dict:
    """
    网格搜索参数优化

    参数:
        strategy_class: 策略类
        df: 数据
        param_grid: {param_name: [values]}
        backtest_fn: 回测函数
        metric: 优化目标指标
        maximize: True=最大化, False=最小化
        **backtest_kwargs: 传给回测函数的其他参数

    返回:
        {
            "best_params": {...},
            "best_score": float,
            "all_results": [{...}],
        }
    """
    keys = list(param_grid.keys())
    value_lists = list(param_grid.values())

    all_results = []
    best_score = float("-inf") if maximize else float("inf")
    best_params = None

    total = 1
    for v in value_lists:
        total *= len(v)

    logger.info(f"Grid search: {total} combinations")

    for i, combo in enumerate(product(*value_lists)):
        params = dict(zip(keys, combo))
        try:
            strategy = strategy_class(params=params)
            result = backtest_fn(strategy, df, **backtest_kwargs)
            score = result["metrics"].get(metric, 0)

            entry = {
                "params": params,
                "score": score,
                "metrics": result["metrics"],
            }
            all_results.append(entry)

            if maximize:
                if score > best_score:
                    best_score = score
                    best_params = params
            else:
                if score < best_score:
                    best_score = score
                    best_params = params

            if (i + 1) % 20 == 0 or i == 0:
                logger.info(f"  [{i+1}/{total}] {params} → {metric}={score:.4f}")

        except Exception as e:
            logger.warning(f"  [{i+1}/{total}] {params} → FAILED: {e}")

    return {
        "best_params": best_params,
        "best_score": best_score,
        "all_results": sorted(all_results, key=lambda x: x["score"], reverse=maximize),
        "metric": metric,
        "strategy_name": strategy_class.__name__,
    }


def optimize_strategy(
    strategy_class: Type,
    df: pd.DataFrame,
    param_ranges: Dict[str, tuple],
    n_iterations: int = 50,
    backtest_fn: Callable = None,
    metric: str = "sharpe_ratio",
    method: str = "random",
    **backtest_kwargs,
) -> Dict:
    """
    策略参数优化 — 支持随机搜索

    参数:
        strategy_class: 策略类
        df: 数据
        param_ranges: {param_name: (min, max, step_or_type)}
        n_iterations: 随机搜索迭代次数
        method: "grid" | "random"
    """
    if backtest_fn is None:
        from .backtester import vectorized_backtest
        backtest_fn = vectorized_backtest

    if method == "random":
        import random as _random

        all_results = []
        best_score = float("-inf")
        best_params = None

        for i in range(n_iterations):
            params = {}
            for k, r in param_ranges.items():
                if len(r) == 3 and isinstance(r[2], (int, float)):
                    # (min, max, step) — 离散
                    n_steps = int((r[1] - r[0]) / r[2]) + 1
                    idx = _random.randint(0, n_steps - 1)
                    params[k] = r[0] + idx * r[2]
                elif len(r) == 2:
                    # (min, max) — 连续
                    if isinstance(r[0], int) and isinstance(r[1], int):
                        params[k] = _random.randint(r[0], r[1])
                    else:
                        params[k] = _random.uniform(r[0], r[1])

            try:
                strategy = strategy_class(params=params)
                result = backtest_fn(strategy, df, **backtest_kwargs)
                score = result["metrics"].get(metric, 0)

                all_results.append({
                    "params": params,
                    "score": score,
                    "metrics": result["metrics"],
                })

                if score > best_score:
                    best_score = score
                    best_params = params

            except Exception as e:
                pass

        return {
            "best_params": best_params,
            "best_score": best_score,
            "all_results": sorted(all_results, key=lambda x: x["score"], reverse=True),
            "metric": metric,
            "strategy_name": strategy_class.__name__,
            "n_iterations": n_iterations,
        }

    else:
        # 网格搜索
        param_grid = {}
        for k, r in param_ranges.items():
            if len(r) == 3 and isinstance(r[2], (int, float)):
                param_grid[k] = list(np.arange(r[0], r[1] + r[2], r[2]))
            else:
                param_grid[k] = list(np.linspace(r[0], r[1], 5))
        return grid_search(strategy_class, df, param_grid, backtest_fn, metric, **backtest_kwargs)
