#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分析当前分位数定义的缺陷
问题：价格分位数没有考虑波动率，不同品种的"低分位数"含义完全不同
"""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.parquet_loader import ParquetLoader

loader = ParquetLoader()
SYMBOLS = ['M', 'RM', 'MA', 'TA']

print("="*80)
print("分位数定义分析：为什么M的分位数信号可能是错的？")
print("="*80)

for sym in SYMBOLS:
    df = loader.load_symbol(sym, '2015-01-01', '2025-12-31')
    if df is None or len(df) < 100:
        continue
    
    # 当前策略的分位数定义
    window = 30
    df['pct_rank'] = df['close'].rolling(window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    
    # 计算实际波动率调整
    df['ret'] = df['close'].pct_change()
    df['rolling_vol'] = df['ret'].rolling(window).std() * np.sqrt(252)
    
    # 分位数突破时的实际波动率
    low_pct_signals = df[df['pct_rank'] < 0.30]  # 做多信号
    high_pct_signals = df[df['pct_rank'] > 0.70]  # 做空信号
    
    print(f"\n{sym}:")
    print(f"  低分位数(<30%%)信号: {len(low_pct_signals)}次")
    print(f"    平均波动率: {low_pct_signals['rolling_vol'].mean()*100:.2f}%")
    print(f"    信号后5日收益偏度: {low_pct_signals['ret'].shift(-5).skew():.3f}")
    print(f"    信号后5日收益均值: {low_pct_signals['ret'].shift(-5).mean()*100:.2f}%")
    
    print(f"  高分位数(>70%%)信号: {len(high_pct_signals)}次")
    print(f"    平均波动率: {high_pct_signals['rolling_vol'].mean()*100:.2f}%")
    print(f"    信号后5日收益偏度: {high_pct_signals['ret'].shift(-5).skew():.3f}")
    print(f"    信号后5日收益均值: {high_pct_signals['ret'].shift(-5).mean()*100:.2f}%")
    
    # 关键：低分位数信号后的收益分布
    if len(low_pct_signals) > 10:
        future_ret = low_pct_signals['ret'].shift(-5).dropna()
        win_rate = (future_ret > 0).mean() * 100
        avg_win = future_ret[future_ret > 0].mean() * 100
        avg_lose = future_ret[future_ret < 0].mean() * 100
        print(f"  低分位数做多后5日: 胜率{win_rate:.1f}%, 平均盈{avg_win:+.2f}%, 平均亏{avg_lose:+.2f}%")
    
    if len(high_pct_signals) > 10:
        future_ret = high_pct_signals['ret'].shift(-5).dropna()
        win_rate = (future_ret < 0).mean() * 100  # 做空，下跌=盈利
        avg_win = future_ret[future_ret < 0].abs().mean() * 100
        avg_lose = future_ret[future_ret > 0].mean() * 100
        print(f"  高分位数做空后5日: 胜率{win_rate:.1f}%, 平均盈{avg_win:+.2f}%, 平均亏{avg_lose:+.2f}%")

print(f"\n{'='*80}")
print(f"问题诊断")
print(f"{'='*80}")
print("""
当前分位数定义的问题:

1. **未考虑波动率差异**
   - M的波动率21.5%, MA的27.3%
   - 但分位数定义完全相同: 价格<30%分位数=做多信号
   - 问题: M的低波动率意味着"低分位数"可能只是正常波动, 不是真正的超卖

2. **未考虑偏度差异**
   - M偏度-0.81(严重左偏), MA偏度+0.02(对称)
   - M的"低分位数做多"后, 大亏损概率远大于大盈利概率
   - MA的"低分位数做多"后, 盈亏概率接近对称

3. **未考虑趋势环境**
   - 如果M处于下降趋势, "低分位数"可能是下跌中继而非反转信号
   - 分位数只看价格位置, 不看趋势方向

4. **未考虑品种间相关性**
   - M和RM都是农产品, 但M偏度-0.81, RM偏度-0.29
   - 同样的分位数阈值, 在两个品种上的含义完全不同

建议的分位数改进方向:

A. **波动率调整分位数**: 
   pct_rank / rolling_vol → 波动率标准化

B. **偏度调整分位数**:
   对左偏品种(如M), 提高做多阈值(如从30%提高到20%)

C. **趋势过滤分位数**:
   只在上升趋势中做多低分位数, 只在下降趋势中做空高分位数

D. **动态分位数**:
   根据品种历史偏度/峰度动态调整分位数阈值
""")
