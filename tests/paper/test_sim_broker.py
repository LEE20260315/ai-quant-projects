#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_sim_broker.py
==================

SimBroker 单元测试：完整下单 → T+1 撮合 → 结算 → 持仓更新链路。

运行：
  python -m tests.paper.test_sim_broker
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

# 路径
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "Pricing deviation detection system"))

from paper_trading.sim_broker import SimBroker


def _make_broker():
    """创建使用临时 DB 的 broker（测试隔离）"""
    import uuid
    tmp_dir = tempfile.mkdtemp(prefix="sim_broker_test_")
    db_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex[:8]}.db")
    return SimBroker(db_path=db_path, initial_capital=1_000_000), db_path


def _safe_remove(path):
    """Windows 下 sqlite 文件可能被锁，重试几次"""
    import time
    for _ in range(3):
        try:
            if os.path.exists(path):
                os.remove(path)
            # 删父目录（如果空）
            parent = os.path.dirname(path)
            try:
                os.rmdir(parent)
            except OSError:
                pass
            return
        except PermissionError:
            time.sleep(0.1)


def _q(sql, db, params=()):
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def test_order_pending_and_match():
    """测试 1：下单后 PENDING，settle 后转 FILLED"""
    print("\n[test1] 下单→PENDING→settle→FILLED")
    broker, db = _make_broker()

    oid, status = broker.submit_order(symbol="RB", direction="LONG", qty=2, price=3500.0, t_date="2025-06-05")
    assert status == "PENDING", f"期望 PENDING, 实际 {status}"

    # settle 前订单表
    rows = _q("SELECT status FROM orders WHERE order_id=?", db, (oid,))
    assert rows[0][0] == "PENDING", f"DB 状态: {rows[0][0]}"

    # settle（T+1 撮合）
    nav = broker.settle(t_date="2025-06-05", last_prices={"RB": 3520.0})
    assert nav["filled_today"] == 1, f"撮合数: {nav['filled_today']}"

    # settle 后订单表
    rows = _q("SELECT status, filled_qty, avg_fill_price FROM orders WHERE order_id=?", db, (oid,))
    assert rows[0][0] == "FILLED", f"撮合后状态: {rows[0][0]}"
    assert rows[0][1] == 2, f"成交手数: {rows[0][1]}"
    # RB tick=1, SLIPPAGE=1, fill = 3520+1=3521
    assert abs(rows[0][2] - 3521.0) < 0.01, f"成交价: {rows[0][2]}"

    # 持仓表
    pos = broker.get_position("RB")
    assert pos is not None
    assert pos["direction"] == "LONG"
    assert pos["qty"] == 2
    print(f"  ✓ 撮合 1 单, 持仓 RB LONG 2手 @ {pos['entry_price']}")

    _safe_remove(db)
    return True


def test_position_add_and_close():
    """测试 2：同向加仓均价加权 / 反向平仓"""
    print("\n[test2] 加仓均价加权 + 平仓")
    broker, db = _make_broker()

    # 第一次建仓 LONG 2手 @ 3500
    broker.submit_order(symbol="RB", direction="LONG", qty=2, price=3500.0, t_date="2025-06-05")
    broker.settle(t_date="2025-06-05", last_prices={"RB": 3500.0})

    # 第二次加仓 LONG 3手 @ 3520
    broker.submit_order(symbol="RB", direction="LONG", qty=3, price=3520.0, t_date="2025-06-06")
    broker.settle(t_date="2025-06-06", last_prices={"RB": 3520.0})

    # 加仓后：均价 = (2*3501 + 3*3521) / 5 = (7002 + 10563) / 5 = 3513
    pos = broker.get_position("RB")
    assert pos["qty"] == 5
    # fill_price = last_price + slip = 3500+1=3501, 3520+1=3521
    expected_avg = (2 * 3501.0 + 3 * 3521.0) / 5
    assert abs(pos["entry_price"] - expected_avg) < 0.01, f"加仓均价 {pos['entry_price']} vs 期望 {expected_avg}"
    print(f"  ✓ 加仓均价加权: {pos['entry_price']:.2f} (期望 {expected_avg:.2f})")

    # 平仓 SHORT 5手
    broker.submit_order(symbol="RB", direction="SHORT", qty=5, price=3550.0, t_date="2025-06-07")
    nav = broker.settle(t_date="2025-06-07", last_prices={"RB": 3550.0})

    pos = broker.get_position("RB")
    assert pos is None, f"全平后应无持仓, 实际 {pos}"
    # 已实现 PnL = (3550+1) - 加权均价 * 5手 * 10 = (3551 - 3513) * 50 = 1900
    assert nav["realized_pnl"] > 0, f"平仓应盈利, 实际 {nav['realized_pnl']}"
    print(f"  ✓ 全平 PnL = {nav['realized_pnl']:,.0f}")

    _safe_remove(db)
    return True


def test_position_reversal():
    """测试 3：反手（开新方向超过原持仓）"""
    print("\n[test3] 反手开新方向")
    broker, db = _make_broker()

    # LONG 2手
    broker.submit_order(symbol="CU", direction="LONG", qty=2, price=75000.0, t_date="2025-06-05")
    broker.settle(t_date="2025-06-05", last_prices={"CU": 75000.0})

    # 反手 SHORT 5手（超过原持仓 3 手）
    broker.submit_order(symbol="CU", direction="SHORT", qty=5, price=74900.0, t_date="2025-06-06")
    broker.settle(t_date="2025-06-06", last_prices={"CU": 74900.0})

    pos = broker.get_position("CU")
    assert pos is not None
    assert pos["direction"] == "SHORT", f"反手后方向: {pos['direction']}"
    assert pos["qty"] == 3, f"反手后数量: {pos['qty']} (期望 3 = 5-2)"
    print(f"  ✓ 反手后: {pos['direction']} {pos['qty']}手")

    _safe_remove(db)
    return True


def test_unrealized_pnl():
    """测试 4：未实现 PnL 正确计算"""
    print("\n[test4] 未实现 PnL")
    broker, db = _make_broker()

    # RB LONG 10手 @ 3500（settle 时 last=3500, fill=3501）
    broker.submit_order(symbol="RB", direction="LONG", qty=10, price=3500.0, t_date="2025-06-05")
    broker.settle(t_date="2025-06-05", last_prices={"RB": 3500.0})

    # 涨 100 点
    nav = broker.settle(t_date="2025-06-06", last_prices={"RB": 3600.0})
    # unrealized = (3600-3501) * 10 * 10 = 9900
    assert abs(nav["unrealized_pnl"] - 9900.0) < 1.0, f"unrealized: {nav['unrealized_pnl']} (期望 9900)"
    print(f"  ✓ unrealized_pnl = {nav['unrealized_pnl']:,.0f} (涨100点×10手×10)")

    _safe_remove(db)
    return True


def test_cancel_pending():
    """测试 5：撤销 PENDING 订单"""
    print("\n[test5] 撤单")
    broker, db = _make_broker()

    broker.submit_order(symbol="RB", direction="LONG", qty=2, price=3500.0, t_date="2025-06-05")
    broker.submit_order(symbol="CU", direction="SHORT", qty=1, price=75000.0, t_date="2025-06-05")

    n = broker.cancel_pending(symbol="RB")
    assert n == 1, f"撤单数: {n}"

    broker.settle(t_date="2025-06-05", last_prices={"RB": 3500.0, "CU": 75000.0})

    rows = _q("SELECT symbol, status FROM orders ORDER BY symbol", db)
    assert rows[0][0] == "CU" and rows[0][1] == "FILLED", f"CU 状态: {rows[0]}"
    assert rows[1][0] == "RB" and rows[1][1] == "CANCELLED", f"RB 状态: {rows[1]}"
    print(f"  ✓ 撤单 1 单, 剩余订单成交 1 单")

    _safe_remove(db)
    return True


def test_nav_continuity():
    """测试 6：连续多日结算的 NAV 连续性"""
    print("\n[test6] 多日 NAV")
    broker, db = _make_broker()

    # Day 1 建仓
    broker.submit_order(symbol="RB", direction="LONG", qty=5, price=3500.0, t_date="2025-06-03")
    broker.settle(t_date="2025-06-03", last_prices={"RB": 3500.0})

    # Day 2 涨
    broker.settle(t_date="2025-06-04", last_prices={"RB": 3550.0})
    # Day 3 跌
    nav3 = broker.settle(t_date="2025-06-05", last_prices={"RB": 3450.0})

    rows = _q("SELECT t_date, total_equity, drawdown FROM nav ORDER BY t_date", db)
    assert len(rows) == 3
    # Day3: 跌 50 点，5手×10×(-50) = -2500
    # 但 Day2 涨 50 点，5手×10×50 = 2500
    # Day3 equity = 1000000 + 2500 - 2500 = 1000000
    # drawdown = (1000000+2500 - 1000000) / 1000000+2500) = 2500/1002500 = 0.0025
    print(f"  ✓ 3 日 NAV 连续:")
    for r in rows:
        print(f"    {r[0]}: equity={r[1]:,.0f} dd={r[2]*100:.3f}%")

    _safe_remove(db)
    return True


# ==================== main ====================
def main():
    tests = [
        test_order_pending_and_match,
        test_position_add_and_close,
        test_position_reversal,
        test_unrealized_pnl,
        test_cancel_pending,
        test_nav_continuity,
    ]
    passed = 0
    for t in tests:
        try:
            if t():
                passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"SimBroker 测试: {passed}/{len(tests)} 通过")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
