#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
仓位引擎（Path 2 / 10X Aggressive Growth）
=====================================

核心公式（来自《10X Aggressive Growth》规划）：

    Total_Lots = floor((Current_Equity - 10000) / 5000) + 2

含义：
  - 起步 2 手（账户 1 万元时，保证金利用率约 50%）
  - 每多 5000 元盈利, 自动 +1 手规模
  - 复利增长靠 "加仓幅度随权益同步放大" 实现

设计原则：
  * 单品种先到上限（避免单品种超押）
  * 总手数不超品种池容量 × 单品种上限
  * 遇连续亏损自动降档（30%/50% 折损系数）
  * 与 RiskManager 解耦 —— 本类只回答 "该下几手"
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional

# 继承 common 的 BaseSizer (跨 path 共享)
_COMMON_EXEC = os.path.join(os.path.dirname(__file__), "..", "..", "common", "execution")
if _COMMON_EXEC not in sys.path:
    sys.path.insert(0, _COMMON_EXEC)
from base_sizer import BaseSizer, SizerDecision as _CommonSizerDecision  # noqa: E402


# ====== 默认参数（可在构造时覆盖） ============================================
DEFAULT_BASE_EQUITY = 10_000.0        # 起步权益
DEFAULT_STEP_EQUITY = 5_000.0         # 每加一手所需盈利
DEFAULT_BASE_LOTS = 2                 # 起步手数
DEFAULT_MAX_LOTS_PER_SYMBOL = 3       # 单品种最大手数
DEFAULT_MAX_TOTAL_LOTS = 6            # 三个品种总手数上限
DEFAULT_LOSS_STREAK_REDUCE = 3        # 连续亏损 3 笔触发降档


@dataclass
class SizerConfig:
    base_equity: float = DEFAULT_BASE_EQUITY
    step_equity: float = DEFAULT_STEP_EQUITY
    base_lots: int = DEFAULT_BASE_LOTS
    max_lots_per_symbol: int = DEFAULT_MAX_LOTS_PER_SYMBOL
    max_total_lots: int = DEFAULT_MAX_TOTAL_LOTS
    loss_streak_reduce: int = DEFAULT_LOSS_STREAK_REDUCE


# 兼容: 仍导出本地的 SizerDecision, 同时其字段与 common 的兼容
@dataclass
class SizerDecision(_CommonSizerDecision):
    """Path 2 仓位决策 (兼容 common.base_sizer.SizerDecision, 多 raw_lots 字段)"""
    raw_lots: int = 0
    multiplier: float = 1.0

    def __post_init__(self):
        # 不调父类 __post_init__, 因为它会要求 extras
        pass


class PositionSizer(BaseSizer):
    """
    权益阶梯加仓仓位引擎 (Path 2 专用 / 10X 激进)

    用法::

        sizer = PositionSizer()
        decision = sizer.calc_lots(
            symbol="TA",
            account_equity=15800.0,
            consecutive_losses=0,
        )
        # decision.lots == 4 ( = floor((15800-10000)/5000) + 2 )
    """

    def __init__(self, config: Optional[SizerConfig] = None):
        self.config = config or SizerConfig()
        # 记录每个品种当前在手手数, 防止重复加仓
        self.holdings: Dict[str, int] = {}

    # ------------------------------------------------------------------ 核心
    def calc_lots(
        self,
        symbol: str,
        account_equity: float,
        consecutive_losses: int = 0,
        **ctx,
    ) -> SizerDecision:
        """
        返回建议手数 (兼容 BaseSizer 接口)
        """
        cfg = self.config

        # 1) 原始公式手数
        if account_equity <= cfg.base_equity:
            raw_lots = cfg.base_lots
        else:
            raw_lots = cfg.base_lots + int(
                math.floor((account_equity - cfg.base_equity) / cfg.step_equity)
            )

        # 2) 连续亏损降档
        multiplier = 1.0
        reason_parts = [f"raw={raw_lots}"]
        if consecutive_losses >= cfg.loss_streak_reduce * 2:
            multiplier = 0.5
            reason_parts.append("连亏>=6, 折50%")
        elif consecutive_losses >= cfg.loss_streak_reduce:
            multiplier = 0.7
            reason_parts.append(f"连亏>={cfg.loss_streak_reduce}, 折30%")

        scaled = max(1, int(math.floor(raw_lots * multiplier)))

        # 3) 单品种上限
        already_held = self.holdings.get(symbol, 0)
        per_symbol_cap = max(1, cfg.max_lots_per_symbol)
        room_left = max(0, per_symbol_cap - already_held)
        final = min(scaled, room_left) if room_left > 0 else 0

        if final < scaled and scaled > 0:
            reason_parts.append(f"单品种上限{per_symbol_cap}手,已持{already_held}")

        # 4) 总手数上限
        total_now = sum(self.holdings.values())
        room_total = max(0, cfg.max_total_lots - total_now)
        if final > room_total:
            final = room_total
            reason_parts.append(f"总手数上限{cfg.max_total_lots},已用{total_now}")

        return SizerDecision(
            lots=final,
            raw_lots=raw_lots,
            reason=" | ".join(reason_parts),
            multiplier=multiplier,
        )

    # --------------------------------------------------------- 状态簿记
    def on_open(self, symbol: str, lots: int) -> None:
        self.holdings[symbol] = self.holdings.get(symbol, 0) + lots

    def on_close(self, symbol: str, lots: int) -> None:
        cur = self.holdings.get(symbol, 0)
        self.holdings[symbol] = max(0, cur - lots)
        if self.holdings[symbol] == 0:
            self.holdings.pop(symbol, None)

    def sync_from_positions(self, positions: Dict[str, dict]) -> None:
        """从外部 position 字典（symbol -> {size, ...}）重新同步"""
        self.holdings = {sym: int(p.get("size", 0)) for sym, p in positions.items() if int(p.get("size", 0)) > 0}

    # ---------------------------------------------------- 内部辅助/测试
    def lots_from_formula(self, equity: float) -> int:
        """公式独立可调用, 便于单元测试"""
        if equity <= self.config.base_equity:
            return self.config.base_lots
        return self.config.base_lots + int(
            math.floor((equity - self.config.base_equity) / self.config.step_equity)
        )


# 简易自测
if __name__ == "__main__":
    sizer = PositionSizer()
    test_eq = [8_000, 10_000, 12_000, 14_900, 15_000, 20_000, 30_000, 50_000]
    print(f"{'权益':>8} | {'公式手数':>6}")
    print("-" * 22)
    for eq in test_eq:
        print(f"{eq:>8.0f} | {sizer.lots_from_formula(eq):>6d}")
    print()
    print("风控叠加测试 (TA, equity=15800, 连亏=4):")
    d = sizer.calc_lots("TA", 15_800, consecutive_losses=4)
    print(f"  建议手数: {d.lots}  原始: {d.raw_lots}  系数: {d.multiplier}  原因: {d.reason}")
