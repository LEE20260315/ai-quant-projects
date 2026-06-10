#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径一：AI增强多策略系统
定价偏差信号 (Pricing Deviation Signal)

核心逻辑:
- 检测期货价格偏离统计常态的异常情况
- 使用Z-Score和百分位排名双重确认
- 当价格偏离超过阈值时产生交易信号
- 偏离越大，信号强度越高

信号输出: {symbol, direction, strength, strategy_name}
- direction: 1(做多, 价格偏低) / -1(做空, 价格偏高) / 0(无信号)
- strength: 0.0 ~ 1.0, 偏离程度越大强度越高
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.data_loader import (
    ParquetLoader, calc_zscore, calc_percentile_rank,
    calc_ema, calc_atr, calc_rsi
)


@dataclass
class DeviationParams:
    """定价偏差信号参数"""
    # Z-Score参数
    zscore_window: int = 20          # Z-Score滚动窗口
    zscore_entry_threshold: float = 2.0    # 入场Z-Score阈值
    zscore_exit_threshold: float = 0.5     # 出场Z-Score阈值

    # 百分位参数
    percentile_window: int = 40      # 百分位滚动窗口
    pct_low_threshold: float = 0.10  # 低百分位阈值(做多)
    pct_high_threshold: float = 0.90 # 高百分位阈值(做空)

    # 趋势确认
    ema_fast: int = 10
    ema_slow: int = 30
    rsi_period: int = 14
    rsi_oversold: float = 35        # RSI超卖(辅助做多确认)
    rsi_overbought: float = 65      # RSI超买(辅助做空确认)

    # 信号强度映射
    strength_zscore_1x: float = 2.0  # Z-Score=2时强度=0.33
    strength_zscore_2x: float = 3.0  # Z-Score=3时强度=0.67
    strength_zscore_3x: float = 4.0  # Z-Score>=4时强度=1.0


class DeviationSignal:
    """
    定价偏差信号生成器

    检测逻辑:
    1. 计算收盘价的滚动Z-Score
    2. 计算收盘价的滚动百分位排名
    3. Z-Score和百分位同向确认时产生信号
    4. 信号强度基于Z-Scode绝对值线性映射
    """

    STRATEGY_NAME = "deviation"

    def __init__(self, params: DeviationParams = None, loader: ParquetLoader = None):
        self.params = params or DeviationParams()
        self.loader = loader or ParquetLoader()

    def prepare_data(self, symbol: str,
                     start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """准备带指标的数据"""
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < max(self.params.zscore_window,
                                        self.params.percentile_window,
                                        self.params.ema_slow) + 50:
            return None

        # Z-Score
        df['zscore'] = calc_zscore(df['close'], self.params.zscore_window)

        # 百分位排名
        df['pct_rank'] = calc_percentile_rank(df['close'], self.params.percentile_window)

        # 趋势确认指标
        df['ema_fast'] = calc_ema(df['close'], self.params.ema_fast)
        df['ema_slow'] = calc_ema(df['close'], self.params.ema_slow)
        df['rsi'] = calc_rsi(df['close'], self.params.rsi_period)
        df['atr'] = calc_atr(df, 14)

        return df

    def generate_signal(self, symbol: str,
                        start_date: str, end_date: str) -> List[Dict]:
        """
        生成定价偏差信号序列

        Returns:
            信号列表, 每个元素: {date, symbol, direction, strength, strategy_name}
        """
        df = self.prepare_data(symbol, start_date, end_date)
        if df is None:
            return []

        signals = []
        p = self.params

        for i, row in df.iterrows():
            zscore = row.get('zscore', np.nan)
            pct_rank = row.get('pct_rank', np.nan)
            rsi = row.get('rsi', np.nan)
            ema_fast = row.get('ema_fast', np.nan)
            ema_slow = row.get('ema_slow', np.nan)

            # 跳过NaN
            if pd.isna(zscore) or pd.isna(pct_rank) or pd.isna(rsi):
                continue

            direction = 0
            strength = 0.0

            # 做多条件: Z-Score < -阈值 AND 百分位 < 低阈值 AND RSI未超买
            if (zscore < -p.zscore_entry_threshold and
                    pct_rank < p.pct_low_threshold and
                    rsi < p.rsi_overbought):
                direction = 1
                strength = self._calc_strength(abs(zscore))

            # 做空条件: Z-Score > +阈值 AND 百分位 > 高阈值 AND RSI未超卖
            elif (zscore > p.zscore_entry_threshold and
                  pct_rank > p.pct_high_threshold and
                  rsi > p.rsi_oversold):
                direction = -1
                strength = self._calc_strength(abs(zscore))

            if direction != 0:
                signals.append({
                    'date': row['date'],
                    'symbol': symbol,
                    'direction': direction,
                    'strength': strength,
                    'strategy_name': self.STRATEGY_NAME,
                    'zscore': zscore,
                    'pct_rank': pct_rank,
                    'rsi': rsi,
                })

        return signals

    def generate_daily_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        在已准备好的DataFrame上生成每日信号列

        在df上添加 'dev_signal' (direction) 和 'dev_strength' 列
        """
        p = self.params
        df = df.copy()

        # 做多信号
        long_cond = (
            (df['zscore'] < -p.zscore_entry_threshold) &
            (df['pct_rank'] < p.pct_low_threshold) &
            (df['rsi'] < p.rsi_overbought)
        )

        # 做空信号
        short_cond = (
            (df['zscore'] > p.zscore_entry_threshold) &
            (df['pct_rank'] > p.pct_high_threshold) &
            (df['rsi'] > p.rsi_oversold)
        )

        df['dev_direction'] = 0
        df.loc[long_cond, 'dev_direction'] = 1
        df.loc[short_cond, 'dev_direction'] = -1

        # 信号强度
        df['dev_strength'] = 0.0
        mask = df['dev_direction'] != 0
        df.loc[mask, 'dev_strength'] = df.loc[mask, 'zscore'].abs().apply(
            lambda z: self._calc_strength(z)
        )

        return df

    def _calc_strength(self, abs_zscore: float) -> float:
        """根据Z-Score绝对值计算信号强度 (0.0 ~ 1.0)"""
        p = self.params
        if abs_zscore >= p.strength_zscore_3x:
            return 1.0
        elif abs_zscore >= p.strength_zscore_2x:
            return 0.67 + 0.33 * (abs_zscore - p.strength_zscore_2x) / \
                   (p.strength_zscore_3x - p.strength_zscore_2x)
        elif abs_zscore >= p.strength_zscore_1x:
            return 0.33 + 0.34 * (abs_zscore - p.strength_zscore_1x) / \
                   (p.strength_zscore_2x - p.strength_zscore_1x)
        else:
            return 0.33 * abs_zscore / p.strength_zscore_1x


if __name__ == "__main__":
    print("=" * 60)
    print("定价偏差信号 (Deviation Signal) 测试")
    print("=" * 60)

    signal_gen = DeviationSignal()
    signals = signal_gen.generate_signal("TA", "2020-01-01", "2025-12-31")

    print(f"\nTA品种 2020-2025 信号统计:")
    print(f"  总信号数: {len(signals)}")

    if signals:
        df_sig = pd.DataFrame(signals)
        long_count = len(df_sig[df_sig['direction'] == 1])
        short_count = len(df_sig[df_sig['direction'] == -1])
        print(f"  做多信号: {long_count}")
        print(f"  做空信号: {short_count}")
        print(f"  平均强度: {df_sig['strength'].mean():.3f}")
        print(f"\n最近5个信号:")
        print(df_sig.tail(5).to_string(index=False))

    print("\n" + "=" * 60)
