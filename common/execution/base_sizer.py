#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用仓位基类 (common 层)
=====================================

提供一个最小可用的 `FixedSizer` 作为缺省实现 (每个信号固定 1 手)。
各 path 可以继承 `BaseSizer` 实现自己的模型:
  - path2_lightweight/execution/position_sizer.py 实现 10X 激进模型
  - path1 以后可实现 AI 增强模型
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SizerDecision:
    """仓位计算结果"""
    lots: int
    raw_lots: int           # 公式计算出的原始手数 (未应用折损)
    reason: str = ""        # 决策可读原因 (调试用)
    multiplier: float = 1.0  # 应用的折损/放大系数
    extras: Dict = None     # 额外信息 (单品种上限, 资金占比...)

    def __post_init__(self):
        if self.extras is None:
            self.extras = {}

    def __str__(self):
        return f"SizerDecision(lots={self.lots}, raw={self.raw_lots}, reason='{self.reason}', mult={self.multiplier})"


class BaseSizer(abc.ABC):
    """
    仓位引擎抽象基类
    -----------------

    子类必须实现:
      - calc_lots(symbol, account_equity, consecutive_losses=0, **ctx) -> SizerDecision

    可选实现:
      - sync_from_positions(positions: dict) —— 同步当前持仓以避免重复开仓
    """

    @abc.abstractmethod
    def calc_lots(
        self,
        symbol: str,
        account_equity: float,
        consecutive_losses: int = 0,
        **ctx,
    ) -> SizerDecision:
        ...

    def sync_from_positions(self, positions: dict) -> None:
        """子类按需重写, 用于同步当前持仓信息"""
        return None


class FixedSizer(BaseSizer):
    """
    缺省仓位器: 每个信号固定 1 手.
    用于 path1 / 不知道该下几手时的回退实现.
    """

    def __init__(self, default_lots: int = 1):
        self.default_lots = default_lots

    def calc_lots(
        self,
        symbol: str,
        account_equity: float,
        consecutive_losses: int = 0,
        **ctx,
    ) -> SizerDecision:
        return SizerDecision(
            lots=self.default_lots,
            raw_lots=self.default_lots,
            reason=f"fixed:{self.default_lots}",
            multiplier=1.0,
        )
