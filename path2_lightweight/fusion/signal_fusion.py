#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from data.parquet_loader import (
    ParquetLoader, calc_atr, calc_ema, calc_sma, calc_rsi,
    calc_bollinger_bands, calc_keltner_channels, calc_percentile_rank, calc_zscore,
)
from strategies.quantile_short_term_v2 import OptimizedParams


@dataclass
class StandardSignal:
    symbol: str
    date: pd.Timestamp
    direction: int
    strength: float
    strategy_name: str
    confidence: float = 0.5


@dataclass
class FusedSignal:
    symbol: str
    date: pd.Timestamp
    direction: int
    strength: float
    confidence: float
    path2_direction: int
    path1_consensus: int
    path1_agreement: float
    strategy_weights: Dict[str, float]
    enhancement_applied: str
    sl_atr_adj: float = 0.0
    tp_atr_adj: float = 0.0
    hold_days_adj: int = 0


class Path1SignalGenerator:
    def __init__(self, loader: ParquetLoader):
        self.loader = loader

    def prepare_deviation(self, symbol, start_date, end_date):
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < 90:
            return None
        df['pct_rank'] = calc_percentile_rank(df['close'], 40)
        df['zscore'] = calc_zscore(df['close'], 20)
        df['ema_trend'] = calc_ema(df['close'], 50)
        df['atr'] = calc_atr(df, 14)
        long_cond = (df['pct_rank'] < 0.25) & (df['zscore'] < -1.5) & (df['close'] > df['ema_trend'])
        short_cond = (df['pct_rank'] > 0.75) & (df['zscore'] > 1.5) & (df['close'] < df['ema_trend'])
        df['dev_direction'] = 0
        df.loc[long_cond, 'dev_direction'] = 1
        df.loc[short_cond, 'dev_direction'] = -1
        df['dev_strength'] = 0.0
        df.loc[df['dev_direction'] != 0, 'dev_strength'] = 0.5
        return df

    def prepare_mean_revert(self, symbol, start_date, end_date):
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < 70:
            return None
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = calc_bollinger_bands(df['close'], 20, 2.0)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        df['rsi'] = calc_rsi(df['close'], 14)
        long_cond = (df['bb_pct'] < 0.05) & (df['rsi'] < 25) & (df['bb_width'] >= 0.02)
        short_cond = (df['bb_pct'] > 0.95) & (df['rsi'] > 75) & (df['bb_width'] >= 0.02)
        df['mr_direction'] = 0
        df.loc[long_cond, 'mr_direction'] = 1
        df.loc[short_cond, 'mr_direction'] = -1
        df['mr_strength'] = 0.0
        df.loc[df['mr_direction'] != 0, 'mr_strength'] = 0.5
        return df

    def prepare_volatility(self, symbol, start_date, end_date):
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < 70:
            return None
        df['kc_upper'], df['kc_mid'], df['kc_lower'] = calc_keltner_channels(df, 20, 10, 1.5)
        df['atr'] = calc_atr(df, 14)
        df['atr_ma'] = calc_sma(df['atr'], 14)
        df['atr_ratio'] = df['atr'] / df['atr_ma']
        df['volume_ma'] = calc_sma(df['volume'], 20)
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        long_cond = (df['high'] > df['kc_upper']) & (df['atr_ratio'] > 0.8) & (df['volume_ratio'] > 1.5)
        short_cond = (df['low'] < df['kc_lower']) & (df['atr_ratio'] > 0.8) & (df['volume_ratio'] > 1.5)
        df['vol_direction'] = 0
        df.loc[long_cond, 'vol_direction'] = 1
        df.loc[short_cond, 'vol_direction'] = -1
        df['vol_strength'] = 0.0
        df.loc[df['vol_direction'] != 0, 'vol_strength'] = 0.5
        return df


class DarwinianWeightManager:
    def __init__(self, strategy_names, min_weight=0.3, max_weight=2.5, rebalance_freq=5):
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.rebalance_freq = rebalance_freq
        self.performances = {}
        for name in strategy_names:
            self.performances[name] = {
                'total_pnl': 0.0, 'total_trades': 0, 'wins': 0,
                'recent_pnls': [], 'weight': 1.0, 'max_dd': 0.0,
                'peak': 0.0, 'current': 0.0,
            }
        self.day_counter = 0

    def update_performance(self, name, pnl):
        if name not in self.performances:
            return
        p = self.performances[name]
        p['total_pnl'] += pnl
        p['total_trades'] += 1
        if pnl > 0:
            p['wins'] += 1
        p['recent_pnls'].append(pnl)
        if len(p['recent_pnls']) > 120:
            p['recent_pnls'] = p['recent_pnls'][-60:]
        p['current'] += pnl
        if p['current'] > p['peak']:
            p['peak'] = p['current']
        dd = (p['peak'] - p['current']) / p['peak'] if p['peak'] > 0 else 0
        p['max_dd'] = max(p['max_dd'], dd)

    def rebalance_weights(self):
        self.day_counter += 1
        if self.day_counter % self.rebalance_freq != 0:
            return {n: p['weight'] for n, p in self.performances.items()}
        scores = {}
        for name, p in self.performances.items():
            recent = p['recent_pnls'][-60:] if p['recent_pnls'] else []
            sharpe = np.mean(recent) / np.std(recent) * np.sqrt(252) if len(recent) >= 5 and np.std(recent) > 0 else 0
            wr = p['wins'] / p['total_trades'] if p['total_trades'] > 0 else 0
            dd_penalty = max(0, 1 - p['max_dd'] * 2)
            trade_bonus = min(p['total_trades'] / 20, 1.0)
            scores[name] = max(sharpe * 0.4 + wr * 0.3 + dd_penalty * 0.2 + trade_bonus * 0.1, 0.01)
        total = sum(scores.values())
        if total == 0:
            return {n: p['weight'] for n, p in self.performances.items()}
        raw = {n: s / total * len(self.performances) for n, s in scores.items()}
        for name, rw in raw.items():
            clamped = max(self.min_weight, min(self.max_weight, rw))
            self.performances[name]['weight'] = clamped
        t = sum(p['weight'] for p in self.performances.values())
        for p in self.performances.values():
            p['weight'] = p['weight'] / t * len(self.performances)
        return {n: p['weight'] for n, p in self.performances.items()}

    def get_weights(self):
        return {n: p['weight'] for n, p in self.performances.items()}


class SignalFusion:
    def __init__(self, symbols,
                 sl_tighten_atr=0.3,
                 tp_widen_atr=0.0,
                 hold_extend_days=0,
                 hold_reduce_days=1):
        self.symbols = symbols
        self.sl_tighten_atr = sl_tighten_atr
        self.tp_widen_atr = tp_widen_atr
        self.hold_extend_days = hold_extend_days
        self.hold_reduce_days = hold_reduce_days
        self.loader = ParquetLoader()
        self.p1_gen = Path1SignalGenerator(self.loader)
        self.darwin = DarwinianWeightManager(['deviation', 'mean_revert', 'volatility'])
        self.prepared_data = {}
        self._initialized = False

    def initialize(self, start_date, end_date):
        print('SignalFusion: 预计算路径1策略指标...')
        strategies = {
            'deviation': lambda s: self.p1_gen.prepare_deviation(s, start_date, end_date),
            'mean_revert': lambda s: self.p1_gen.prepare_mean_revert(s, start_date, end_date),
            'volatility': lambda s: self.p1_gen.prepare_volatility(s, start_date, end_date),
        }
        dir_cols = {'deviation': 'dev_direction', 'mean_revert': 'mr_direction', 'volatility': 'vol_direction'}
        for sym in self.symbols:
            self.prepared_data[sym] = {}
            for sname, prep_fn in strategies.items():
                try:
                    df = prep_fn(sym)
                    if df is not None and len(df) > 0:
                        dcol = dir_cols.get(sname)
                        sig_count = (df[dcol] != 0).sum() if dcol and dcol in df.columns else 0
                        self.prepared_data[sym][sname] = df
                        print(f'  {sym}/{sname}: {len(df)}行, {sig_count}个信号')
                    else:
                        self.prepared_data[sym][sname] = None
                except Exception as e:
                    print(f'  {sym}/{sname}: 失败 - {e}')
                    self.prepared_data[sym][sname] = None
        self._initialized = True
        print('SignalFusion: 预计算完成')

    def get_path1_signals(self, symbol, date):
        if not self._initialized:
            return {}
        dir_cols = {'deviation': 'dev_direction', 'mean_revert': 'mr_direction', 'volatility': 'vol_direction'}
        str_cols = {'deviation': 'dev_strength', 'mean_revert': 'mr_strength', 'volatility': 'vol_strength'}
        signals = {}
        for sname in ['deviation', 'mean_revert', 'volatility']:
            df = self.prepared_data.get(symbol, {}).get(sname)
            if df is None:
                signals[sname] = StandardSignal(symbol, date, 0, 0.0, sname)
                continue
            row = df[df['date'] == date]
            if row.empty:
                signals[sname] = StandardSignal(symbol, date, 0, 0.0, sname)
                continue
            r = row.iloc[0]
            dcol = dir_cols.get(sname)
            scol = str_cols.get(sname)
            d = int(r.get(dcol, 0)) if pd.notna(r.get(dcol)) else 0
            s = float(r.get(scol, 0.0)) if pd.notna(r.get(scol)) else 0.0
            signals[sname] = StandardSignal(symbol, date, d, s, sname)
        return signals

    def fuse(self, path2_direction, path2_strength, symbol, date):
        path1_signals = self.get_path1_signals(symbol, date)
        weights = self.darwin.get_weights()
        path1_directions = []
        path1_weighted_sum = 0.0
        path1_total_weight = 0.0
        for sname, sig in path1_signals.items():
            if sig.direction != 0:
                w = weights.get(sname, 1.0)
                path1_directions.append(sig.direction)
                path1_weighted_sum += sig.direction * sig.strength * w
                path1_total_weight += w
        if path1_directions:
            path1_consensus = 1 if sum(path1_directions) > 0 else (-1 if sum(path1_directions) < 0 else 0)
            path1_agreement = sum(1 for d in path1_directions if d == path1_consensus) / len(path1_directions)
        else:
            path1_consensus = 0
            path1_agreement = 0.0

        sl_adj = 0.0
        tp_adj = 0.0
        hold_adj = 0
        enhancement_applied = 'none'

        if path2_direction != 0 and path1_consensus != 0:
            if path2_direction == path1_consensus:
                agreement_scale = path1_agreement
                if path1_total_weight > 0:
                    agreement_scale *= min(abs(path1_weighted_sum / path1_total_weight), 1.0)
                tp_adj = self.tp_widen_atr * agreement_scale
                hold_adj = int(round(self.hold_extend_days * agreement_scale))
                enhancement_applied = f'same_dir:tp+{tp_adj:.2f}atr,hold+{hold_adj}d'
            else:
                agreement_scale = path1_agreement
                if path1_total_weight > 0:
                    agreement_scale *= min(abs(path1_weighted_sum / path1_total_weight), 1.0)
                sl_adj = -self.sl_tighten_atr * agreement_scale
                hold_adj = -int(round(self.hold_reduce_days * agreement_scale))
                enhancement_applied = f'conflict:sl{sl_adj:.2f}atr,hold{hold_adj}d'
        elif path2_direction != 0 and path1_consensus == 0:
            enhancement_applied = 'no_path1_signal'

        confidence = min(1.0, path2_strength * (1 + path1_agreement * 0.3))
        return FusedSignal(
            symbol=symbol, date=date, direction=path2_direction,
            strength=path2_strength, confidence=confidence,
            path2_direction=path2_direction, path1_consensus=path1_consensus,
            path1_agreement=path1_agreement, strategy_weights=weights,
            enhancement_applied=enhancement_applied,
            sl_atr_adj=sl_adj, tp_atr_adj=tp_adj, hold_days_adj=hold_adj,
        )

    def update_darwin(self, strategy_name, pnl):
        self.darwin.update_performance(strategy_name, pnl)

    def rebalance_darwin(self):
        return self.darwin.rebalance_weights()
