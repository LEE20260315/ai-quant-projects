#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二：轻量级分位数短线系统
实验运行入口 - 批量回测所有可用品种 + 蒙特卡罗模拟
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategies.quantile_short_term import QuantileShortTermStrategy, StrategyParams
from data.parquet_loader import ParquetLoader, LOW_MARGIN_SYMBOLS


# ============================================================
# 实验配置
# ============================================================
CONFIG = {
    # 时间分割
    "train_start": "2020-01-01",
    "train_end": "2023-12-31",
    "test_start": "2024-01-01", 
    "test_end": "2025-12-31",
    
    # 全期回测
    "full_start": "2020-01-01",
    "full_end": "2025-12-31",
    
    # 资金
    "initial_capital": 10000,
    
    # 输出
    "output_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"),
}


def run_single_symbol_test(strategy, symbol, start_date, end_date, capital):
    """运行单个品种的回测"""
    result = strategy.backtest_single_symbol(symbol, start_date, end_date, capital)
    return result


def run_all_symbols_test(strategy, start_date, end_date, capital):
    """批量回测所有可用品种"""
    loader = ParquetLoader()
    availability = loader.check_data_availability()
    available = availability[availability['file_exists'] == True]
    
    print(f"\n开始回测 {len(available)} 个品种...")
    print(f"时间: {start_date} 至 {end_date}")
    print(f"初始资金: {capital:,.0f}元")
    print("-" * 80)
    
    all_results = []
    
    for _, row in available.iterrows():
        symbol = row['symbol']
        result = run_single_symbol_test(strategy, symbol, start_date, end_date, capital)
        
        if 'error' not in result or result.get('total_trades', 0) > 0:
            all_results.append(result)
            
            if 'error' in result and result.get('total_trades', 0) == 0:
                print(f"  {symbol:4s} ({row['name']:6s}) | 无交易")
            else:
                print(f"  {symbol:4s} ({row['name']:6s}) | "
                      f"收益:{result.get('total_return_pct', 0):+.1f}% | "
                      f"交易:{result.get('total_trades', 0):3d}笔 | "
                      f"胜率:{result.get('win_rate_pct', 0):.1f}% | "
                      f"回撤:{result.get('max_drawdown_pct', 0):.1f}%")
    
    return all_results


def run_monte_carlo(strategy, symbol, start_date, end_date, 
                   capital, n_simulations=100):
    """
    简化的蒙特卡罗模拟 - 参数随机扰动
    
    每次随机调整策略参数，观察收益分布
    """
    print(f"\n蒙特卡罗模拟: {symbol} ({n_simulations}次)")
    print("-" * 60)
    
    results = []
    
    for i in range(n_simulations):
        # 随机扰动参数
        params = StrategyParams(
            percentile_window=int(np.random.uniform(30, 50)),
            long_entry_pct=np.random.uniform(0.20, 0.40),
            short_entry_pct=np.random.uniform(0.60, 0.80),
            ema_fast=int(np.random.uniform(12, 22)),
            ema_slow=int(np.random.uniform(35, 60)),
            atr_stop_mult=np.random.uniform(1.0, 2.0),
            atr_take_mult=np.random.uniform(1.5, 3.0),
            trailing_trigger=np.random.uniform(0.005, 0.02),
            trailing_pct_low=np.random.uniform(0.05, 0.15),
            trailing_pct_mid=np.random.uniform(0.10, 0.20),
            trailing_pct_high=np.random.uniform(0.20, 0.30),
            max_hold_days=int(np.random.uniform(5, 10)),
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
                'params': {
                    'percentile_window': params.percentile_window,
                    'long_entry_pct': params.long_entry_pct,
                    'short_entry_pct': params.short_entry_pct,
                    'atr_stop_mult': params.atr_stop_mult,
                    'max_hold_days': params.max_hold_days,
                }
            })
        
        if (i + 1) % 20 == 0:
            print(f"  完成 {i+1}/{n_simulations} 次模拟...")
    
    return results


def analyze_monte_carlo_results(mc_results):
    """分析蒙特卡罗结果"""
    if len(mc_results) == 0:
        print("  无有效模拟结果")
        return
    
    df = pd.DataFrame(mc_results)
    
    print(f"\n  有效模拟次数: {len(df)}")
    print(f"\n  收益分布:")
    print(f"    平均年化: {df['annual_return_pct'].mean():+.2f}%")
    print(f"    中位数:   {df['annual_return_pct'].median():+.2f}%")
    print(f"    最佳:     {df['annual_return_pct'].max():+.2f}%")
    print(f"    最差:     {df['annual_return_pct'].min():+.2f}%")
    print(f"    标准差:   {df['annual_return_pct'].std():.2f}%")
    
    print(f"\n  风险指标:")
    print(f"    平均最大回撤: {df['max_drawdown_pct'].mean():.2f}%")
    print(f"    最差回撤:     {df['max_drawdown_pct'].min():.2f}%")
    print(f"    平均夏普:     {df['sharpe_ratio'].mean():.2f}")
    
    print(f"\n  盈利概率:")
    profitable = len(df[df['annual_return_pct'] > 0])
    print(f"    {profitable}/{len(df)} ({profitable/len(df)*100:.1f}%) 模拟盈利")
    
    # VaR (5%)
    var_5 = df['annual_return_pct'].quantile(0.05)
    cvar_5 = df[df['annual_return_pct'] <= var_5]['annual_return_pct'].mean()
    print(f"\n  VaR(5%):  {var_5:.2f}%")
    print(f"  CVaR(5%): {cvar_5:.2f}%")
    
    # 最优参数区间
    top_10 = df.nlargest(10, 'annual_return_pct')
    print(f"\n  Top 10% 最优参数区间:")
    print(f"    分位数窗口: {top_10['params'].apply(lambda x: x['percentile_window']).mean():.0f}")
    print(f"    做多阈值:   {top_10['params'].apply(lambda x: x['long_entry_pct']).mean():.2f}")
    print(f"    做空阈值:   {top_10['params'].apply(lambda x: x['short_entry_pct']).mean():.2f}")
    print(f"    ATR止损:    {top_10['params'].apply(lambda x: x['atr_stop_mult']).mean():.2f}x")
    print(f"    最大持仓:   {top_10['params'].apply(lambda x: x['max_hold_days']).mean():.0f}天")


def save_results(all_results, mc_results, output_dir):
    """保存结果到文件"""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存品种回测结果
    summary_data = []
    for r in all_results:
        if 'error' not in r or r.get('total_trades', 0) > 0:
            summary_data.append({
                'symbol': r.get('symbol'),
                'initial_capital': r.get('initial_capital'),
                'final_capital': r.get('final_capital'),
                'total_return_pct': r.get('total_return_pct'),
                'annual_return_pct': r.get('annual_return_pct'),
                'total_trades': r.get('total_trades'),
                'win_rate_pct': r.get('win_rate_pct'),
                'profit_factor': r.get('profit_factor'),
                'max_drawdown_pct': r.get('max_drawdown_pct'),
                'sharpe_ratio': r.get('sharpe_ratio'),
                'calmar_ratio': r.get('calmar_ratio'),
            })
    
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        summary_file = os.path.join(output_dir, f"backtest_summary_{timestamp}.csv")
        summary_df.to_csv(summary_file, index=False, encoding='utf-8-sig')
        print(f"\n品种回测结果已保存: {summary_file}")
    
    # 保存蒙特卡罗结果
    if mc_results:
        mc_df = pd.DataFrame(mc_results)
        mc_file = os.path.join(output_dir, f"monte_carlo_{timestamp}.csv")
        mc_df.to_csv(mc_file, index=False, encoding='utf-8-sig')
        print(f"蒙特卡罗结果已保存: {mc_file}")


# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("路径二：轻量级分位数短线系统 - 实验运行")
    print("=" * 80)
    
    # 创建策略（默认参数）
    strategy = QuantileShortTermStrategy(StrategyParams())
    
    # 1. 检查数据可用性
    print("\n[步骤1] 检查数据可用性...")
    loader = ParquetLoader()
    availability = loader.check_data_availability()
    available = availability[availability['file_exists'] == True]
    print(f"  可用品种: {len(available)} / {len(LOW_MARGIN_SYMBOLS)}")
    
    # 2. 样本内回测（2020-2023）
    print("\n[步骤2] 样本内回测 (2020-2023)...")
    train_results = run_all_symbols_test(
        strategy, 
        CONFIG["train_start"], 
        CONFIG["train_end"],
        CONFIG["initial_capital"],
    )
    
    # 3. 样本外回测（2024-2025）
    print("\n[步骤3] 样本外回测 (2024-2025)...")
    test_results = run_all_symbols_test(
        strategy,
        CONFIG["test_start"],
        CONFIG["test_end"],
        CONFIG["initial_capital"],
    )
    
    # 4. 全期回测（2020-2025）
    print("\n[步骤4] 全期回测 (2020-2025)...")
    full_results = run_all_symbols_test(
        strategy,
        CONFIG["full_start"],
        CONFIG["full_end"],
        CONFIG["initial_capital"],
    )
    
    # 5. 蒙特卡罗模拟（选表现最好的品种）
    if full_results:
        # 找年化收益最好的品种
        valid_results = [r for r in full_results if 'error' not in r]
        if valid_results:
            best = max(valid_results, key=lambda x: x.get('annual_return_pct', -999))
            best_symbol = best['symbol']
            
            print(f"\n[步骤5] 蒙特卡罗模拟 - 最佳品种 {best_symbol}...")
            mc_results = run_monte_carlo(
                strategy,
                best_symbol,
                CONFIG["full_start"],
                CONFIG["full_end"],
                CONFIG["initial_capital"],
                n_simulations=100,
            )
            
            analyze_monte_carlo_results(mc_results)
        else:
            mc_results = []
            print("\n无有效回测结果，跳过蒙特卡罗模拟")
    else:
        mc_results = []
    
    # 6. 保存结果
    print("\n[步骤6] 保存结果...")
    save_results(full_results, mc_results, CONFIG["output_dir"])
    
    print("\n" + "=" * 80)
    print("实验运行完成!")
    print("=" * 80)
