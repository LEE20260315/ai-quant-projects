#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""恢复 state.json 到 5/11 那个 TA 浮盈仓的状态 (清掉测试副作用)"""
import json
import os

STATE = r"C:\Users\MR.Dong\OneDrive\My Project\ai-quant-projects-merged\path2_lightweight\tracking\tracker_state.json"
ORDER_LOG = r"C:\Users\MR.Dong\OneDrive\My Project\ai-quant-projects-merged\path2_lightweight\tracking\ctp_order_log.json"

# 1) 恢复 state: capital=10000, TA 仓在场
state = {
    "capital": 10000,
    "peak_capital": 10000,
    "positions": {
        "TA": {
            "direction": 1,
            "entry_price": 6338.0,
            "entry_date": "2026-05-09",
            "size": 1,
            "stop_loss": 5998.57,
            "take_profit": 6809.43,
            "max_hold_days": 10,
            "margin_used": 1901.4,
            "fusion": "no_path1_signal",
            "dominant_strategy": "none",
        }
    },
    "trade_log": [],
    "daily_log": [
        {"date": "2026-04-27", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-04-28", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-04-29", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-04-30", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-01", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-04", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-05", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-06", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-07", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-08", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 0},
        {"date": "2026-05-09", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 1},
        {"date": "2026-05-11", "capital": 10000, "drawdown": 0.0, "return_pct": 0.0, "positions": 1},
    ],
    "start_date": "2026-04-23",
    "version": "v1.2",
}

with open(STATE, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2, default=str)
print(f"✅ state.json 已恢复 (TA 仓在场)")

# 2) 清掉 ctp_order_log.json (测试副作用)
if os.path.exists(ORDER_LOG):
    os.remove(ORDER_LOG)
    print(f"✅ ctp_order_log.json 已清空 (测试副作用)")
