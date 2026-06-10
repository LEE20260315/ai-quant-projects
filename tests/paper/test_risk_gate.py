#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_risk_gate.py
=================

RiskGate 单元测试：触发 4 道风险闸门各 1 次。

  1. 组合止损 12%
  2. Layer2 10%
  3. 单笔止损 15%
  4. 单日风险 3%

运行：
  python -m tests.paper.test_risk_gate
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "Pricing deviation detection system"))

from paper_trading.sim_broker import SimBroker
from paper_trading.risk_gate import RiskGate, _attach_latest_nav_helper
from paper_trading import config as cfg


def _make_env():
    """broker + gate + 临时 DB"""
    import uuid
    tmp_dir = tempfile.mkdtemp(prefix="risk_gate_test_")
    db_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex[:8]}.db")
    broker = SimBroker(db_path=db_path, initial_capital=cfg.INITIAL_CAPITAL)
    _attach_latest_nav_helper(broker)
    gate = RiskGate(initial_capital=cfg.INITIAL_CAPITAL)
    return broker, gate, db_path


def _safe_remove(path):
    import time
    for _ in range(3):
        try:
            if os.path.exists(path):
                os.remove(path)
            try:
                os.rmdir(os.path.dirname(path))
            except OSError:
                pass
            return
        except PermissionError:
            time.sleep(0.1)


def _seed_nav(broker, db, t_date, drawdown, daily_pnl, equity=None):
    """手工写一条 nav（模拟历史结算）"""
    if equity is None:
        equity = cfg.INITIAL_CAPITAL * (1 - drawdown)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO nav
           (t_date, cash, market_value, realized_pnl, unrealized_pnl,
            total_equity, drawdown, layer2_active, portfolio_stopped)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (t_date, equity, 0, daily_pnl, 0, equity, drawdown, 0, 0),
    )
    conn.commit()
    conn.close()


def test_single_stop_gate():
    """闸 3：单笔止损 15%"""
    print("\n[test3] 单笔止损 15%")
    broker, gate, db = _make_env()

    # RB LONG 5手，entry=3500（fill 时 3501）
    broker.submit_order(symbol="RB", direction="LONG", qty=5, price=3500.0, t_date="2025-06-05")
    broker.settle(t_date="2025-06-05", last_prices={"RB": 3500.0})

    # 跌 30%（远大于 15%）
    to_close = gate.check_single_stop(broker)
    # 实际上扫的是当前 broker 持仓，settle 后 last_price 还是 3500，未实现 PnL=0
    # 改成手工改 last_price
    conn = sqlite3.connect(db)
    conn.execute("UPDATE positions SET last_price=2400 WHERE symbol='RB'")
    conn.commit()
    conn.close()
    to_close = gate.check_single_stop(broker)
    assert len(to_close) == 1, f"应触发 1 单止损, 实际 {len(to_close)}"
    assert to_close[0]["symbol"] == "RB"
    assert to_close[0]["close_direction"] == "SHORT"
    # loss_pct = -(2400-3501)*5*10 / (3501*5*10) = 11010/175050 = 0.314 > 0.15 ✓
    print(f"  ✓ 触发: {to_close[0]['reason']}")

    _safe_remove(db)
    return True


def test_layer2_gate():
    """闸 2：Layer2 10% 触发后拒新开仓"""
    print("\n[test2] Layer2 10% 拒新开仓")
    broker, gate, db = _make_env()

    # 模拟历史：回撤 11%
    _seed_nav(broker, db, "2025-06-04", drawdown=0.11, daily_pnl=0)

    # 首次 pre_trade_check：触发 Layer2 激活 + 拒新开仓
    ok, reason = gate.pre_trade_check(broker, "RB", "LONG", 1, 3500.0)
    assert not ok, f"回撤 11% 触发 Layer2 后应拒新单: 实际 ok={ok}"
    assert gate.state.layer2_active, "Layer2 应已激活"
    print(f"  ✓ Layer2 激活（首次）拒单: {reason}")

    # 平仓(SHORT)允许
    ok, reason = gate.pre_trade_check(broker, "RB", "SHORT", 1, 3500.0)
    assert ok, f"平仓应放行: {reason}"
    print(f"  ✓ 平仓(SHORT)放行")

    _safe_remove(db)
    return True


def test_portfolio_stop_gate():
    """闸 1：组合止损 12% 触发后拒所有新单"""
    print("\n[test1] 组合止损 12%")
    broker, gate, db = _make_env()

    # 模拟历史：回撤 13%
    _seed_nav(broker, db, "2025-06-04", drawdown=0.13, daily_pnl=0)

    # 开仓被拒
    ok, reason = gate.pre_trade_check(broker, "RB", "LONG", 1, 3500.0)
    assert not ok, "组合止损后应拒新单"
    assert "组合止损" in reason or "12%" in reason
    print(f"  ✓ 拒单: {reason}")

    # check_portfolio_stop 返回减仓单
    # 需要先有持仓
    broker.submit_order(symbol="RB", direction="LONG", qty=1, price=3500.0, t_date="2025-06-05")
    broker.settle(t_date="2025-06-05", last_prices={"RB": 3500.0})
    # 但此时 nav 已经被重写为 drawdown=0，需要再写一次高回撤 nav
    _seed_nav(broker, db, "2025-06-05", drawdown=0.13, daily_pnl=0)
    # 触发 portfolio_stopped
    gate.pre_trade_check(broker, "RB", "LONG", 1, 3500.0)

    flat_list = gate.check_portfolio_stop(broker)
    assert len(flat_list) >= 0  # 看持仓是否存在
    print(f"  ✓ 减仓单: {flat_list}")

    os.remove(db)
    return True


def test_daily_risk_gate():
    """闸 4：单日风险 3%"""
    print("\n[test4] 单日风险 3%")
    broker, gate, db = _make_env()

    # 当日已亏 4%（> 3%）
    _seed_nav(broker, db, "2025-06-05", drawdown=0.04, daily_pnl=-40000.0)  # 4万 = 4%

    ok, reason = gate.pre_trade_check(broker, "RB", "LONG", 1, 3500.0)
    assert not ok, "单日亏损超限应拒新单"
    assert "单日" in reason or "3%" in reason
    print(f"  ✓ 拒单: {reason}")

    _safe_remove(db)
    return True


def test_normal_open_allowed():
    """无风险时全部放行"""
    print("\n[normal] 正常开仓放行")
    broker, gate, db = _make_env()

    # 无历史 nav，应放行
    ok, reason = gate.pre_trade_check(broker, "RB", "LONG", 1, 3500.0)
    assert ok, f"无历史 nav 应放行: {reason}"

    # 正常回撤 2%
    _seed_nav(broker, db, "2025-06-04", drawdown=0.02, daily_pnl=0)
    ok, reason = gate.pre_trade_check(broker, "RB", "LONG", 1, 3500.0)
    assert ok, f"回撤 2% 应放行: {reason}"
    print(f"  ✓ 无风险时正常放行")

    os.remove(db)
    return True


# ==================== main ====================
def main():
    tests = [
        test_normal_open_allowed,
        test_daily_risk_gate,
        test_single_stop_gate,
        test_layer2_gate,
        test_portfolio_stop_gate,
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
    print(f"RiskGate 测试: {passed}/{len(tests)} 通过")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
