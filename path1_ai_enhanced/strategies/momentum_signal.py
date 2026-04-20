#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径一：AI增强多策略系统
动量突破信号 (Momentum Breakout Signal)

核心逻辑:
- 使用EMA交叉判断趋势方向
- ATR确认波动率足够产生突破
- 成交量确认突破有效性
- 趋势跟踪型策略，适合单边行情

信号输出: {symbol, direction, strength, strategy_name}
- direction: 1(做多) / -1(做空) / 0(无信号)
- strength: 0.0 ~ 1.0, 基于EMA交叉角度和ATR扩张
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.data_loader import (
    ParquetLoader, calc_ema, calc_atr, calc_sma
)


@dataclass
class MomentumParams:
    """动量突破信号参数"""
    # EMA交叉参数
    ema_fast: int = 10               # 快速EMA周期
    ema_slow: int = 30               # 慢速EMA周期
    ema_trend: int = 60              # 趋势EMA周期

    # ATR突破确认
    atr_period: int = 14
    atr_expansion_mult: float = 1.2  # ATR扩张倍数(当前ATR > 均值ATR * 此值)

    # 成交量确认
    volume_ma_period: int = 20       # 成交量均线周期
    volume_break_mult: float = 1.3   # 成交量突破倍数

    # 信号冷却期
    cooldown_days: int = 3           # 信号产生后冷却天数


class MomentumSignal:
    """
    动量突破信号生成器

    检测逻辑:
    1. EMA快线上穿慢线 -> 做多信号
    2. EMA快线下穿慢线 -> 做空信号
    3. ATR扩张确认波动率放大
    4. 成交量放大确认突破有效
    5. 信号强度基于EMA交叉角度和ATR扩张程度
    """

    STRATEGY_NAME = "momentum"

    def __init__(self, params: MomentumParams = None, loader: ParquetLoader = None):
        self.params = params or MomentumParams()
        self.loader = loader or ParquetLoader()

    def prepare_data(self, symbol: str,
                     start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """准备带指标的数据"""
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < self.params.ema_trend + 50:
            return None

        p = self.params

        # EMA
        df['ema_fast'] = calc_ema(df['close'], p.ema_fast)
        df['ema_slow'] = calc_ema(df['close'], p.ema_slow)
        df['ema_trend'] = calc_ema(df['close'], p.ema_trend)

        # ATR
        df['atr'] = calc_atr(df, p.atr_period)
        df['atr_ma'] = calc_sma(df['atr'], p.atr_period)
        df['atr_expansion'] = df['atr'] / df['atr_ma']

        # 成交量
        df['volume_ma'] = calc_sma(df['volume'], p.volume_ma_period)
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        # EMA差值和交叉
        df['ema_diff'] = df['ema_fast'] - df['ema_slow']
        df['ema_diff_prev'] = df['ema_diff'].shift(1)

        # EMA交叉检测
        df['ema_cross_up'] = (df['ema_diff'] > 0) & (df['ema_diff_prev'] <= 0)
        df['ema_cross_down'] = (df['ema_diff'] < 0) & (df['ema_diff_prev'] >= 0)

        # 趋势方向
        df['trend_up'] = df['close'] > df['ema_trend']
        df['trend_down'] = df['close'] < df['ema_trend']

        return df

    def generate_signal(self, symbol: str,
                        start_date: str, end_date: str) -> List[Dict]:
        """
        生成动量突破信号序列
        """
        df = self.prepare_data(symbol, start_date, end_date)
        if df is None:
            return []

        signals = []
        p = self.params
        last_signal_idx = -p.cooldown_days - 1  # 确保第一个信号不被冷却期过滤

        for i, row in df.iterrows():
            # 冷却期检查
            if i - last_signal_idx <= p.cooldown_days:
                continue

            direction = 0
            strength = 0.0

            # 做多: EMA金叉 + 上升趋势 + ATR扩张 + 成交量放大
            if (row.get('ema_cross_up', False) and
                    row.get('trend_up', False) and
                    row.get('atr_expansion', 0) > p.atr_expansion_mult):

                direction = 1
                strength = self._calc_strength(
                    row['ema_diff'], row['atr_expansion'],
                    row.get('volume_ratio', 1.0), direction=1
                )

            # 做空: EMA死叉 + 下降趋势 + ATR扩张 + 成交量放大
            elif (row.get('ema_cross_down', False) and
                  row.get('trend_down', False) and
                  row.get('atr_expansion', 0) > p.atr_expansion_mult):

                direction = -1
                strength = self._calc_strength(
                    row['ema_diff'], row['atr_expansion'],
                    row.get('volume_ratio', 1.0), direction=-1
                )

            # 放宽条件: EMA方向一致 + ATR扩张(无交叉但有趋势延续)
            elif row.get('ema_diff', 0) > 0 and row.get('trend_up', False):
                if (row.get('atr_expansion', 0) > p.atr_expansion_mult * 1.3 and
                        row.get('volume_ratio', 1.0) > p.volume_break_mult):
                    direction = 1
                    strength = 0.3  # 弱信号

            elif row.get('ema_diff', 0) < 0 and row.get('trend_down', False):
                if (row.get('atr_expansion', 0) > p.atr_expansion_mult * 1.3 and
                        row.get('volume_ratio', 1.0) > p.volume_break_mult):
                    direction = -1
                    strength = 0.3  # 弱信号

            if direction != 0:
                signals.append({
                    'date': row['date'],
                    'symbol': symbol,
                    'direction': direction,
                    'strength': strength,
                    'strategy_name': self.STRATEGY_NAME,
                    'ema_diff': row.get('ema_diff', 0),
                    'atr_expansion': row.get('atr_expansion', 0),
                    'volume_ratio': row.get('volume_ratio', 1.0),
                })
                last_signal_idx = i

        return signals

    def generate_daily_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """在已准备好的DataFrame上生成每日信号列"""
        p = self.params
        df = df.copy()

        # 主要信号: EMA交叉
        long_cond = (
            df.get('ema_cross_up', pd.Series(False, index=df.index)) &
            df.get('trend_up', pd.Series(False, index=df.index)) &
            (df.get('atr_expansion', 0) > p.atr_expansion_mult)
        )

        short_cond = (
            df.get('ema_cross_down', pd.Series(False, index=df.index)) &
            df.get('trend_down', pd.Series(False, index=df.index)) &
            (df.get('atr_expansion', 0) > p.atr_expansion_mult)
        )

        df['mom_direction'] = 0
        df.loc[long_cond, 'mom_direction'] = 1
        df.loc[short_cond, 'mom_direction'] = -1

        # 信号强度
        df['mom_strength'] = 0.0
        mask_long = df['mom_direction'] == 1
        mask_short = df['mom_direction'] == -1

        if mask_long.any():
            df.loc[mask_long, 'mom_strength'] = df.loc[mask_long].apply(
                lambda r: self._calc_strength(
                    r.get('ema_diff', 0), r.get('atr_expansion', 1),
                    r.get('volume_ratio', 1), direction=1
                ), axis=1
            )
        if mask_short.any():
            df.loc[mask_short, 'mom_strength'] = df.loc[mask_short].apply(
                lambda r: self._calc_strength(
                    r.get('ema_diff', 0), r.get('atr_expansion', 1),
                    r.get('volume_ratio', 1), direction=-1
                ), axis=1
            )

        return df

    def _calc_strength(self, ema_diff: float, atr_expansion: float,
                       volume_ratio: float, direction: int = 1) -> float:
        """
        计算信号强度 (0.0 ~ 1.0)

        基于三个因子:
        1. EMA差值斜率 (权重0.4)
        2. ATR扩张程度 (权重0.35)
        3. 成交量放大程度 (权重0.25)
        """
        # EMA差值归一化 (相对于价格)
        ema_score = min(abs(ema_diff) / max(abs(ema_diff) * 2, 0.001), 1.0) if ema_diff != 0 else 0

        # ATR扩张得分
        atr_score = min((atr_expansion - 1.0) / 0.5, 1.0) if atr_expansion > 1.0 else 0

        # 成交量得分
        vol_score = min((volume_ratio - 1.0) / 0.5, 1.0) if volume_ratio > 1.0 else 0

        strength = 0.4 * ema_score + 0.35 * atr_score + 0.25 * vol_score
        return max(0.1, min(1.0, strength))


if __name__ == "__main__":
    print("=" * 60)
    print("动量突破信号 (Momentum Signal) 测试")
    print("=" * 60)

    signal_gen = MomentumSignal()
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
