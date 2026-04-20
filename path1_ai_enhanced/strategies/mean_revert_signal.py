#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.data_loader import (
    ParquetLoader, calc_bollinger_bands, calc_rsi, calc_ema, calc_atr
)


@dataclass
class MeanRevertParams:
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_oversold: float = 25
    rsi_overbought: float = 75
    ema_trend: int = 50
    min_bb_width_pct: float = 0.02


class MeanRevertSignal:
    STRATEGY_NAME = "mean_revert"

    def __init__(self, params: MeanRevertParams = None, loader: ParquetLoader = None):
        self.params = params or MeanRevertParams()
        self.loader = loader or ParquetLoader()

    def prepare_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < self.params.bb_period + 50:
            return None
        p = self.params
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = calc_bollinger_bands(
            df['close'], p.bb_period, p.bb_std)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
        df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        df['rsi'] = calc_rsi(df['close'], p.rsi_period)
        df['ema_trend'] = calc_ema(df['close'], p.ema_trend)
        df['atr'] = calc_atr(df, 14)
        return df

    def generate_signal(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        df = self.prepare_data(symbol, start_date, end_date)
        if df is None:
            return []
        signals = []
        p = self.params
        for _, row in df.iterrows():
            if pd.isna(row.get('bb_pct')) or pd.isna(row.get('rsi')):
                continue
            direction = 0
            strength = 0.0
            bb_pct = row['bb_pct']
            rsi = row['rsi']
            bb_width = row.get('bb_width', 0)
            if bb_width < p.min_bb_width_pct:
                continue
            if bb_pct < 0.05 and rsi < p.rsi_oversold:
                direction = 1
                strength = min(1.0, (0.05 - bb_pct) / 0.05 * 0.6 + (p.rsi_oversold - rsi) / p.rsi_oversold * 0.4)
            elif bb_pct > 0.95 and rsi > p.rsi_overbought:
                direction = -1
                strength = min(1.0, (bb_pct - 0.95) / 0.05 * 0.6 + (rsi - p.rsi_overbought) / (100 - p.rsi_overbought) * 0.4)
            if direction != 0:
                signals.append({
                    'date': row['date'],
                    'symbol': symbol,
                    'direction': direction,
                    'strength': max(0.1, strength),
                    'strategy_name': self.STRATEGY_NAME,
                })
        return signals

    def generate_daily_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        df = df.copy()
        if 'bb_pct' not in df.columns:
            df['bb_upper'], df['bb_mid'], df['bb_lower'] = calc_bollinger_bands(
                df['close'], p.bb_period, p.bb_std)
            df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
            df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        if 'rsi' not in df.columns:
            df['rsi'] = calc_rsi(df['close'], p.rsi_period)
        long_cond = (df['bb_pct'] < 0.05) & (df['rsi'] < p.rsi_oversold) & (df['bb_width'] >= p.min_bb_width_pct)
        short_cond = (df['bb_pct'] > 0.95) & (df['rsi'] > p.rsi_overbought) & (df['bb_width'] >= p.min_bb_width_pct)
        df['mr_direction'] = 0
        df.loc[long_cond, 'mr_direction'] = 1
        df.loc[short_cond, 'mr_direction'] = -1
        df['mr_strength'] = 0.0
        df.loc[df['mr_direction'] != 0, 'mr_strength'] = 0.5
        return df
