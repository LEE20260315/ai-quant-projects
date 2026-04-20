#!/usr/bin/env python
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class StrategyPerformance:
    name: str
    total_pnl: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    peak_capital: float = 0.0
    max_drawdown: float = 0.0
    current_capital: float = 0.0
    recent_pnls: list = field(default_factory=list)
    weight: float = 1.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def sharpe(self) -> float:
        if len(self.recent_pnls) < 5:
            return 0.0
        arr = np.array(self.recent_pnls[-60:])
        if np.std(arr) == 0:
            return 0.0
        return float(np.mean(arr) / np.std(arr) * np.sqrt(252))


class DarwinianWeightManager:
    def __init__(self, strategy_names: List[str],
                 min_weight: float = 0.3,
                 max_weight: float = 2.5,
                 lookback: int = 60,
                 rebalance_freq: int = 5):
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.lookback = lookback
        self.rebalance_freq = rebalance_freq
        self.performances: Dict[str, StrategyPerformance] = {}
        for name in strategy_names:
            self.performances[name] = StrategyPerformance(name=name)
        self.day_counter = 0

    def update_performance(self, strategy_name: str, pnl: float):
        if strategy_name not in self.performances:
            return
        perf = self.performances[strategy_name]
        perf.total_pnl += pnl
        perf.total_trades += 1
        if pnl > 0:
            perf.wins += 1
        else:
            perf.losses += 1
        perf.recent_pnls.append(pnl)
        if len(perf.recent_pnls) > self.lookback * 2:
            perf.recent_pnls = perf.recent_pnls[-self.lookback:]
        perf.current_capital += pnl
        if perf.current_capital > perf.peak_capital:
            perf.peak_capital = perf.current_capital
        dd = (perf.peak_capital - perf.current_capital) / perf.peak_capital if perf.peak_capital > 0 else 0
        perf.max_drawdown = max(perf.max_drawdown, dd)

    def rebalance_weights(self) -> Dict[str, float]:
        self.day_counter += 1
        if self.day_counter % self.rebalance_freq != 0:
            return {n: p.weight for n, p in self.performances.items()}
        scores = {}
        for name, perf in self.performances.items():
            sharpe = perf.sharpe
            win_rate = perf.win_rate
            dd_penalty = max(0, 1 - perf.max_drawdown * 2)
            trade_bonus = min(perf.total_trades / 20, 1.0)
            score = sharpe * 0.4 + win_rate * 0.3 + dd_penalty * 0.2 + trade_bonus * 0.1
            scores[name] = max(score, 0.01)
        total_score = sum(scores.values())
        if total_score == 0:
            equal_w = 1.0 / len(self.performances)
            for name in self.performances:
                self.performances[name].weight = equal_w
            return {n: equal_w for n in self.performances}
        raw_weights = {n: s / total_score * len(self.performances) for n, s in scores.items()}
        for name, raw_w in raw_weights.items():
            clamped = max(self.min_weight, min(self.max_weight, raw_w))
            self.performances[name].weight = clamped
        total = sum(p.weight for p in self.performances.values())
        for perf in self.performances.values():
            perf.weight = perf.weight / total * len(self.performances)
        return {n: p.weight for n, p in self.performances.items()}

    def get_weights(self) -> Dict[str, float]:
        return {n: p.weight for n, p in self.performances.items()}

    def get_combined_signal(self, signals: Dict[str, Dict]) -> tuple:
        weights = self.get_weights()
        weighted_direction = 0.0
        weighted_strength = 0.0
        total_weight = 0.0
        for name, sig in signals.items():
            if sig and sig.get('direction', 0) != 0:
                w = weights.get(name, 1.0)
                weighted_direction += sig['direction'] * sig['strength'] * w
                weighted_strength += sig['strength'] * w
                total_weight += w
        if total_weight == 0:
            return 0, 0.0
        avg_direction = weighted_direction / total_weight
        avg_strength = weighted_strength / total_weight
        final_direction = 1 if avg_direction > 0.05 else (-1 if avg_direction < -0.05 else 0)
        return final_direction, avg_strength
