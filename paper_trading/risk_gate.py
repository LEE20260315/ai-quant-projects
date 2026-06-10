#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
4 道风险闸门
================

  1. 组合止损 12%  → 拒所有新单 + 触发减仓
  2. Layer2 10%    → 拒新敞口（仅允许平仓）
  3. 单笔止损 15%  → 自动生成平仓单
  4. 单日风险 3%   → 当日拒新单

每个闸门可独立启用/禁用。
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import config as cfg


logger = logging.getLogger("paper_trading.risk_gate")


@dataclass
class RiskState:
    layer2_active: bool = False
    portfolio_stopped: bool = False
    daily_realized_loss: float = 0.0    # 当日已实现亏损（元）


class RiskGate:
    """4 道风险闸门（pre-trade + post-position check）"""

    def __init__(self,
                 portfolio_stop: float = cfg.PORTFOLIO_STOP_LOSS,
                 layer2: float = cfg.LAYER2_TRIGGER,
                 single_stop: float = cfg.SINGLE_STOP_LOSS,
                 daily_limit: float = cfg.DAILY_RISK_LIMIT,
                 initial_capital: float = cfg.INITIAL_CAPITAL):
        self.portfolio_stop = portfolio_stop
        self.layer2 = layer2
        self.single_stop = single_stop
        self.daily_limit = daily_limit
        self.initial_capital = initial_capital
        self.state = RiskState()

    # ------------------- 下单前 -------------------
    def pre_trade_check(self, broker, symbol: str, direction: str, qty: int, price: float) -> Tuple[bool, str]:
        """
        下单前检查：4 道闸门任意一道拒绝即返回 (False, reason)
        """
        nav = broker._latest_nav() if hasattr(broker, "_latest_nav") else None
        if nav is None:
            return True, ""  # 没历史 nav 不挡

        equity = nav["total_equity"]
        drawdown = nav["drawdown"]
        daily_pnl = nav.get("realized_pnl", 0)  # 负值表示亏损

        # 闸 1：组合止损
        if drawdown >= self.portfolio_stop or self.state.portfolio_stopped:
            self.state.portfolio_stopped = True
            return False, f"组合止损触发：回撤 {drawdown*100:.2f}% ≥ {self.portfolio_stop*100:.0f}%"

        # 闸 2：Layer2（拒新敞口）
        if drawdown >= self.layer2 and not self.state.layer2_active:
            self.state.layer2_active = True
            logger.warning(f"[Layer2 激活] 回撤 {drawdown*100:.2f}% ≥ {self.layer2*100:.0f}%")

        # 闸 4：单日风险（仅对新开仓）
        if direction == "LONG" and daily_pnl < -self.initial_capital * self.daily_limit:
            return False, f"单日亏损已 ≥ {self.daily_limit*100:.0f}% 初始资金，今日拒新单"

        # Layer2 后只能平仓
        if self.state.layer2_active and direction == "LONG":
            return False, "Layer2 已激活，今日拒新开仓（仅允许平仓）"

        return True, ""

    # ------------------- 持仓检查（单笔止损）-------------------
    def check_single_stop(self, broker) -> List[Dict]:
        """
        扫描所有持仓，对触发单笔止损的品种返回待平仓单
        """
        result: List[Dict] = []
        for p in broker.list_open_positions():
            params = cfg.get_contract_param(p["symbol"])
            diff = (p["last_price"] - p["entry_price"]) * p["qty"] * params["multiplier"]
            if p["direction"] == "SHORT":
                diff = -diff
            loss_pct = -diff / (p["entry_price"] * p["qty"] * params["multiplier"]) if p["entry_price"] > 0 else 0
            if loss_pct >= self.single_stop:
                result.append({
                    "symbol": p["symbol"],
                    "qty": p["qty"],
                    "reason": f"单笔止损 {loss_pct*100:.1f}% ≥ {self.single_stop*100:.0f}%",
                    "close_direction": "SHORT" if p["direction"] == "LONG" else "LONG",
                })
        return result

    # ------------------- 组合止损后减仓 -------------------
    def check_portfolio_stop(self, broker) -> List[Dict]:
        """组合止损触发时返回所有持仓的市价平仓单"""
        nav = broker._latest_nav() if hasattr(broker, "_latest_nav") else None
        if nav is None or nav["drawdown"] < self.portfolio_stop:
            return []
        if not self.state.portfolio_stopped:
            return []
        result = []
        for p in broker.list_open_positions():
            result.append({
                "symbol": p["symbol"],
                "qty": p["qty"],
                "reason": f"组合止损减仓（回撤 {nav['drawdown']*100:.1f}%）",
                "close_direction": "SHORT" if p["direction"] == "LONG" else "LONG",
            })
        return result

    # ------------------- 日初重置 -------------------
    def reset_daily(self):
        self.state.daily_realized_loss = 0.0


# 为 sim_broker 加一个辅助方法（避免在 broker 文件改动太多）
def _attach_latest_nav_helper(broker):
    """给 broker 加 _latest_nav 方法（从 nav 表读最后一条）"""
    if hasattr(broker, "_latest_nav"):
        return broker
    import sqlite3
    def _latest_nav(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT t_date, cash, market_value, realized_pnl, unrealized_pnl, total_equity, drawdown FROM nav ORDER BY t_date DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "t_date": row[0], "cash": row[1], "market_value": row[2],
            "realized_pnl": row[3], "unrealized_pnl": row[4],
            "total_equity": row[5], "drawdown": row[6],
        }
    import types
    broker._latest_nav = types.MethodType(_latest_nav, broker)
    return broker
