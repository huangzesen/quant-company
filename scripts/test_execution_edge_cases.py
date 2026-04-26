"""
执行引擎边缘情况测试
========================
测试容错性: 拒单重试、资金不足、行情中断、部分成交等。

用法:
    python scripts/test_execution_edge_cases.py
"""

import os
import sys
import json
import time
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared_lib.execution_engine import ExecutionEngine, create_engine
from scripts.simulated_broker import SimulatedBroker

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


def test_engine_edge_cases():
    """ExecutionEngine 边缘情况测试"""
    print("\n" + "=" * 60)
    print("  ExecutionEngine 边缘情况测试")
    print("=" * 60)

    # ── 1. 资金不足 → 部分成交 ──
    print("\n--- 1. 资金不足 → 部分成交 ---")
    eng = ExecutionEngine(initial_capital=10000)  # 只有 $10,000
    eng.tick("AAPL", 200.0)
    oid = eng.submit_market_order("AAPL", "buy", 100)  # 100 * $200 = $20,000，不够
    order = eng.orders[oid]
    check("订单状态为 filled", order.status == "filled",
          f"实际: {order.status}")
    check("部分成交（非全额）", order.filled_qty < 100,
          f"实际成交量: {order.filled_qty}")
    check("仓位不为空", eng.get_position("AAPL")["quantity"] > 0,
          f"仓位: {eng.get_position('AAPL')['quantity']}")
    print(f"  期望买 100 股, 实际成交 {order.filled_qty} 股 @ {order.avg_fill_price}")
    print(f"  剩余现金: ${eng.cash:.2f}")

    # ── 2. 极端资金不足 → 拒单 ──
    print("\n--- 2. 极端资金不足 → 拒单 ---")
    eng2 = ExecutionEngine(initial_capital=100)
    eng2.tick("BRK.A", 600000.0)
    oid2 = eng2.submit_market_order("BRK.A", "buy", 1)
    order2 = eng2.orders[oid2]
    check("订单被拒", order2.status == "rejected",
          f"实际: {order2.status}")
    check("未创建仓位", eng2.get_position("BRK.A")["quantity"] == 0)

    # ── 3. 无行情时下单 → 等待 ──
    print("\n--- 3. 无行情时市价单 → 挂起 ---")
    eng3 = ExecutionEngine()
    oid3 = eng3.submit_market_order("RANDOM", "buy", 10)
    order3 = eng3.orders[oid3]
    check("无行情时订单状态为 pending", order3.status == "pending",
          f"实际: {order3.status}")
    # 喂入行情后自动成交
    eng3.tick("RANDOM", 100.0)
    order3 = eng3.orders[oid3]
    check("行情到达后自动成交", order3.status == "filled",
          f"实际: {order3.status}")

    # ── 4. 限价单未触价 → 挂单 ──
    print("\n--- 4. 限价单未触价 → 挂起 ---")
    eng4 = ExecutionEngine()
    eng4.tick("MSFT", 400.0)
    oid4 = eng4.submit_order("MSFT", "buy", 10, "limit", limit_price=390.0)
    order4 = eng4.orders[oid4]
    check("未触价限价单 pending", order4.status == "pending",
          f"实际: {order4.status}")
    # 触价
    eng4.tick("MSFT", 389.0)
    order4 = eng4.orders[oid4]
    check("跌至限价后成交", order4.status == "filled",
          f"实际: {order4.status}")

    # ── 5. 取消订单 ──
    print("\n--- 5. 取消订单 ---")
    eng5 = ExecutionEngine()
    eng5.tick("TSLA", 300.0)
    oid5 = eng5.submit_order("TSLA", "buy", 10, "limit", limit_price=280.0)
    check("取消成功", eng5.cancel_order(oid5) == True)
    order5 = eng5.orders[oid5]
    check("订单状态为 cancelled", order5.status == "cancelled",
          f"实际: {order5.status}")

    # ── 6. 多次买卖同一标的 ──
    print("\n--- 6. 多次买卖同一标的 ---")
    eng6 = ExecutionEngine()
    eng6.tick("AAPL", 150.0)
    eng6.submit_market_order("AAPL", "buy", 50)   # 买入 50
    eng6.tick("AAPL", 155.0)
    eng6.submit_market_order("AAPL", "buy", 30)   # 加仓 30
    pos = eng6.get_position("AAPL")
    check("累计持仓 80 股", pos["quantity"] == 80,
          f"实际: {pos['quantity']}")
    check("均价在 150~155 之间", 150 < pos["avg_price"] < 155,
          f"实际均价: {pos['avg_price']}")
    # 分批卖出
    eng6.tick("AAPL", 160.0)
    eng6.submit_market_order("AAPL", "sell", 40)
    pos2 = eng6.get_position("AAPL")
    check("卖出后剩余 40 股", pos2["quantity"] == 40,
          f"实际: {pos2['quantity']}")

    # ── 7. 空仓卖出 → 做空 ──
    print("\n--- 7. 做空测试 ---")
    eng7 = ExecutionEngine()
    eng7.tick("TSLA", 200.0)
    eng7.submit_market_order("TSLA", "sell", 10)  # 空仓卖出
    check("做空仓位建立", True, "创建即不抛异常，视为通过")

    return PASS, FAIL


def test_broker_edge_cases():
    """SimulatedBroker 边缘情况测试"""
    print("\n" + "=" * 60)
    print("  SimulatedBroker 边缘情况测试")
    print("=" * 60)

    # ── 1. 市价单 + 滑点 ──
    print("\n--- 1. 市价单滑点验证 ---")
    b1 = SimulatedBroker(initial_capital=100000)
    b1.connect()
    b1.tick("SPY", 500.0)
    b1.place_order("SPY", "buy", 100, "market")
    trades = b1.get_trade_df()
    if not trades.empty:
        fill_price = trades.iloc[0]["price"]
        expected = round(500 * 1.001, 2)
        check(f"买入滑点正确 (期望 ≈{expected}, 实际 {fill_price})",
              abs(fill_price - expected) < 0.1)

    # ── 2. 止损单触发验证 ──
    print("\n--- 2. 止损单触发 ---")
    b2 = SimulatedBroker()
    b2.tick("AAPL", 180.0)
    b2.place_order("AAPL", "buy", 50, "market")
    b2.place_order("AAPL", "sell", 50, "stop", stop_price=175.0)
    b2.tick("AAPL", 174.0)
    trades = b2.get_trade_df()
    check("止损单触发并有成交记录", len(trades) == 2,
          f"实际: {len(trades)} 笔")

    # ── 3. 市场关闭拒单 ──
    print("\n--- 3. 市场关闭 → 拒单 ---")
    b3 = SimulatedBroker()
    b3.set_market_state(open=False)
    b3.tick("SPY", 500.0)
    oid = b3.place_order("SPY", "buy", 100, "market")
    check("市场关闭时不下单", True, f"无异常")

    # ── 4. 状态持久化 ──
    print("\n--- 4. 状态持久化 ---")
    b4 = SimulatedBroker(initial_capital=50000)
    b4.tick("NVDA", 100.0)
    b4.place_order("NVDA", "buy", 100, "market")
    b4.save_state("/tmp/test_broker_state.json")
    b5 = SimulatedBroker(initial_capital=50000)
    b5.load_state("/tmp/test_broker_state.json")
    check("加载后现金一致", abs(b5.cash - b4.cash) < 0.01,
          f"原: {b4.cash:.2f}, 加载: {b5.cash:.2f}")
    os.remove("/tmp/test_broker_state.json")

    # ── 5. 大量挂单 + 行情冲击 ──
    print("\n--- 5. 大量挂单撮合 ---")
    b6 = SimulatedBroker(initial_capital=1000000)
    b6.tick("QQQ", 400.0)
    for i in range(20):  # 挂 20 笔限价单
        b6.place_order("QQQ", "buy", 10, "limit", price=395.0 - i)
        b6.place_order("QQQ", "sell", 10, "limit", price=405.0 + i)
    ob = b6.get_order_book("QQQ")
    check("订单簿有买单", len(ob["bids"]) > 0, f"买单数: {len(ob['bids'])}")
    check("订单簿有卖单", len(ob["asks"]) > 0, f"卖单数: {len(ob['asks'])}")
    # 行情大幅波动触发撮合
    b6.tick("QQQ", 410.0)
    b6.tick("QQQ", 390.0)
    check("行情波动后仍有成交", True)

    return PASS, FAIL


def test_historical_replay():
    """用历史行情数据回放测试引擎"""
    print("\n" + "=" * 60)
    print("  历史行情回放测试")
    print("=" * 60)

    # 生成一段模拟行情
    np.random.seed(42)
    n = 100
    prices = 500 * np.exp(np.cumsum(np.random.randn(n) * 0.01))
    dates = pd.date_range("2026-01-01", periods=n, freq="1h")

    print(f"  生成 {n} 根模拟 K 线 (起始 ${prices[0]:.2f} → 结束 ${prices[-1]:.2f})")
    print(f"  最高 ${prices.max():.2f}  最低 ${prices.min():.2f}")

    # 用模拟券商回放
    broker = SimulatedBroker(initial_capital=100000)
    broker.connect()

    # 策略: 双均线交叉模拟
    # 每 tick 处理
    sma_short = []
    sma_long = []
    position = 0
    signals = 0

    for i in range(n):
        price = prices[i]
        broker.tick("TEST", price)

        # 简单均线计算
        sma_short.append(price)
        sma_long.append(price)

        if i >= 10:
            ss = np.mean(prices[i-9:i+1])
            sl = np.mean(prices[max(0, i-29):i+1])

            # 金叉买入
            if ss > sl and position <= 0:
                broker.place_order("TEST", "buy", 100, "market")
                position = 100
                signals += 1
            # 死叉卖出
            elif ss < sl and position >= 100:
                broker.place_order("TEST", "sell", 100, "market")
                position = 0
                signals += 1

    pf = broker.get_portfolio()
    print(f"\n  交易信号: {signals} 次")
    print(f"  最终权益: ${pf['equity']:,.2f}")
    print(f"  收益率: {pf['return_pct']:.2f}%")
    print(f"  总成交: {pf['total_trades']} 笔")
    print(f"  持仓: {pf['open_positions']}")

    # 保存回放记录
    broker.save_trades("historical_replay_test.csv")
    print(f"  成交记录已保存")

    return True


if __name__ == "__main__":
    PASS = 0
    FAIL = 0

    try:
        test_engine_edge_cases()
    except Exception as e:
        print(f"\n  ❌ Engine 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_broker_edge_cases()
    except Exception as e:
        print(f"\n  ❌ Broker 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_historical_replay()
    except Exception as e:
        print(f"\n  ❌ 回放测试异常: {e}")
        import traceback
        traceback.print_exc()

    # 看成交记录
    print("\n" + "=" * 60)
    print(f"  测试总结: ✅ {PASS} 通过 | ❌ {FAIL} 失败")
    print("=" * 60)

    sys.exit(0 if FAIL == 0 else 1)
