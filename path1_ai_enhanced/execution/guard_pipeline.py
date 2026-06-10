#!/usr/bin/env python
# -*- coding: utf-8 -*-
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class GuardConfig:
    max_positions: int = 3
    max_single_position_pct: float = 0.30
    max_drawdown_pct: float = 0.30
    max_correlation: float = 0.7
    min_capital_reserve: float = 0.3


class GuardPipeline:
    def __init__(self, config: GuardConfig = None):
        self.config = config or GuardConfig()
        self.current_drawdown = 0.0
        self.peak_capital = 0.0
        self.positions: Dict[str, dict] = {}

    def update_capital(self, capital: float):
        if capital > self.peak_capital:
            self.peak_capital = capital
        if self.peak_capital > 0:
            self.current_drawdown = (self.peak_capital - capital) / self.peak_capital

    def can_open(self, symbol: str, direction: int, capital: float,
                 position_value: float) -> tuple:
        checks = []
        if len(self.positions) >= self.config.max_positions:
            checks.append(('max_positions', False, f'持仓数{len(self.positions)}>={self.config.max_positions}'))
        else:
            checks.append(('max_positions', True, 'OK'))
        if self.current_drawdown >= self.config.max_drawdown_pct:
            checks.append(('max_drawdown', False, f'回撤{self.current_drawdown:.1%}>={self.config.max_drawdown_pct:.1%}'))
        else:
            checks.append(('max_drawdown', True, 'OK'))
        if symbol in self.positions:
            checks.append(('duplicate', False, f'{symbol}已有持仓'))
        else:
            checks.append(('duplicate', True, 'OK'))
        pos_pct = position_value / capital if capital > 0 else 1.0
        if pos_pct > self.config.max_single_position_pct:
            checks.append(('position_size', False, f'仓位{pos_pct:.1%}>{self.config.max_single_position_pct:.1%}'))
        else:
            checks.append(('position_size', True, 'OK'))
        reserve = capital - position_value
        if reserve < capital * self.config.min_capital_reserve:
            checks.append(('capital_reserve', False, f'预留资金不足'))
        else:
            checks.append(('capital_reserve', True, 'OK'))
        passed = all(c[1] for c in checks)
        return passed, checks

    def add_position(self, symbol: str, direction: int, entry_price: float, size: int):
        self.positions[symbol] = {
            'direction': direction,
            'entry_price': entry_price,
            'size': size,
        }

    def remove_position(self, symbol: str):
        if symbol in self.positions:
            del self.positions[symbol]

    def get_position_count(self) -> int:
        return len(self.positions)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions
