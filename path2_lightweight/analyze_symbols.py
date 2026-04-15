#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分析M/RM/MA/TA品种特性差异
"""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.parquet_loader import ParquetLoader

loader = ParquetLoader()
SYMBOLS = ['M', 'RM', 'MA', 'TA']

print("="*70)
print("品种特性分析")
print("="*70)

all_stats = []

for sym in SYMBOLS:
    df = loader.load_symbol(sym, '2015-01-01', '2025-12-31')
    if df is None or len(df) < 100:
        print(f"{sym}: 数据不足")
        continue
    
    # 日收益率
    df['ret'] = df['close'].pct_change()
    
    # 年度统计
    df['year'] = pd.to_datetime(df['date']).dt.year
    df['abs_ret'] = df['ret'].abs()
    
    # 趋势强度 (annualized return / volatility)
    total_return = (df['close'].iloc[-1] / df['close'].iloc[0] - 1)
    years = (df['date'].iloc[-1] - df['date'].iloc[0]).days / 365.25
    annual = (1 + total_return) ** (1/years) - 1
    vol = df['ret'].std() * np.sqrt(252)
    sharpe = annual / vol if vol > 0 else 0
    
    # 趋势持续性: 正收益率天数占比
    up_days = (df['ret'] > 0).mean() * 100
    
    # 平均绝对波动
    avg_vol = df['abs_ret'].mean() * 100
    
    # 年度盈亏方向一致性
    yearly_returns = df.groupby('year')['ret'].sum()
    pos_years = (yearly_returns > 0).sum()
    neg_years = (yearly_returns < 0).sum()
    
    # 连续涨跌天数
    streaks = []
    cur_streak = 0
    cur_dir = 0
    for r in df['ret']:
        if r > 0 and cur_dir >= 0:
            cur_streak += 1
            cur_dir = 1
        elif r < 0 and cur_dir <= 0:
            cur_streak += 1
            cur_dir = -1
        else:
            if cur_streak > 1:
                streaks.append(cur_streak)
            cur_streak = 1
            cur_dir = 1 if r > 0 else -1
    if cur_streak > 1:
        streaks.append(cur_streak)
    
    avg_streak = np.mean(streaks) if streaks else 0
    max_streak = max(streaks) if streaks else 0
    
    # 年度趋势方向一致性
    trend_consistency = max(pos_years, neg_years) / (pos_years + neg_years) * 100
    
    print(f"\n{sym} ({len(df)}行):")
    print(f"  总收益: {total_return*100:.1f}% | 年化: {annual*100:.1f}% | 波动率: {vol*100:.1f}% | 夏普: {sharpe:.2f}")
    print(f"  上涨天数: {up_days:.1f}% | 平均日波动: {avg_vol:.3f}%")
    print(f"  趋势方向一致性: {trend_consistency:.0f}% ({pos_years}年正 / {neg_years}年负)")
    print(f"  平均连涨/连跌天数: {avg_streak:.1f} | 最长: {max_streak}天")
    
    # 逐年
    print(f"  逐年收益:")
    for y, yr in df.groupby('year'):
        yr_ret = yr['ret'].sum() * 100
        yr_vol = yr['ret'].std() * np.sqrt(252) * 100
        sign = "+" if yr_ret > 0 else ""
        print(f"    {y}: {sign}{yr_ret:.1f}% (vol={yr_vol:.1f}%)")
    
    all_stats.append({
        'symbol': sym,
        'annual_return': annual,
        'volatility': vol,
        'sharpe': sharpe,
        'up_days_pct': up_days,
        'avg_daily_vol': avg_vol,
        'trend_consistency': trend_consistency,
        'avg_streak': avg_streak,
        'max_streak': max_streak,
        'pos_years': pos_years,
        'neg_years': neg_years,
    })

print(f"\n{'='*70}")
print(f"汇总对比")
print(f"{'='*70}")
stats_df = pd.DataFrame(all_stats)
print(f"{'品种':4s} | {'年化':>6s} | {'波动率':>6s} | {'夏普':>5s} | {'上涨天':>5s} | "
      f"{'日波动':>5s} | {'趋势一致':>6s} | {'正/负年':>7s} | {'连涨/跌':>5s} | {'最长':>4s}")
print(f"{'-'*80}")
for _, r in stats_df.iterrows():
    print(f"{r['symbol']:4s} | {r['annual_return']*100:5.1f}% | {r['volatility']*100:5.1f}% | "
          f"{r['sharpe']:5.2f} | {r['up_days_pct']:4.1f}% | {r['avg_daily_vol']:4.3f}% | "
          f"{r['trend_consistency']:5.0f}% | {int(r['pos_years'])}/{int(r['neg_years'])}    | "
          f"{r['avg_streak']:4.1f} | {int(r['max_streak'])}d")
