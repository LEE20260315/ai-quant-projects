#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 live_tracker_ctp.py 的开仓/平仓/panic 链路"""
import sys
import os

sys.path.insert(0, ".")

from live_tracker_ctp import LiveTrackerCTP

t = LiveTrackerCTP(dry_run=True)

print("--- 测试 1: MA 开多 ---")
t._execute_open("MA", 1, 3049.0, 84.0, None, entry_type="trend")
print()

print("--- 测试 2: MA 平多 ---")
t._execute_close("MA", 3080.0, "manual_test")
print()

print("--- 测试 3: panic 强平 (开 RM 1 手, panic 强平) ---")
t._execute_open("RM", 1, 2240.0, 31.0, None, entry_type="revert")
t.panic_close_all()
print()

print("--- 订单日志 ---")
print(f"  共 {len(t._order_log)} 条订单")
for o in t._order_log:
    print(f"    {o['ts']} {o['action']:5} {o['symbol']:3} {o['ctp_code']:8}.{o['exchange']} {o['direction']} {o['size']}手 @ {o.get('price', 0):.0f} -> broker_id={o['broker_order_id']}")
print()

print("--- broker 视角持仓 ---")
print(f"  positions: {t.broker.query_positions()}")
print(f"  order_log 条数: {len(t.broker.dump_order_log())}")
