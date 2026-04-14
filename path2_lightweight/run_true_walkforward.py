#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MA+RM+TA+M 真实Walk-Forward回测
- 每个IS窗口重新做参数优化（随机搜索50次）
- 用该窗口最优参数跑OOS
- 严格消除前视偏差
- 1万元共享账户，总仓位≤80%
"""
import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio.portfolio_backtest import PortfolioBacktest, PortfolioConfig
from strategies.quantile_short_term_v2 import OptimizedParams
from data.parquet_loader import ParquetLoader

SYMBOLS = ['MA', 'RM', 'TA', 'M']
INITIAL_CAPITAL = 10000
MAX_POSITIONS = 3
MAX_POSITION_PCT = 0.50
MAX_TOTAL_POSITION_PCT = 0.80

# 参数搜索空间
PARAM_GRID = {
    'percentile_window': [25, 30, 40, 50],
    'long_entry_pct': [0.20, 0.25, 0.30, 0.35],
    'short_entry_pct': [0.65, 0.70, 0.75, 0.80],
    'atr_stop_mult': [1.5, 1.8, 2.0, 2.5],
    'atr_take_mult': [2.0, 2.5, 3.0],
    'max_hold_days': [7, 10, 14, 20],
}
N_SEARCH = 50  # 每次IS随机搜索50次

# WF窗口：逐年滚动
WF_WINDOWS = [
    ("2015-01-01", "2018-12-31", "2019-01-01", "2019-12-31"),
    ("2016-01-01", "2019-12-31", "2020-01-01", "2020-12-31"),
    ("2017-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
    ("2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2020-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("2021-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
]

def optimize_is(is_start, is_end, symbols):
    """IS参数优化"""
    grid = PARAM_GRID
    names = list(grid.keys())
    values = list(grid.values())
    
    best_sharpe = -999
    best_params = None
    best_metrics = None
    all_results = []
    
    for i in range(N_SEARCH):
        sampled = {n: values[j][np.random.randint(len(values[j]))] for j, n in enumerate(names)}
        
        p = OptimizedParams(
            percentile_window=int(sampled['percentile_window']),
            long_entry_pct=sampled['long_entry_pct'],
            short_entry_pct=sampled['short_entry_pct'],
            atr_stop_mult=sampled['atr_stop_mult'],
            atr_take_mult=sampled['atr_take_mult'],
            max_hold_days=int(sampled['max_hold_days']),
            trend_filter_enabled=False,
        )
        
        cfg = PortfolioConfig(
            initial_capital=INITIAL_CAPITAL,
            max_positions=MAX_POSITIONS,
            max_position_pct=MAX_POSITION_PCT,
            max_total_position_pct=MAX_TOTAL_POSITION_PCT,
            start_date=is_start,
            end_date=is_end,
        )
        
        result = PortfolioBacktest(cfg).run(symbols, p)
        
        if result.get('total_trades', 0) >= 30:
            sharpe = result.get('sharpe_ratio', -999)
            all_results.append({
                'params': sampled,
                'sharpe': sharpe,
                'annual': result.get('annual_return_pct', 0),
                'dd': result.get('max_drawdown_pct', 0),
            })
            
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = sampled
                best_metrics = {
                    'sharpe': sharpe,
                    'annual': result.get('annual_return_pct', 0),
                    'dd': result.get('max_drawdown_pct', 0),
                    'trades': result.get('total_trades', 0),
                }
        
        if (i+1) % 10 == 0:
            print(f"    IS搜索 {i+1}/{N_SEARCH}... 当前最优夏普: {best_sharpe:.2f}")
    
    return best_params, best_metrics, all_results

def main():
    print("=" * 80)
    print("MA+RM+TA+M 真实Walk-Forward回测")
    print("每窗口IS随机搜索50次 | 严格消除前视偏差")
    print("=" * 80)
    
    # 确定实际起始
    loader = ParquetLoader()
    starts = {}
    for sym in SYMBOLS:
        df = loader.load_symbol(sym, '2010-01-01', '2025-12-31')
        if df is not None and len(df) > 0:
            starts[sym] = df['date'].iloc[0]
            print(f"  {sym}: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]} ({len(df)}行)")
    
    actual_start = max(starts.values())
    print(f"\n实际可回测起始: {actual_start}")
    
    valid_windows = []
    for ws, we, os_, oe in WF_WINDOWS:
        if pd.to_datetime(ws) >= actual_start:
            valid_windows.append((ws, we, os_, oe))
    
    print(f"有效WF窗口: {len(valid_windows)}个\n")
    
    wf_results = []
    all_oos_trades = []
    
    for is_start, is_end, oos_start, oos_end in valid_windows:
        print(f"{'='*70}")
        print(f"IS: {is_start}~{is_end} | OOS: {oos_start}~{oos_end}")
        
        # 1. IS优化
        print(f"[IS优化]")
        best_params, is_metrics, _ = optimize_is(is_start, is_end, SYMBOLS)
        
        if best_params is None:
            print(f"  ⚠️ IS无有效参数，跳过此窗口")
            continue
        
        print(f"  IS最优: 夏普{is_metrics['sharpe']:.2f} | 年化{is_metrics['annual']:.1f}% | "
              f"回撤{is_metrics['dd']:.1f}% | {is_metrics['trades']}笔")
        print(f"  参数: window={best_params['percentile_window']}, "
              f"long={best_params['long_entry_pct']}, short={best_params['short_entry_pct']}, "
              f"stop={best_params['atr_stop_mult']}, take={best_params['atr_take_mult']}, "
              f"hold={best_params['max_hold_days']}")
        
        # 2. OOS验证
        print(f"[OOS验证]")
        p = OptimizedParams(
            percentile_window=int(best_params['percentile_window']),
            long_entry_pct=best_params['long_entry_pct'],
            short_entry_pct=best_params['short_entry_pct'],
            atr_stop_mult=best_params['atr_stop_mult'],
            atr_take_mult=best_params['atr_take_mult'],
            max_hold_days=int(best_params['max_hold_days']),
            trend_filter_enabled=False,
        )
        
        cfg = PortfolioConfig(
            initial_capital=INITIAL_CAPITAL,
            max_positions=MAX_POSITIONS,
            max_position_pct=MAX_POSITION_PCT,
            max_total_position_pct=MAX_TOTAL_POSITION_PCT,
            start_date=oos_start,
            end_date=oos_end,
        )
        
        oos_result = PortfolioBacktest(cfg).run(SYMBOLS, p)
        
        oos_sharpe = oos_result.get('sharpe_ratio', 0)
        oos_annual = oos_result.get('annual_return_pct', 0)
        oos_dd = oos_result.get('max_drawdown_pct', 0)
        oos_trades = oos_result.get('total_trades', 0)
        oos_final = oos_result.get('final_capital', 0)
        
        print(f"  OOS: 夏普{oos_sharpe:.2f} | 年化{oos_annual:.1f}% | "
              f"回撤{oos_dd:.1f}% | {oos_trades}笔 | 期末{oos_final:,.0f}元")
        
        if oos_result.get('symbol_stats'):
            for sym, stats in oos_result['symbol_stats'].items():
                print(f"    {sym:4s} | {stats['trades']:3d}笔 | 胜率:{stats['win_rate']:5.1f}% | "
                      f"盈亏:{stats['total_pnl']:+8.0f}元")
        
        sharpe_decay = abs(is_metrics['sharpe'] - oos_sharpe) / abs(is_metrics['sharpe']) * 100 if is_metrics['sharpe'] != 0 else 999
        is_overfit = sharpe_decay > 50
        
        wf_results.append({
            'is_start': is_start, 'is_end': is_end,
            'oos_start': oos_start, 'oos_end': oos_end,
            'is_sharpe': is_metrics['sharpe'],
            'is_annual': is_metrics['annual'],
            'is_dd': is_metrics['dd'],
            'is_trades': is_metrics['trades'],
            'oos_sharpe': oos_sharpe,
            'oos_annual': oos_annual,
            'oos_dd': oos_dd,
            'oos_trades': oos_trades,
            'oos_final': oos_final,
            'sharpe_decay': sharpe_decay,
            'is_overfit': is_overfit,
            'best_params': best_params,
        })
        
        if oos_result.get('trades_df') is not None:
            all_oos_trades.append(oos_result['trades_df'].copy())
    
    # 汇总
    print(f"\n{'='*90}")
    print(f"真实Walk-Forward汇总")
    print(f"{'='*90}")
    
    print(f"{'年份':>4s} | {'IS夏普':>6s} | {'IS年化':>7s} | {'OOS夏普':>7s} | {'OOS年化':>7s} | "
          f"{'OOS回撤':>7s} | {'交易':>4s} | {'期末资金':>9s} | {'衰减':>6s} | {'过拟合':>5s}")
    print(f"{'-'*100}")
    
    for r in wf_results:
        year = r['oos_start'][:4]
        flag = "⚠️" if r['is_overfit'] else "✅"
        print(f"{year:>4s} | {r['is_sharpe']:6.2f} | {r['is_annual']:6.1f}% | {r['oos_sharpe']:7.2f} | "
              f"{r['oos_annual']:6.1f}% | {r['oos_dd']:6.1f}% | {r['oos_trades']:4d} | "
              f"{r['oos_final']:9,.0f} | {r['sharpe_decay']:5.1f}% | {flag:>5s}")
    
    # 全期统计
    all_trades = pd.concat(all_oos_trades, ignore_index=True) if all_oos_trades else pd.DataFrame()
    
    if len(all_trades) > 0:
        total = len(all_trades)
        wins = all_trades[all_trades['pnl'] > 0]
        wr = len(wins) / total * 100
        pnl = all_trades['pnl'].sum()
        avg_w = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_l = all_trades[all_trades['pnl'] <= 0]['pnl'].mean()
        pf = abs(avg_w / avg_l) if avg_l != 0 else float('inf')
        
        print(f"\n全期统计:")
        print(f"  总交易: {total}笔 | 胜率: {wr:.1f}% | 总盈亏: {pnl:+,.0f}元")
        print(f"  平均盈利: {avg_w:+,.0f} | 平均亏损: {avg_l:+,.0f} | 盈亏比: {pf:.2f}")
        
        print(f"\n品种表现:")
        for sym in SYMBOLS:
            st = all_trades[all_trades['symbol'] == sym]
            if len(st) > 0:
                sw = st[st['pnl'] > 0]
                print(f"  {sym:4s} | {len(st):4d}笔 | 胜率:{len(sw)/len(st)*100:5.1f}% | "
                      f"盈亏:{st['pnl'].sum():+9,.0f}元")
        
        print(f"\n出场原因:")
        for reason, count in all_trades['exit_reason'].value_counts().items():
            print(f"  {reason}: {count}次 ({count/total*100:.1f}%)")
        
        # 保存
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
        os.makedirs(outdir, exist_ok=True)
        all_trades.to_csv(os.path.join(outdir, f"wf_trades_{ts}.csv"), index=False, encoding='utf-8-sig')
        print(f"\n结果已保存: {outdir}")
    
    print(f"\n{'='*90}")
    print("完成!")


if __name__ == "__main__":
    main()
