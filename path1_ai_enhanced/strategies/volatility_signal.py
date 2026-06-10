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
    ParquetLoader, calc_keltner_channels, calc_atr, calc_ema, calc_sma
)


@dataclass
class VolatilityParams:
    keltner_ema: int = 20
    keltner_atr: int = 10
    keltner_mult: float = 1.5
    atr_period: int = 14
    atr_squeeze_threshold: float = 0.8
    volume_ma_period: int = 20
    volume_mult: float = 1.5


class VolatilitySignal:
    STRATEGY_NAME = "volatility"

    def __init__(self, params: VolatilityParams = None, loader: ParquetLoader = None):
        self.params = params or VolatilityParams()
        self.loader = loader or ParquetLoader()

    def prepare_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < max(self.params.keltner_ema, self.params.atr_period) + 50:
            return None
        p = self.params
        df['kc_upper'], df['kc_mid'], df['kc_lower'] = calc_keltner_channels(
            df, p.keltner_ema, p.keltner_atr, p.keltner_mult)
        df['atr'] = calc_atr(df, p.atr_period)
        df['atr_ma'] = calc_sma(df['atr'], p.atr_period)
        df['atr_ratio'] = df['atr'] / df['atr_ma']
        df['volume_ma'] = calc_sma(df['volume'], p.volume_ma_period)
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        return df

    def generate_signal(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        df = self.prepare_data(symbol, start_date, end_date)
        if df is None:
            return []
        signals = []
        p = self.params
        for _, row in df.iterrows():
            if pd.isna(row.get('atr_ratio')) or pd.isna(row.get('kc_upper')):
                continue
            direction = 0
            strength = 0.0
            close = row['close']
            high = row['high']
            low = row['low']
            kc_upper = row['kc_upper']
            kc_lower = row['kc_lower']
            atr_ratio = row['atr_ratio']
            vol_ratio = row.get('volume_ratio', 1.0)
            if high > kc_upper and atr_ratio > p.atr_squeeze_threshold and vol_ratio > p.volume_mult:
                direction = 1
                strength = min(1.0, (high - kc_upper) / row['atr'] * 0.5 + (atr_ratio - 1) * 0.3 + (vol_ratio - 1) * 0.2)
            elif low < kc_lower and atr_ratio > p.atr_squeeze_threshold and vol_ratio > p.volume_mult:
                direction = -1
                strength = min(1.0, (kc_lower - low) / row['atr'] * 0.5 + (atr_ratio - 1) * 0.3 + (vol_ratio - 1) * 0.2)
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
        if 'kc_upper' not in df.columns:
            df['kc_upper'], df['kc_mid'], df['kc_lower'] = calc_keltner_channels(
                df, p.keltner_ema, p.keltner_atr, p.keltner_mult)
        if 'atr_ratio' not in df.columns:
            df['atr'] = calc_atr(df, p.atr_period)
            df['atr_ma'] = calc_sma(df['atr'], p.atr_period)
            df['atr_ratio'] = df['atr'] / df['atr_ma']
        if 'volume_ratio' not in df.columns:
            df['volume_ma'] = calc_sma(df['volume'], p.volume_ma_period)
            df['volume_ratio'] = df['volume'] / df['volume_ma']
        long_cond = (df['high'] > df['kc_upper']) & (df['atr_ratio'] > p.atr_squeeze_threshold) & (df['volume_ratio'] > p.volume_mult)
        short_cond = (df['low'] < df['kc_lower']) & (df['atr_ratio'] > p.atr_squeeze_threshold) & (df['volume_ratio'] > p.volume_mult)
        df['vol_direction'] = 0
        df.loc[long_cond, 'vol_direction'] = 1
        df.loc[short_cond, 'vol_direction'] = -1
        df['vol_strength'] = 0.0
        # 基于 atr_ratio 和 volume_ratio 计算精确强度, 而非统一 0.5
        if 'atr_ratio' in df.columns and 'volume_ratio' in df.columns:
            active_mask = df['vol_direction'] != 0
            atr_bonus = (df.loc[active_mask, 'atr_ratio'] - 1.0).clip(0, 1) * 0.3
            vol_bonus = (df.loc[active_mask, 'volume_ratio'] - 1.0).clip(0, 1) * 0.2
            df.loc[active_mask, 'vol_strength'] = (0.5 + atr_bonus + vol_bonus).clip(0.3, 0.9)
        else:
            df.loc[df['vol_direction'] != 0, 'vol_strength'] = 0.5
        return df
