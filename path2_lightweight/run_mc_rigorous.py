#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TA+RM+MA 三品种蒙特卡罗严谨分析
- 使用真实Walk-Forward的OOS交易数据
- 块自助重采样 (block bootstrap)
- 1000次模拟
- 关注破产率(回撤>50%)
"""
import os, sys
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio.portfolio_backtest import PortfolioBacktest, PortfolioConfig
from strategies.quantile_short_term_v2 import OptimizedParams

SYMBOLS = ['TA', 'RM', 'MA']

# 使用WF中表现最好的参数（来自2021窗口IS优化）
BEST_PARAMS = {
    'percentile_window': 30,
    'long_entry_pct': 0.30,
    'short_entry_pct': 0.70,
    'atr_stop_mult': 1.8,
    'atr_take_mult': 2.5,
    'max_hold_days': 10,
}

def run_mc_analysis(n_sims=1000, block_size=10):
    """蒙特卡罗分析"""
    print("="*70)
    print("TA+RM+MA 三品种蒙特卡罗严谨分析")
    print(f"模拟次数: {n_sims} | 块大小: {block_size}")
    print("="*70)
    
    # 先用最优参数跑完整OOS(2019-2025)获取日收益率
    print(f"\n[1/3] 获取OOS日收益率序列...")
    
    cfg = PortfolioConfig(
        initial_capital=10000, max_positions=3, max_position_pct=0.50,
        max_total_position_pct=0.80,
        start_date="2019-01-01", end_date="2025-12-31"
    )
    p = OptimizedParams(
        percentile_window=BEST_PARAMS['percentile_window'],
        long_entry_pct=BEST_PARAMS['long_entry_pct'],
        short_entry_pct=BEST_PARAMS['short_entry_pct'],
        atr_stop_mult=BEST_PARAMS['atr_stop_mult'],
        atr_take_mult=BEST_PARAMS['atr_take_mult'],
        max_hold_days=BEST_PARAMS['max_hold_days'],
        trend_filter_enabled=False,
    )
    
    result = PortfolioBacktest(cfg).run(SYMBOLS, p)
    equity = result.get('equity_df')
    
    if equity is None or len(equity) < 50:
        print("错误: OOS权益数据不足")
        return
    
    equity = equity.copy()
    equity['daily_ret'] = equity['capital'].pct_change().fillna(0)
    daily_rets = equity['daily_ret'].values
    n_days = len(daily_rets)
    
    print(f"  OOS天数: {n_days}天")
    print(f"  OOS交易: {result.get('total_trades', 0)}笔")
    print(f"  OOS年化: {result.get('annual_return_pct', 0):.1f}%")
    print(f"  OOS夏普: {result.get('sharpe_ratio', 0):.2f}")
    print(f"  OOS回撤: {result.get('max_drawdown_pct', 0):.1f}%")
    
    # 蒙特卡罗模拟
    print(f"\n[2/3] 运行{n_sims}次蒙特卡罗模拟...")
    
    mc_results = []
    
    for i in range(n_sims):
        # 块自助重采样
        sampled = []
        while len(sampled) < n_days:
            start = np.random.randint(0, max(1, n_days - block_size + 1))
            block = daily_rets[start:start + block_size]
            sampled.extend(block.tolist())
        sampled = np.array(sampled[:n_days])
        
        # 计算净值
        nav = 10000 * (1 + sampled).cumprod()
        total_ret = (nav[-1] / 10000 - 1) * 100
        years = n_days / 252
        annual_ret = ((nav[-1] / 10000) ** (1/years) - 1) * 100
        
        peak = np.maximum.accumulate(nav)
        dd = (nav - peak) / peak
        max_dd = dd.min() * 100
        
        sharpe = (sampled.mean() / sampled.std() * np.sqrt(252)) if sampled.std() > 0 else 0
        calmar = annual_ret / abs(max_dd) if max_dd != 0 else 0
        
        mc_results.append({
            'sim': i+1,
            'total_ret': total_ret,
            'annual_ret': annual_ret,
            'max_dd': max_dd,
            'sharpe': sharpe,
            'calmar': calmar,
            'final_nav': nav[-1],
        })
        
        if (i+1) % 200 == 0:
            print(f"  完成 {i+1}/{n_sims}...")
    
    mc_df = pd.DataFrame(mc_results)
    
    # 统计分析
    print(f"\n[3/3] 统计分析...")
    
    percentiles = {
        'p1': mc_df['annual_ret'].quantile(0.01),
        'p5': mc_df['annual_ret'].quantile(0.05),
        'p10': mc_df['annual_ret'].quantile(0.10),
        'p25': mc_df['annual_ret'].quantile(0.25),
        'p50': mc_df['annual_ret'].quantile(0.50),
        'p75': mc_df['annual_ret'].quantile(0.75),
        'p90': mc_df['annual_ret'].quantile(0.90),
        'p95': mc_df['annual_ret'].quantile(0.95),
        'p99': mc_df['annual_ret'].quantile(0.99),
    }
    
    ruin_prob = (mc_df['max_dd'] < -50).mean() * 100
    ruin_prob_30 = (mc_df['max_dd'] < -30).mean() * 100
    ruin_prob_40 = (mc_df['max_dd'] < -40).mean() * 100
    
    var_5 = mc_df['annual_ret'].quantile(0.05)
    cvar_5 = mc_df[mc_df['annual_ret'] <= var_5]['annual_ret'].mean()
    
    print(f"\n{'='*60}")
    print(f"蒙特卡罗结果汇总")
    print(f"{'='*60}")
    print(f"年化收益率分位数:")
    print(f"  P1:  {percentiles['p1']:7.1f}%")
    print(f"  P5:  {percentiles['p5']:7.1f}%")
    print(f"  P10: {percentiles['p10']:7.1f}%")
    print(f"  P25: {percentiles['p25']:7.1f}%")
    print(f"  P50: {percentiles['p50']:7.1f}%")
    print(f"  P75: {percentiles['p75']:7.1f}%")
    print(f"  P90: {percentiles['p90']:7.1f}%")
    print(f"  P95: {percentiles['p95']:7.1f}%")
    print(f"  P99: {percentiles['p99']:7.1f}%")
    
    print(f"\n破产概率:")
    print(f"  回撤>30%%: {ruin_prob_30:.1f}%")
    print(f"  回撤>40%%: {ruin_prob_40:.1f}%")
    print(f"  回撤>50%%: {ruin_prob:.1f}%")
    
    print(f"\n风险指标:")
    print(f"  VaR(5%):  {var_5:.1f}%")
    print(f"  CVaR(5%): {cvar_5:.1f}%")
    
    # 分布统计
    print(f"\n分布统计:")
    print(f"  均值: {mc_df['annual_ret'].mean():.1f}%")
    print(f"  中位数: {mc_df['annual_ret'].median():.1f}%")
    print(f"  标准差: {mc_df['annual_ret'].std():.1f}%")
    print(f"  偏度: {mc_df['annual_ret'].skew():.2f}")
    print(f"  峰度: {mc_df['annual_ret'].kurtosis():.2f}")
    
    # 盈利概率
    profit_prob = (mc_df['annual_ret'] > 0).mean() * 100
    print(f"\n盈利概率(年化>0): {profit_prob:.1f}%")
    
    # 保存结果
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(outdir, exist_ok=True)
    
    mc_df.to_csv(os.path.join(outdir, f"mc_results_{ts}.csv"), index=False)
    
    # 汇总报告
    report = {
        'symbols': SYMBOLS,
        'period': '2019-2025',
        'n_sims': n_sims,
        'block_size': block_size,
        'oos_trades': result.get('total_trades', 0),
        'oos_sharpe': result.get('sharpe_ratio', 0),
        'oos_annual': result.get('annual_return_pct', 0),
        'oos_max_dd': result.get('max_drawdown_pct', 0),
        'percentiles': percentiles,
        'ruin_prob_30': ruin_prob_30,
        'ruin_prob_40': ruin_prob_40,
        'ruin_prob_50': ruin_prob,
        'var_5': var_5,
        'cvar_5': cvar_5,
        'profit_prob': profit_prob,
        'mean_annual': mc_df['annual_ret'].mean(),
        'median_annual': mc_df['annual_ret'].median(),
        'std_annual': mc_df['annual_ret'].std(),
        'best_params': BEST_PARAMS,
    }
    
    import json
    with open(os.path.join(outdir, f"mc_report_{ts}.json"), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n结果已保存: {outdir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_mc_analysis(n_sims=1000, block_size=10)
