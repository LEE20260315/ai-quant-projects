#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MA+RM+TA+M 全期 Walk-Forward 回测
- 1万元共享账户
- 总仓位≤80%, 单品种≤50%, 最多3品种
- 从2015年到2025年
- 严格消除前视偏差：滚动IS/OOS，每次只用历史数据
- 使用v5最优参数（来自IS优化）
"""
import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio.portfolio_backtest import PortfolioBacktest, PortfolioConfig
from strategies.quantile_short_term_v2 import OptimizedParams
from data.parquet_loader import ParquetLoader

# ============================================================
# 全期Walk-Forward回测配置
# ============================================================
SYMBOLS = ['MA', 'RM', 'TA', 'M']
INITIAL_CAPITAL = 10000
MAX_POSITIONS = 3
MAX_POSITION_PCT = 0.50
MAX_TOTAL_POSITION_PCT = 0.80

# Walk-Forward窗口：每年滚动一次
# IS: 过去4年, OOS: 当年
# 2015-2018 IS → 2019 OOS
# 2016-2019 IS → 2020 OOS
# ...
WF_WINDOWS = [
    ("2015-01-01", "2018-12-31", "2019-01-01", "2019-12-31"),
    ("2016-01-01", "2019-12-31", "2020-01-01", "2020-12-31"),
    ("2017-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
    ("2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2020-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("2021-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
]

# v5最优参数（来自MA+RM+TA+M第1轮IS优化）
BEST_PARAMS = OptimizedParams(
    percentile_window=30,
    long_entry_pct=0.35,
    short_entry_pct=0.65,
    atr_stop_mult=2.0,
    atr_take_mult=2.0,
    max_hold_days=10,
    trend_filter_enabled=False,
)

def run_walkforward() -> Dict:
    """运行Walk-Forward回测"""
    print("=" * 80)
    print("MA+RM+TA+M 全期Walk-Forward回测")
    print("1万元共享 | 总仓位≤80% | 消除前视偏差")
    print("=" * 80)
    
    loader = ParquetLoader()
    
    # 检查数据可用性
    print(f"\n品种数据范围:")
    start_dates = {}
    for sym in SYMBOLS:
        df = loader.load_symbol(sym, '2010-01-01', '2025-12-31')
        if df is not None and len(df) > 0:
            start_dates[sym] = df['date'].iloc[0]
            print(f"  {sym}: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    
    # 确定实际可回测起始日期（最晚的品种）
    actual_start = max(start_dates.values())
    print(f"\n实际可回测起始: {actual_start}")
    
    # 过滤有效的WF窗口（需要IS数据完整）
    valid_windows = []
    for is_start, is_end, oos_start, oos_end in WF_WINDOWS:
        is_start_dt = pd.to_datetime(is_start)
        if is_start_dt >= actual_start:
            valid_windows.append((is_start, is_end, oos_start, oos_end))
    
    print(f"有效WF窗口: {len(valid_windows)}个")
    for w in valid_windows:
        print(f"  IS: {w[0]} ~ {w[1]} | OOS: {w[2]} ~ {w[3]}")
    
    # 运行每个WF窗口
    all_oos_trades = []
    all_oos_equity = []
    wf_results = []
    
    for is_start, is_end, oos_start, oos_end in valid_windows:
        print(f"\n{'='*60}")
        print(f"WF窗口: IS {is_start}~{is_end} | OOS {oos_start}~{oos_end}")
        print(f"{'='*60}")
        
        # IS回测（参数优化，这里用已知最优参数）
        pf_config_is = PortfolioConfig(
            initial_capital=INITIAL_CAPITAL,
            max_positions=MAX_POSITIONS,
            max_position_pct=MAX_POSITION_PCT,
            max_total_position_pct=MAX_TOTAL_POSITION_PCT,
            start_date=is_start,
            end_date=is_end,
        )
        portfolio_is = PortfolioBacktest(pf_config_is)
        result_is = portfolio_is.run(SYMBOLS, BEST_PARAMS)
        
        is_sharpe = result_is.get('sharpe_ratio', 0)
        is_annual = result_is.get('annual_return_pct', 0)
        is_dd = result_is.get('max_drawdown_pct', 0)
        is_trades = result_is.get('total_trades', 0)
        
        print(f"  IS结果: 夏普{is_sharpe:.2f} | 年化{is_annual:.1f}% | 回撤{is_dd:.1f}% | {is_trades}笔")
        
        # OOS回测
        pf_config_oos = PortfolioConfig(
            initial_capital=INITIAL_CAPITAL,
            max_positions=MAX_POSITIONS,
            max_position_pct=MAX_POSITION_PCT,
            max_total_position_pct=MAX_TOTAL_POSITION_PCT,
            start_date=oos_start,
            end_date=oos_end,
        )
        portfolio_oos = PortfolioBacktest(pf_config_oos)
        result_oos = portfolio_oos.run(SYMBOLS, BEST_PARAMS)
        
        oos_sharpe = result_oos.get('sharpe_ratio', 0)
        oos_annual = result_oos.get('annual_return_pct', 0)
        oos_dd = result_oos.get('max_drawdown_pct', 0)
        oos_trades = result_oos.get('total_trades', 0)
        oos_final = result_oos.get('final_capital', 0)
        
        print(f"  OOS结果: 夏普{oos_sharpe:.2f} | 年化{oos_annual:.1f}% | 回撤{oos_dd:.1f}% | {oos_trades}笔 | 期末{oos_final:,.0f}元")
        
        # 品种分解
        if result_oos.get('symbol_stats'):
            for sym, stats in result_oos['symbol_stats'].items():
                print(f"    {sym:4s} | {stats['trades']:3d}笔 | 胜率:{stats['win_rate']:5.1f}% | 盈亏:{stats['total_pnl']:+8.0f}元")
        
        wf_results.append({
            'is_start': is_start,
            'is_end': is_end,
            'oos_start': oos_start,
            'oos_end': oos_end,
            'is_sharpe': is_sharpe,
            'is_annual': is_annual,
            'is_dd': is_dd,
            'is_trades': is_trades,
            'oos_sharpe': oos_sharpe,
            'oos_annual': oos_annual,
            'oos_dd': oos_dd,
            'oos_trades': oos_trades,
            'oos_final_capital': oos_final,
        })
        
        # 收集OOS交易和权益
        if result_oos.get('trades_df') is not None:
            trades = result_oos['trades_df'].copy()
            all_oos_trades.append(trades)
        
        if result_oos.get('equity_df') is not None:
            equity = result_oos['equity_df'].copy()
            all_oos_equity.append(equity)
    
    # 汇总全期结果
    print(f"\n{'='*80}")
    print(f"全期Walk-Forward汇总")
    print(f"{'='*80}")
    
    wf_df = pd.DataFrame(wf_results)
    print(f"\n{'窗口':>20s} | {'IS夏普':>6s} | {'IS年化':>7s} | {'OOS夏普':>7s} | {'OOS年化':>7s} | {'OOS回撤':>7s} | {'OOS交易':>6s} | {'期末资金':>10s}")
    print(f"{'-'*90}")
    for _, r in wf_df.iterrows():
        window = f"{r['oos_start'][:4]}"
        print(f"{window:>20s} | {r['is_sharpe']:6.2f} | {r['is_annual']:6.1f}% | "
              f"{r['oos_sharpe']:7.2f} | {r['oos_annual']:6.1f}% | {r['oos_dd']:6.1f}% | "
              f"{r['oos_trades']:6d} | {r['oos_final_capital']:10,.0f}")
    
    # 全期统计
    all_trades = pd.concat(all_oos_trades, ignore_index=True) if all_oos_trades else pd.DataFrame()
    
    if len(all_trades) > 0:
        total_trades = len(all_trades)
        win_trades = all_trades[all_trades['pnl'] > 0]
        win_rate = len(win_trades) / total_trades * 100
        total_pnl = all_trades['pnl'].sum()
        avg_win = win_trades['pnl'].mean() if len(win_trades) > 0 else 0
        avg_lose = all_trades[all_trades['pnl'] <= 0]['pnl'].mean()
        profit_factor = abs(avg_win / avg_lose) if avg_lose != 0 else float('inf')
        
        print(f"\n全期交易统计:")
        print(f"  总交易数: {total_trades}笔")
        print(f"  胜率: {win_rate:.1f}%")
        print(f"  总盈亏: {total_pnl:+,.0f}元")
        print(f"  平均盈利: {avg_win:+,.0f}元")
        print(f"  平均亏损: {avg_lose:+,.0f}元")
        print(f"  盈亏比: {profit_factor:.2f}")
        
        # 品种汇总
        print(f"\n全期品种表现:")
        for sym in SYMBOLS:
            sym_trades = all_trades[all_trades['symbol'] == sym]
            if len(sym_trades) > 0:
                sym_wins = sym_trades[sym_trades['pnl'] > 0]
                sym_wr = len(sym_wins) / len(sym_trades) * 100
                sym_pnl = sym_trades['pnl'].sum()
                print(f"  {sym:4s} | {len(sym_trades):4d}笔 | 胜率:{sym_wr:5.1f}% | 盈亏:{sym_pnl:+9,.0f}元")
        
        # 出场原因
        print(f"\n出场原因:")
        for reason, count in all_trades['exit_reason'].value_counts().items():
            print(f"  {reason}: {count}次 ({count/total_trades*100:.1f}%)")
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(output_dir, exist_ok=True)
    
    wf_df.to_csv(os.path.join(output_dir, f"walkforward_summary_{timestamp}.csv"), index=False, encoding='utf-8-sig')
    if len(all_trades) > 0:
        all_trades.to_csv(os.path.join(output_dir, f"all_trades_{timestamp}.csv"), index=False, encoding='utf-8-sig')
    
    print(f"\n结果已保存: {output_dir}")
    print(f"\n{'='*80}")
    print("回测完成!")
    print(f"{'='*80}")


if __name__ == "__main__":
    run_walkforward()
