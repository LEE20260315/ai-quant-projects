#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Paper Trading 框架配置
========================
"""
import os
from pathlib import Path
from typing import Dict, Tuple


# ==================== 路径 ====================
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent

ORDERS_DB_PATH = str(_THIS_DIR / "orders.db")
LOG_DIR = str(_THIS_DIR)
ARCHIVE_DIR = str(_THIS_DIR / "archive")
EMERGENCY_DIR = str(_THIS_DIR)
WEEKLY_REPORT_DIR = str(_THIS_DIR)
STOP_FLAG_PATH = str(_THIS_DIR / "STOP_PAPER.flag")

for p in (LOG_DIR, ARCHIVE_DIR):
    Path(p).mkdir(parents=True, exist_ok=True)


# ==================== 资金与风控 ====================
INITIAL_CAPITAL = 1_000_000          # 初始资金 100 万（虚拟）

# 4 道风险闸门
PORTFOLIO_STOP_LOSS = 0.12           # 组合止损 12%
LAYER2_TRIGGER = 0.10                # Layer2 10%
SINGLE_STOP_LOSS = 0.15              # 单笔止损 15%
DAILY_RISK_LIMIT = 0.03              # 单日风险 3%

# 期货合约参数（仅保证金与合约乘数）
CONTRACT_PARAMS: Dict[str, Dict] = {
    "RB":  {"margin_per_lot": 3500,   "multiplier": 10,   "tick": 1},
    "I":   {"margin_per_lot": 9000,   "multiplier": 100,  "tick": 0.5},
    "CU":  {"margin_per_lot": 35000,  "multiplier": 5,    "tick": 10},
    "AU":  {"margin_per_lot": 45000,  "multiplier": 1000, "tick": 0.02},
    "AG":  {"margin_per_lot": 9000,   "multiplier": 15,   "tick": 1},
    "NI":  {"margin_per_lot": 20000,  "multiplier": 1,    "tick": 10},
    "Y":   {"margin_per_lot": 4000,   "multiplier": 10,   "tick": 2},
    "P":   {"margin_per_lot": 4000,   "multiplier": 10,   "tick": 2},
    "M":   {"margin_per_lot": 3000,   "multiplier": 10,   "tick": 1},
    "C":   {"margin_per_lot": 2500,   "multiplier": 10,   "tick": 1},
    "SR":  {"margin_per_lot": 3500,   "multiplier": 10,   "tick": 1},
    "CF":  {"margin_per_lot": 5000,   "multiplier": 5,    "tick": 5},
    "TA":  {"margin_per_lot": 3000,   "multiplier": 5,    "tick": 2},
    "MA":  {"margin_per_lot": 2500,   "multiplier": 10,   "tick": 1},
    "FG":  {"margin_per_lot": 3000,   "multiplier": 20,   "tick": 1},
    "SA":  {"margin_per_lot": 4000,   "multiplier": 20,   "tick": 2},
    "RU":  {"margin_per_lot": 12000,  "multiplier": 10,   "tick": 5},
    "BU":  {"margin_per_lot": 4000,   "multiplier": 10,   "tick": 2},
    "FU":  {"margin_per_lot": 4000,   "multiplier": 10,   "tick": 1},
    "IF":  {"margin_per_lot": 130000, "multiplier": 300,  "tick": 0.2},
}


def get_contract_param(symbol: str) -> Dict:
    """获取合约参数（缺省给保守值）"""
    return CONTRACT_PARAMS.get(symbol.upper(), {
        "margin_per_lot": 5000,
        "multiplier": 10,
        "tick": 1,
    })


# ==================== 交易时段 ====================
TRADING_SESSIONS: Tuple[Tuple[int, int], ...] = (
    (9, 0, 11, 30),    # 日盘上午
    (13, 0, 15, 0),    # 日盘下午
)


def in_trading_session(hour: int, minute: int) -> bool:
    """判断 hh:mm 是否在交易时段内"""
    cur = hour * 60 + minute
    for sh, sm, eh, em in TRADING_SESSIONS:
        if sh * 60 + sm <= cur <= eh * 60 + em:
            return True
    return False


# ==================== 轮询与撮合 ====================
POLL_INTERVAL_SEC = 300               # 5 分钟轮询
T1_MATCH = True                       # T+1 撮合（占位）
SLIPPAGE_TICKS = 1                    # 滑点（默认 1 tick）


# ==================== 日志 ====================
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
