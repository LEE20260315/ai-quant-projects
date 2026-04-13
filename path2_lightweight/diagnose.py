#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断脚本：分析TA成功而其他品种失败的原因"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategies.quantile_short_term import QuantileShortTermStrategy, StrategyParams
from data.parquet_loader import ParquetLoader, LOW_MARGIN_SYMBOLS
import pandas as pd
import numpy as np

strategy = QuantileShortTermStrategy(StrategyParams())
loader = ParquetLoader()

print("=" * 80)
print("诊断分析：TA成功 vs 其他品种失败")
print("=" * 80)

# ============================================================
# 1. 样本内外对比
# ============================================================
print("\n【1】样本内(2020-2023) vs 样本外(2024-2025) 对比")
print("-" * 80)

all_symbols = [s[0] for s in LOW_MARGIN_SYMBOLS]
periods = {
    'INSAMPLE': ('2020-01-01', '2023-12-31'),
    'OUTSAMPLE': ('2024-01-01', '2025-12-31'),
    'FULL': ('2020-01-01', '2025-12-31'),
}

results_by_symbol = {}

for sym in all_symbols:
    results_by_symbol[sym] = {}
    for period_name, (start, end) in periods.items():
        r = strategy.backtest_single_symbol(sym, start, end, 10000)
        results_by_symbol[sym][period_name] = r

# 打印对比表
print(f"{'品种':4s} | {'样本内收益':>10s} | {'样本外收益':>10s} | {'全期收益':>10s} | {'样本内交易':>8s} | {'样本外交易':>8s}")
print("-" * 80)
for sym in all_symbols:
    def fmt(r, key):
        if 'error' in r and r.get('total_trades', 0) == 0:
            return f"{r.get('error', 'N/A'):>10s}"
        return f"{r.get(key, 0):>10.1f}"
    
    in_r = results_by_symbol[sym]['INSAMPLE']
    out_r = results_by_symbol[sym]['OUTSAMPLE']
    full_r = results_by_symbol[sym]['FULL']
    
    in_ret = f"{in_r.get('total_return_pct', 0):+.1f}%" if 'error' not in in_r else in_r.get('error', 'N/A')
    out_ret = f"{out_r.get('total_return_pct', 0):+.1f}%" if 'error' not in out_r else out_r.get('error', 'N/A')
    full_ret = f"{full_r.get('total_return_pct', 0):+.1f}%" if 'error' not in full_r else full_r.get('error', 'N/A')
    
    in_trades = in_r.get('total_trades', 0)
    out_trades = out_r.get('total_trades', 0)
    
    print(f"{sym:4s} | {in_ret:>10s} | {out_ret:>10s} | {full_ret:>10s} | {in_trades:>8d} | {out_trades:>8d}")

# ============================================================
# 2. TA的详细分析 - 多空统计
# ============================================================
print("\n\n【2】TA的详细交易分析（全期）")
print("-" * 80)

ta_full = results_by_symbol['TA']['FULL']
if 'trades_df' in ta_full:
    trades = ta_full['trades_df']
    long_trades = trades[trades['direction'] == '多']
    short_trades = trades[trades['direction'] == '空']
    
    print(f"总交易: {len(trades)}笔")
    print(f"  做多: {len(long_trades)}笔, 胜率={long_trades[long_trades['pnl']>0].shape[0]/max(len(long_trades),1)*100:.1f}%, 平均盈亏={long_trades['pnl'].mean():.1f}")
    print(f"  做空: {len(short_trades)}笔, 胜率={short_trades[short_trades['pnl']>0].shape[0]/max(len(short_trades),1)*100:.1f}%, 平均盈亏={short_trades['pnl'].mean():.1f}")
    print(f"\n出场原因分布:")
    for reason, count in ta_full['exit_reasons'].items():
        print(f"  {reason}: {count}")
    
    # 亏损交易分析
    losing = trades[trades['pnl'] <= 0]
    print(f"\n亏损交易分析({len(losing)}笔):")
    print(losing[['entry_date', 'exit_date', 'direction', 'pnl', 'exit_reason', 'hold_days']].to_string())

# ============================================================
# 3. 高回撤品种分析
# ============================================================
print("\n\n【3】高回撤品种分析（回撤>50%）")
print("-" * 80)

for sym in all_symbols:
    full_r = results_by_symbol[sym]['FULL']
    if 'error' not in full_r and full_r.get('max_drawdown_pct', 0) < -50:
        print(f"\n{sym} (回撤={full_r['max_drawdown_pct']:.1f}%, 收益={full_r['total_return_pct']:.1f}%):")
        if 'trades_df' in full_r:
            trades = full_r['trades_df']
            long_t = trades[trades['direction'] == '多']
            short_t = trades[trades['direction'] == '空']
            print(f"  做多: {len(long_t)}笔, 胜率={long_t[long_t['pnl']>0].shape[0]/max(len(long_t),1)*100:.1f}%")
            print(f"  做空: {len(short_t)}笔, 胜率={short_t[short_t['pnl']>0].shape[0]/max(len(short_t),1)*100:.1f}%")
            print(f"  出场原因: {full_r['exit_reasons']}")
            
            # 最大的5笔亏损
            worst = trades.nsmallest(5, 'pnl')
            print(f"  最大5笔亏损:")
            for _, t in worst.iterrows():
                print(f"    {t['entry_date'].date()} {t['direction']} 亏损={t['pnl']:.1f} 原因={t['exit_reason']} 持仓={t['hold_days']}天")

# ============================================================
# 4. SM 样本内外不一致分析
# ============================================================
print("\n\n【4】SM 样本内(+65%) vs 样本外(-64%) 深度分析")
print("-" * 80)

for period_name in ['INSAMPLE', 'OUTSAMPLE']:
    sm_r = results_by_symbol['SM'][period_name]
    if 'error' not in sm_r:
        print(f"\nSM {period_name}:")
        print(f"  收益={sm_r['total_return_pct']:+.1f}%, 交易={sm_r['total_trades']}笔, 胜率={sm_r['win_rate_pct']:.1f}%")
        print(f"  盈亏比={sm_r['profit_factor']:.2f}, 回撤={sm_r['max_drawdown_pct']:.1f}%")
        print(f"  出场原因: {sm_r['exit_reasons']}")
        
        if 'trades_df' in sm_r:
            trades = sm_r['trades_df']
            long_t = trades[trades['direction'] == '多']
            short_t = trades[trades['direction'] == '空']
            print(f"  做多: {len(long_t)}笔, 胜率={long_t[long_t['pnl']>0].shape[0]/max(len(long_t),1)*100:.1f}%")
            print(f"  做空: {len(short_t)}笔, 胜率={short_t[short_t['pnl']>0].shape[0]/max(len(short_t),1)*100:.1f}%")

# ============================================================
# 5. 止损分析 - ATR 1.2x 是否过紧
# ============================================================
print("\n\n【5】止损机制分析")
print("-" * 80)

# 统计所有品种的硬止损比例
print(f"{'品种':4s} | {'总交易':>6s} | {'硬止损':>6s} | {'移动止损':>8s} | {'超时':>6s} | {'ATR止盈':>6s} | {'硬止损占比':>8s}")
print("-" * 80)

for sym in all_symbols:
    full_r = results_by_symbol[sym]['FULL']
    if 'exit_reasons' in full_r:
        exits = full_r['exit_reasons']
        total = sum(exits.values())
        hard_stop = exits.get('硬止损', 0)
        trailing = exits.get('移动止损', 0)
        timeout = sum(v for k, v in exits.items() if '超时' in k)
        take_profit = exits.get('ATR止盈', 0)
        
        print(f"{sym:4s} | {total:>6d} | {hard_stop:>6d} | {trailing:>8d} | {timeout:>6d} | {take_profit:>6d} | {hard_stop/max(total,1)*100:>7.1f}%")

# ============================================================
# 6. TA的价格波动特性
# ============================================================
print("\n\n【6】TA价格波动特性（ATR/价格比率）")
print("-" * 80)

for sym in ['TA', 'SM', 'RB', 'SA', 'EG', 'MA', 'FB']:
    df = strategy.prepare_data(sym, '2020-01-01', '2025-12-31')
    if df is not None and len(df) > 100:
        df_clean = df.dropna(subset=['atr', 'close'])
        if len(df_clean) > 0:
            atr_ratio = (df_clean['atr'] / df_clean['close']).mean() * 100
            daily_range = ((df_clean['high'] - df_clean['low']) / df_clean['close']).mean() * 100
            print(f"{sym}: 日均ATR/价格={atr_ratio:.2f}%, 日均波幅={daily_range:.2f}%, 数据行数={len(df_clean)}")

print("\n\n诊断完成!")
