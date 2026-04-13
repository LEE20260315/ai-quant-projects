#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二 v2：优化版实验运行
对比v1和v2结果
"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategies.quantile_short_term_v2 import OptimizedQuantileStrategy, OptimizedParams
from data.parquet_loader import ParquetLoader, LOW_MARGIN_SYMBOLS

CONFIG = {
    "full_start": "2020-01-01",
    "full_end": "2025-12-31",
    "initial_capital": 10000,
    "output_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"),
}


def run_all_symbols_v2(strategy, start_date, end_date, capital):
    """批量回测所有品种"""
    loader = ParquetLoader()
    availability = loader.check_data_availability()
    available = availability[availability['file_exists'] == True]
    
    print(f"\n回测 {len(available)} 个品种 (v2优化版)...")
    print(f"时间: {start_date} 至 {end_date}")
    print("-" * 100)
    
    all_results = []
    
    for _, row in available.iterrows():
        symbol = row['symbol']
        result = strategy.backtest_single_symbol(symbol, start_date, end_date, capital)
        
        if 'error' not in result or result.get('total_trades', 0) > 0:
            all_results.append(result)
            
            if result.get('total_trades', 0) == 0:
                print(f"  {symbol:4s} ({row['name']:6s}) | 无交易")
            else:
                print(f"  {symbol:4s} ({row['name']:6s}) | "
                      f"收益:{result.get('total_return_pct', 0):+.1f}% | "
                      f"交易:{result.get('total_trades', 0):3d}笔 "
                      f"(多{result.get('long_trades', 0):3d}/空{result.get('short_trades', 0):3d}) | "
                      f"胜率:{result.get('win_rate_pct', 0):.1f}% "
                      f"(多{result.get('long_win_rate', 0):.0f}%/空{result.get('short_win_rate', 0):.0f}%) | "
                      f"回撤:{result.get('max_drawdown_pct', 0):.1f}% | "
                      f"夏普:{result.get('sharpe_ratio', 0):.2f}")
    
    return all_results


def run_monte_carlo_v2(strategy, symbol, start_date, end_date, capital, n_simulations=100):
    """蒙特卡罗模拟v2"""
    print(f"\n蒙特卡罗模拟: {symbol} ({n_simulations}次, v2优化版)")
    print("-" * 60)
    
    results = []
    
    for i in range(n_simulations):
        params = OptimizedParams(
            percentile_window=int(np.random.uniform(30, 50)),
            long_entry_pct=np.random.uniform(0.20, 0.40),
            short_entry_pct=np.random.uniform(0.60, 0.80),
            ema_fast=int(np.random.uniform(12, 22)),
            ema_slow=int(np.random.uniform(35, 60)),
            atr_stop_mult=np.random.uniform(1.5, 2.2),
            atr_take_mult=np.random.uniform(2.0, 3.5),
            trailing_trigger=np.random.uniform(0.02, 0.05),
            max_hold_days=int(np.random.uniform(7, 14)),
        )
        
        strategy.params = params
        result = strategy.backtest_single_symbol(symbol, start_date, end_date, capital)
        
        if 'error' not in result or result.get('total_trades', 0) > 0:
            results.append({
                'iteration': i,
                'total_return_pct': result.get('total_return_pct', 0),
                'annual_return_pct': result.get('annual_return_pct', 0),
                'win_rate_pct': result.get('win_rate_pct', 0),
                'max_drawdown_pct': result.get('max_drawdown_pct', 0),
                'sharpe_ratio': result.get('sharpe_ratio', 0),
                'total_trades': result.get('total_trades', 0),
            })
        
        if (i + 1) % 20 == 0:
            print(f"  完成 {i+1}/{n_simulations} 次...")
    
    return results


def compare_with_v1(v2_results, v1_summary_path):
    """对比v1和v2结果"""
    try:
        v1_df = pd.read_csv(v1_summary_path)
    except FileNotFoundError:
        print("\n⚠️  v1结果文件未找到，跳过对比")
        return
    
    v2_data = []
    for r in v2_results:
        if 'error' not in r or r.get('total_trades', 0) > 0:
            v2_data.append({
                'symbol': r.get('symbol'),
                'total_return_pct': r.get('total_return_pct'),
                'annual_return_pct': r.get('annual_return_pct'),
                'total_trades': r.get('total_trades'),
                'win_rate_pct': r.get('win_rate_pct'),
                'max_drawdown_pct': r.get('max_drawdown_pct'),
                'sharpe_ratio': r.get('sharpe_ratio'),
            })
    
    v2_df = pd.DataFrame(v2_data)
    
    # 合并对比
    merged = v1_df.merge(v2_df, on='symbol', suffixes=('_v1', '_v2'), how='inner')
    
    if len(merged) == 0:
        print("\n⚠️  无共同品种，跳过对比")
        return
    
    print("\n" + "=" * 100)
    print("v1 vs v2 优化对比")
    print("=" * 100)
    
    improvements = []
    for _, row in merged.iterrows():
        symbol = row['symbol']
        ret_change = row['total_return_pct_v2'] - row['total_return_pct_v1']
        dd_change = row['max_drawdown_pct_v2'] - row['max_drawdown_pct_v1']
        sharpe_change = row['sharpe_ratio_v2'] - row['sharpe_ratio_v1']
        
        status = "✅" if ret_change > 0 else "❌"
        print(f"  {status} {symbol:4s} | "
              f"收益: {row['total_return_pct_v1']:+.1f}% → {row['total_return_pct_v2']:+.1f}% ({ret_change:+.1f}pp) | "
              f"回撤: {row['max_drawdown_pct_v1']:.1f}% → {row['max_drawdown_pct_v2']:.1f}% ({dd_change:+.1f}pp) | "
              f"夏普: {row['sharpe_ratio_v1']:.2f} → {row['sharpe_ratio_v2']:.2f} ({sharpe_change:+.2f})")
        
        improvements.append({
            'symbol': symbol,
            'return_change': ret_change,
            'dd_change': dd_change,
            'sharpe_change': sharpe_change,
        })
    
    imp_df = pd.DataFrame(improvements)
    improved_count = len(imp_df[imp_df['return_change'] > 0])
    dd_reduced = len(imp_df[imp_df['dd_change'] < 0])
    
    print(f"\n汇总:")
    print(f"  收益改善: {improved_count}/{len(imp_df)} 个品种")
    print(f"  回撤降低: {dd_reduced}/{len(imp_df)} 个品种")
    print(f"  平均收益变化: {imp_df['return_change'].mean():+.2f}pp")
    print(f"  平均回撤变化: {imp_df['dd_change'].mean():+.2f}pp")
    print(f"  平均夏普变化: {imp_df['sharpe_change'].mean():+.2f}")


def analyze_mc_results_v2(mc_results):
    """分析蒙特卡罗v2结果"""
    if len(mc_results) == 0:
        return
    
    df = pd.DataFrame(mc_results)
    print(f"\n  有效模拟: {len(df)}次")
    print(f"  平均年化: {df['annual_return_pct'].mean():+.2f}%")
    print(f"  中位数:   {df['annual_return_pct'].median():+.2f}%")
    print(f"  最佳:     {df['annual_return_pct'].max():+.2f}%")
    print(f"  最差:     {df['annual_return_pct'].min():+.2f}%")
    print(f"  平均回撤: {df['max_drawdown_pct'].mean():.2f}%")
    print(f"  平均夏普: {df['sharpe_ratio'].mean():.2f}")
    
    profitable = len(df[df['annual_return_pct'] > 0])
    print(f"  盈利概率: {profitable}/{len(df)} ({profitable/len(df)*100:.1f}%)")


if __name__ == "__main__":
    print("=" * 100)
    print("路径二 v2：优化版实验运行")
    print("核心改进: ATR止损1.8x | 移动止损3%触发 | 趋势过滤 | 做多信号放宽 | 超时10天")
    print("=" * 100)
    
    strategy = OptimizedQuantileStrategy(OptimizedParams())
    
    # 1. 全期回测v2
    print("\n[步骤1] 全期回测 v2 (2020-2025)...")
    v2_results = run_all_symbols_v2(
        strategy, CONFIG["full_start"], CONFIG["full_end"], CONFIG["initial_capital"]
    )
    
    # 2. 蒙特卡罗v2（选v2表现最好的品种）
    if v2_results:
        valid = [r for r in v2_results if 'error' not in r]
        if valid:
            best = max(valid, key=lambda x: x.get('annual_return_pct', -999))
            best_symbol = best['symbol']
            
            print(f"\n[步骤2] 蒙特卡罗模拟 v2 - {best_symbol}...")
            mc_results = run_monte_carlo_v2(
                strategy, best_symbol,
                CONFIG["full_start"], CONFIG["full_end"],
                CONFIG["initial_capital"], n_simulations=100,
            )
            analyze_mc_results_v2(mc_results)
        else:
            mc_results = []
    else:
        mc_results = []
    
    # 3. 对比v1
    print("\n[步骤3] v1 vs v2 对比...")
    v1_path = os.path.join(CONFIG["output_dir"], "latest_backtest_summary.csv")
    compare_with_v1(v2_results, v1_path)
    
    # 4. 保存结果
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    v2_summary = []
    for r in v2_results:
        if 'error' not in r or r.get('total_trades', 0) > 0:
            v2_summary.append({
                'symbol': r.get('symbol'),
                'initial_capital': r.get('initial_capital'),
                'final_capital': r.get('final_capital'),
                'total_return_pct': r.get('total_return_pct'),
                'annual_return_pct': r.get('annual_return_pct'),
                'total_trades': r.get('total_trades'),
                'long_trades': r.get('long_trades'),
                'short_trades': r.get('short_trades'),
                'long_win_rate': r.get('long_win_rate'),
                'short_win_rate': r.get('short_win_rate'),
                'win_rate_pct': r.get('win_rate_pct'),
                'profit_factor': r.get('profit_factor'),
                'max_drawdown_pct': r.get('max_drawdown_pct'),
                'sharpe_ratio': r.get('sharpe_ratio'),
                'calmar_ratio': r.get('calmar_ratio'),
            })
    
    if v2_summary:
        v2_df = pd.DataFrame(v2_summary)
        v2_path = os.path.join(CONFIG["output_dir"], f"backtest_v2_{timestamp}.csv")
        v2_df.to_csv(v2_path, index=False, encoding='utf-8-sig')
        print(f"\nv2结果已保存: {v2_path}")
    
    if mc_results:
        mc_df = pd.DataFrame(mc_results)
        mc_path = os.path.join(CONFIG["output_dir"], f"monte_carlo_v2_{timestamp}.csv")
        mc_df.to_csv(mc_path, index=False, encoding='utf-8-sig')
        print(f"蒙特卡罗v2已保存: {mc_path}")
    
    print("\n" + "=" * 100)
    print("v2实验完成!")
    print("=" * 100)
