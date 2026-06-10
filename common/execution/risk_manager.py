#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
风控与硬熔断（Path 2 / 10X Aggressive Growth）
=========================================

设计要点（来自规划要求）：

  1. 40% 账户回撤 = 硬熔断（自毁线）
     - 权益跌至 6000 元（初始 1 万的 60%）
     - 触发后强制平掉所有头寸并锁定系统

  2. can_trade() 单一真相源
     - 任何执行函数（execute_signal）必须先调用此方法
     - False 状态下任何新开仓请求一律拒绝

  3. 递进式风控
     - 一级（DD >= 20%）: 仓位减半
     - 二级（DD >= 27%）: 禁止开新仓
     - 三级（DD >= 35%）: 现有仓位发出强平建议（旧版逻辑保留, 40% 为新版硬熔断）
     - 硬熔断（DD >= 40%）: 强制平仓 + 锁定
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


class RiskLevel(Enum):
    NORMAL = "normal"
    LEVEL1_HALF = "level1_half"            # 20% ~ 27%
    LEVEL2_NO_NEW = "level2_no_new"        # 27% ~ 35%
    LEVEL3_CLOSE = "level3_close"          # 35% ~ 40%
    HARDBREAK_TRIP = "hardbreak_trip"      # >= 40% — 硬熔断


@dataclass
class RiskConfig:
    initial_equity: float = 10_000.0
    hardbreak_drawdown: float = 0.40       # 硬熔断线
    level1_dd: float = 0.20
    level2_dd: float = 0.27
    level3_dd: float = 0.35
    max_positions: int = 3
    consecutive_loss_limit: int = 6         # 连亏暂停开仓


@dataclass
class AccountSnapshot:
    """风控模块关心的最小账户状态"""
    capital: float
    peak_capital: float
    positions: Dict[str, dict] = field(default_factory=dict)
    trade_log: List[dict] = field(default_factory=list)

    @property
    def drawdown(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.capital) / self.peak_capital

    @property
    def total_equity(self) -> float:
        unrealized = 0.0
        for pos in self.positions.values():
            # 简化: 用 entry_price 估算, 实盘由 execution_engine 注入当前价
            unrealized += pos.get("unrealized_pnl", 0.0)
        return self.capital + unrealized

    @property
    def equity_peak(self) -> float:
        # 优先用外部注入的 equity_peak
        if "equity_peak" in self.positions and isinstance(self.positions.get("equity_peak"), (int, float)):
            return self.positions["equity_peak"]
        return self.peak_capital

    @property
    def equity_drawdown(self) -> float:
        peak = self.equity_peak
        if peak <= 0:
            return 0.0
        return (peak - self.total_equity) / peak

    @property
    def consecutive_losses(self) -> int:
        n = 0
        for t in reversed(self.trade_log):
            if t.get("pnl", 0) < 0:
                n += 1
            else:
                break
        return n


class RiskManager:
    """
    单一真相源风控模块。

    用法::

        rm = RiskManager()
        rm.update_snapshot(snapshot)            # 推一次当前账户状态
        if not rm.can_trade():
            logger.warning("Risk limit reached. Operation aborted.")
            return
        if rm.is_hardbreak:
            rm.force_close_all()                # 触发硬熔断: 强平
    """

    def __init__(self, config: Optional[RiskConfig] = None, logger: Optional[logging.Logger] = None):
        self.config = config or RiskConfig()
        self.logger = logger or logging.getLogger(__name__)
        self._snapshot: Optional[AccountSnapshot] = None
        self._tripped = False                 # 硬熔断已触发 → 锁定
        self._trip_history: List[dict] = []    # 触发历史
        # 强平回调: 由 execution_engine 注入, 返回 list of closed symbols
        self._force_close_hook: Optional[Callable[[], List[str]]] = None

    # ------------------------------------------------- 状态注入
    def attach_snapshot(self, snapshot: AccountSnapshot) -> None:
        self._snapshot = snapshot
        # 推送后即评估一次, 触发硬熔断
        if self.is_hardbreak and not self._tripped:
            self._trip_hardbreak()

    def register_force_close_hook(self, hook: Callable[[], List[str]]) -> None:
        """注册一个可被强制调用的"全平"函数, 由 execution_engine 注入"""
        self._force_close_hook = hook

    # ------------------------------------------------- 核心 API
    @property
    def current_drawdown(self) -> float:
        """返回权益回撤 (基于 capital 的 DD, 同时也参考 equity DD 取较大值)"""
        if self._snapshot is None:
            return 0.0
        return max(self._snapshot.drawdown, self._snapshot.equity_drawdown)

    @property
    def risk_level(self) -> RiskLevel:
        if self._tripped:
            return RiskLevel.HARDBREAK_TRIP
        dd = self.current_drawdown
        if dd >= self.config.hardbreak_drawdown:
            return RiskLevel.HARDBREAK_TRIP
        if dd >= self.config.level3_dd:
            return RiskLevel.LEVEL3_CLOSE
        if dd >= self.config.level2_dd:
            return RiskLevel.LEVEL2_NO_NEW
        if dd >= self.config.level1_dd:
            return RiskLevel.LEVEL1_HALF
        return RiskLevel.NORMAL

    @property
    def is_hardbreak(self) -> bool:
        return self.current_drawdown >= self.config.hardbreak_drawdown

    def can_trade(self) -> bool:
        """
        单一真相：所有新开仓 / 加仓请求必须先通过此判断。
        """
        if self._tripped:
            self.logger.warning(
                "RiskManager: 系统已硬熔断, 拒绝一切新开仓."
            )
            return False
        if self.is_hardbreak:
            self._trip_hardbreak()
            return False
        lvl = self.risk_level
        if lvl == RiskLevel.LEVEL2_NO_NEW:
            self.logger.warning("RiskManager: 二级风控 DD>=27%s, 禁止开新仓.", "%")
            return False
        if lvl == RiskLevel.LEVEL3_CLOSE:
            self.logger.warning("RiskManager: 三级风控 DD>=35%%, 禁止开新仓.")
            return False

        # 连亏暂停
        if self._snapshot and self._snapshot.consecutive_losses >= self.config.consecutive_loss_limit:
            self.logger.warning(
                "RiskManager: 连续亏损 %d 笔, 暂停开仓.",
                self._snapshot.consecutive_losses,
            )
            return False

        # 持仓数上限
        if self._snapshot and len(self._snapshot.positions) >= self.config.max_positions:
            self.logger.warning(
                "RiskManager: 持仓数 %d 已达上限 %d.",
                len(self._snapshot.positions), self.config.max_positions,
            )
            return False

        return True

    def position_size_multiplier(self) -> float:
        """返回仓位折扣系数 (执行引擎会乘到 PositionSizer 的结果上)"""
        if self._tripped or self.is_hardbreak:
            return 0.0
        lvl = self.risk_level
        if lvl == RiskLevel.LEVEL1_HALF:
            return 0.5
        if lvl == RiskLevel.LEVEL2_NO_NEW:
            return 0.0
        if lvl == RiskLevel.LEVEL3_CLOSE:
            return 0.0
        return 1.0

    # ------------------------------------------------- 硬熔断
    def _trip_hardbreak(self) -> None:
        self._tripped = True
        msg = (
            f"[HARDBREAK] 账户回撤 {self.current_drawdown:.1%} >= "
            f"{self.config.hardbreak_drawdown:.0%}, 触发硬熔断. "
            f"权益 {self._snapshot.capital if self._snapshot else 'NA'} 元"
        )
        self.logger.critical(msg)
        self._trip_history.append({
            "ts": __import__("datetime").datetime.now().isoformat(),
            "dd": self.current_drawdown,
            "equity": self._snapshot.capital if self._snapshot else None,
        })
        if self._force_close_hook is not None:
            try:
                closed = self._force_close_hook() or []
                self.logger.critical("[HARDBREAK] 已强平 %d 个持仓: %s", len(closed), closed)
            except Exception as e:
                self.logger.exception("[HARDBREAK] 强平回调失败: %s", e)

    def force_close_all(self) -> List[str]:
        """显式触发强平, 可由外部 (如移动端) 主动调用"""
        self._tripped = True
        if self._force_close_hook is None:
            self.logger.warning("[HARDBREAK] 未注册强平回调, 仅锁定系统.")
            return []
        return self._force_close_hook()

    def reset_trip(self) -> None:
        """仅用于运维恢复 —— 不应在生产路径中调用"""
        self.logger.warning("RiskManager: 人工解除硬熔断, 重新接受开仓.")
        self._tripped = False

    @property
    def trip_history(self) -> List[dict]:
        return list(self._trip_history)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = RiskConfig()
    rm = RiskManager(cfg)

    # 1) 正常: equity=10_000, peak=10_000 -> can_trade=True
    rm.attach_snapshot(AccountSnapshot(capital=10_000, peak_capital=10_000))
    print("normal:", rm.can_trade(), "dd=", rm.current_drawdown)

    # 2) 一级: DD=22% -> can_trade=True, 仓位 0.5x
    rm.attach_snapshot(AccountSnapshot(capital=7_800, peak_capital=10_000))
    print("L1:", rm.can_trade(), "dd=", rm.current_drawdown, "mult=", rm.position_size_multiplier())

    # 3) 二级: DD=30% -> can_trade=False
    rm.attach_snapshot(AccountSnapshot(capital=7_000, peak_capital=10_000))
    print("L2:", rm.can_trade(), "dd=", rm.current_drawdown)

    # 4) 硬熔断: DD=42% -> 自动 trip
    rm = RiskManager(cfg)
    closed = []
    rm.register_force_close_hook(lambda: (closed.append("TA") or closed))
    rm.attach_snapshot(AccountSnapshot(capital=5_800, peak_capital=10_000))
    print("hardbreak:", rm.can_trade(), "dd=", rm.current_drawdown, "tripped=", rm._tripped, "closed=", closed)
    print("again can_trade:", rm.can_trade())
