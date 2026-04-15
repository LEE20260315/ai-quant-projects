#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
深度分析：为什么M拖累组合，RM/MA/TA适应策略
"""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.parquet_loader import ParquetLoader

loader = ParquetLoader()
SYMBOLS = ['M', 'RM', 'MA', 'TA']

print("="*80)
print("品种特性深度分析：为什么M拖累组合？")
print("="*80)

# 收集逐年数据
all_data = {}

for sym in SYMBOLS:
    df = loader.load_symbol(sym, '2015-01-01', '2025-12-31')
    if df is None: continue
    
    df['ret'] = df['close'].pct_change()
    df['year'] = pd.to_datetime(df['date']).dt.year
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    
    # 年度统计
    yearly = df.groupby('year').agg(
        annual_ret=('ret', 'sum'),
        volatility=('ret', lambda x: x.std()*np.sqrt(252)),
        skew=('ret', lambda x: x.skew()),
        kurtosis=('ret', lambda x: x.kurtosis()),
    )
    
    # 月度自相关性 (动量/反转特征)
    monthly = df.groupby('month')['ret'].sum()
    # 计算月度收益率的自相关(滞后1期)
    if len(monthly) > 2:
        autocorr = monthly.autocorr(lag=1)
    else:
        autocorr = 0
    
    # 波动率聚类 (高波动后面是否还是高波动)
    df['abs_ret'] = df['ret'].abs()
    vol_autocorr = df['abs_ret'].autocorr(lag=1) if len(df) > 1 else 0
    
    # 极端波动天数 (>3σ)
    mean_ret = df['ret'].mean()
    std_ret = df['ret'].std()
    extreme_days = ((df['ret'] - mean_ret).abs() > 3*std_ret).sum()
    
    print(f"\n{sym}:")
    print(f"  月度自相关(动量): {autocorr:.3f}  |  波动率聚类: {vol_autocorr:.3f}")
    print(f"  极端波动天数(>3σ): {extreme_days}")
    print(f"  偏度: {yearly['skew'].mean():.3f} | 峰度: {yearly['kurtosis'].mean():.3f}")
    print(f"  逐年收益:")
    for y in yearly.index:
        yr = yearly.loc[y]
        print(f"    {y}: {yr['annual_ret']*100:+6.1f}% (vol={yr['volatility']*100:.1f}%, "
              f"偏度={yr['skew']:.2f}, 峰度={yr['kurtosis']:.1f})")
    
    all_data[sym] = {
        'autocorr': autocorr,
        'vol_autocorr': vol_autocorr,
        'extreme_days': extreme_days,
        'yearly_skew': yearly['skew'].mean(),
        'yearly_kurtosis': yearly['kurtosis'].mean(),
    }

# 对比分析
print(f"\n{'='*80}")
print(f"关键特性对比")
print(f"{'='*80}")
print(f"{'品种':4s} | {'月度动量':>8s} | {'波动聚类':>8s} | {'极端天数':>6s} | "
      f"{'偏度':>6s} | {'峰度':>6s}")
print(f"{'-'*60}")
for sym in SYMBOLS:
    d = all_data[sym]
    print(f"{sym:4s} | {d['autocorr']:8.3f} | {d['vol_autocorr']:8.3f} | "
          f"{d['extreme_days']:6d} | {d['yearly_skew']:6.3f} | {d['yearly_kurtosis']:6.1f}")

# 解释
print(f"\n{'='*80}")
print(f"分析与结论")
print(f"{'='*80}")
print("""
【月度动量 autocorr】
正值 = 趋势延续性(动量)，策略友好
负值 = 均值回归(反转)，策略不友好
接近0 = 随机游走，策略中性

M:    {m_auto:.3f} → {m_interp}
RM:   {rm_auto:.3f} → {rm_interp}
MA:   {ma_auto:.3f} → {ma_interp}
TA:   {ta_auto:.3f} → {ta_interp}

【波动率聚类 vol_autocorr】
高值 = 波动率聚集，趋势行情时止损容易被打掉
低值 = 波动率均匀，策略友好

M:    {m_vol:.3f} → {m_vol_interp}
RM:   {rm_vol:.3f} → {rm_vol_interp}
MA:   {ma_vol:.3f} → {ma_vol_interp}
TA:   {ta_vol:.3f} → {ta_vol_interp}

【偏度 skew】
正值 = 右偏(大正收益多)，趋势跟踪策略友好
负值 = 左偏(大负收益多)，止损频繁

【峰度 kurtosis】
高值 = 肥尾(极端行情多)，策略风险大
低值 = 接近正态分布，策略稳定
""".format(
    m_auto=all_data['M']['autocorr'],
    rm_auto=all_data['RM']['autocorr'],
    ma_auto=all_data['MA']['autocorr'],
    ta_auto=all_data['TA']['autocorr'],
    m_vol=all_data['M']['vol_autocorr'],
    rm_vol=all_data['RM']['vol_autocorr'],
    ma_vol=all_data['MA']['vol_autocorr'],
    ta_vol=all_data['TA']['vol_autocorr'],
    m_interp="动量强" if all_data['M']['autocorr'] > 0.1 else ("均值回归" if all_data['M']['autocorr'] < -0.1 else "随机"),
    rm_interp="动量强" if all_data['RM']['autocorr'] > 0.1 else ("均值回归" if all_data['RM']['autocorr'] < -0.1 else "随机"),
    ma_interp="动量强" if all_data['MA']['autocorr'] > 0.1 else ("均值回归" if all_data['MA']['autocorr'] < -0.1 else "随机"),
    ta_interp="动量强" if all_data['TA']['autocorr'] > 0.1 else ("均值回归" if all_data['TA']['autocorr'] < -0.1 else "随机"),
    m_vol_interp="高聚集" if all_data['M']['vol_autocorr'] > 0.1 else "低",
    rm_vol_interp="高" if all_data['RM']['vol_autocorr'] > 0.1 else "低",
    ma_vol_interp="高" if all_data['MA']['vol_autocorr'] > 0.1 else "低",
    ta_vol_interp="高" if all_data['TA']['vol_autocorr'] > 0.1 else "低",
))
