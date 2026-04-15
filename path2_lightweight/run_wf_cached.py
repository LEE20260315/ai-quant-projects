#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MA+RM+TA+M 真实Walk-Forward回测（带断点续跑）
"""
import os, sys, json, pickle
import numpy as np, pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio.portfolio_backtest import PortfolioBacktest, PortfolioConfig
from strategies.quantile_short_term_v2 import OptimizedParams
from data.parquet_loader import ParquetLoader

SYMBOLS = ['MA', 'RM', 'TA']
PARAM_GRID = {
    'percentile_window': [25, 30, 40, 50],
    'long_entry_pct': [0.20, 0.25, 0.30, 0.35],
    'short_entry_pct': [0.65, 0.70, 0.75, 0.80],
    'atr_stop_mult': [1.5, 1.8, 2.0, 2.5],
    'atr_take_mult': [2.0, 2.5, 3.0],
    'max_hold_days': [7, 10, 14, 20],
}

WF_WINDOWS = [
    ("2015-01-01", "2018-12-31", "2019-01-01", "2019-12-31"),
    ("2016-01-01", "2019-12-31", "2020-01-01", "2020-12-31"),
    ("2017-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
    ("2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2020-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("2021-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
]

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wf_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def main():
    loader = ParquetLoader()
    starts = {}
    for sym in SYMBOLS:
        df = loader.load_symbol(sym, '2010-01-01', '2025-12-31')
        if df is not None and len(df) > 0:
            starts[sym] = df['date'].iloc[0]
    actual_start = max(starts.values())
    print(f"品种起始: MA={starts.get('MA')}, RM={starts.get('RM')}, TA={starts.get('TA')}, M={starts.get('M')}")
    print(f"实际可回测起始: {actual_start}")
    
    # 加载缓存
    cache_file = os.path.join(CACHE_DIR, "wf_cache.pkl")
    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            cache = pickle.load(f)
        print(f"缓存已加载: {len(cache)}个窗口")
    
    results = {}
    for i, (ws, we, os_, oe) in enumerate(WF_WINDOWS):
        key = f"{os_[:4]}"
        if key in cache:
            print(f"[{i+1}/7] {key}: 使用缓存")
            results[key] = cache[key]
            continue
        
        if pd.to_datetime(ws) < actual_start:
            print(f"[{i+1}/7] {key}: 数据不足，跳过")
            continue
        
        print(f"\n[{i+1}/7] {key}: IS={ws}~{we} | OOS={os_}~{oe}")
        
        # IS优化（简化：20次搜索）
        best_sharpe = -999
        best_p = None
        names = list(PARAM_GRID.keys())
        values = list(PARAM_GRID.values())
        
        for j in range(20):
            sp = {n: values[k][np.random.randint(len(values[k]))] for k, n in enumerate(names)}
            p = OptimizedParams(
                percentile_window=int(sp['percentile_window']), long_entry_pct=sp['long_entry_pct'],
                short_entry_pct=sp['short_entry_pct'], atr_stop_mult=sp['atr_stop_mult'],
                atr_take_mult=sp['atr_take_mult'], max_hold_days=int(sp['max_hold_days']),
                trend_filter_enabled=False)
            cfg = PortfolioConfig(initial_capital=10000, max_positions=3, max_position_pct=0.50,
                                  max_total_position_pct=0.80, start_date=ws, end_date=we)
            r = PortfolioBacktest(cfg).run(SYMBOLS, p)
            if r.get('total_trades', 0) >= 20 and r.get('sharpe_ratio', -999) > best_sharpe:
                best_sharpe = r['sharpe_ratio']
                best_p = sp
        
        if best_p is None:
            print(f"  IS无有效结果")
            continue
        
        is_sharpe = best_sharpe
        
        # OOS
        p = OptimizedParams(
            percentile_window=int(best_p['percentile_window']), long_entry_pct=best_p['long_entry_pct'],
            short_entry_pct=best_p['short_entry_pct'], atr_stop_mult=best_p['atr_stop_mult'],
            atr_take_mult=best_p['atr_take_mult'], max_hold_days=int(best_p['max_hold_days']),
            trend_filter_enabled=False)
        cfg = PortfolioConfig(initial_capital=10000, max_positions=3, max_position_pct=0.50,
                              max_total_position_pct=0.80, start_date=os_, end_date=oe)
        r = PortfolioBacktest(cfg).run(SYMBOLS, p)
        
        rec = {
            'year': key,
            'is_sharpe': is_sharpe,
            'oos_sharpe': r.get('sharpe_ratio', 0),
            'oos_annual': r.get('annual_return_pct', 0),
            'oos_dd': r.get('max_drawdown_pct', 0),
            'oos_trades': r.get('total_trades', 0),
            'oos_final': r.get('final_capital', 0),
            'symbol_stats': r.get('symbol_stats', {}),
        }
        results[key] = rec
        cache[key] = rec
        
        with open(cache_file, 'wb') as f:
            pickle.dump(cache, f)
        
        print(f"  IS夏普={is_sharpe:.2f} | OOS夏普={rec['oos_sharpe']:.2f} | "
              f"OOS年化={rec['oos_annual']:.1f}% | 回撤={rec['oos_dd']:.1f}% | 期末={rec['oos_final']:,.0f}")
        for sym, stats in rec['symbol_stats'].items():
            print(f"    {sym:4s}: {stats['trades']:3d}笔 胜率{stats['win_rate']:.1f}% 盈亏{stats['total_pnl']:+.0f}")
    
    # 汇总
    print(f"\n{'='*80}")
    print(f"{'年份':>4s} | {'IS夏普':>6s} | {'OOS夏普':>7s} | {'OOS年化':>7s} | {'OOS回撤':>7s} | "
          f"{'交易':>4s} | {'期末资金':>9s}")
    print(f"{'-'*70}")
    for key in ['2019','2020','2021','2022','2023','2024','2025']:
        if key in results:
            r = results[key]
            print(f"{key:>4s} | {r['is_sharpe']:6.2f} | {r['oos_sharpe']:7.2f} | "
                  f"{r['oos_annual']:6.1f}% | {r['oos_dd']:6.1f}% | {r['oos_trades']:4d} | "
                  f"{r['oos_final']:9,.0f}")

if __name__ == "__main__":
    main()
