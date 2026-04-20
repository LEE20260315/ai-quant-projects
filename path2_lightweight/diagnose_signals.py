#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略诊断脚本 - 分析信号生成问题
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from strategies.quantile_short_term_v2 import OptimizedQuantileStrategy, OptimizedParams
from data.parquet_loader import ParquetLoader


def diagnose_signals():
    """诊断信号生成问题"""
    print("=" * 80)
    print("策略诊断 - 信号生成分析")
    print("=" * 80)
    
    # 测试品种
    test_symbols = ['CS', 'MA']
    
    # 策略参数
    params = OptimizedParams(
        percentile_window=30,
        long_entry_pct=0.35,
        short_entry_pct=0.65,
        atr_stop_mult=1.8,
        atr_take_mult=3.0,
        max_hold_days=7,
        trend_filter_enabled=False,  # 暂时关闭趋势过滤
    )
    
    strategy = OptimizedQuantileStrategy(params)
    loader = ParquetLoader()
    
    for symbol in test_symbols:
        print(f"\n【{symbol}】")
        
        # 加载数据
        df = loader.load_symbol(symbol, "2020-01-01", "2025-12-31")
        if df is None:
            print(f"  数据不可用")
            continue
        
        # 计算指标
        df['ema_fast'] = df['close'].ewm(span=params.ema_fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=params.ema_slow, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=params.rsi_period).mean()
        avg_loss = loss.rolling(window=params.rsi_period).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 分位数
        df['pct_rank'] = df['close'].rolling(window=params.percentile_window).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )
        
        # 生成信号
        df['signal_long'] = (
            (df['pct_rank'] < params.long_entry_pct) &
            (df['ema_fast'] > df['ema_slow'])
        )
        
        df['signal_short'] = (
            (df['pct_rank'] > params.short_entry_pct) &
            (df['rsi'] > params.rsi_overbought)
        )
        
        # 统计信号
        long_signals = df['signal_long'].sum()
        short_signals = df['signal_short'].sum()
        
        print(f"  数据行数: {len(df)}")
        print(f"  做多信号: {long_signals}")
        print(f"  做空信号: {short_signals}")
        print(f"  总分位数: {len(df) - params.percentile_window}")
        
        # 查看信号分布
        if long_signals > 0:
            long_pct_ranks = df[df['signal_long']]['pct_rank']
            print(f"  做多信号分位数范围: {long_pct_ranks.min():.3f} ~ {long_pct_ranks.max():.3f}")
            print(f"  做多信号分位数平均: {long_pct_ranks.mean():.3f}")
        
        if short_signals > 0:
            short_pct_ranks = df[df['signal_short']]['pct_rank']
            print(f"  做空信号分位数范围: {short_pct_ranks.min():.3f} ~ {short_pct_ranks.max():.3f}")
            print(f"  做空信号RSI平均: {df[df['signal_short']]['rsi'].mean():.1f}")
        
        # 查看最近的信号
        print("\n  最近10个做多信号:")
        recent_long = df[df['signal_long']].tail(10)
        if len(recent_long) > 0:
            for _, row in recent_long.iterrows():
                print(f"    {row['date'].strftime('%Y-%m-%d')}: 分位数={row['pct_rank']:.3f}, EMA差={(row['ema_fast']-row['ema_slow'])/row['ema_slow']:.3f}")
        else:
            print("    无")
        
        print("\n  最近10个做空信号:")
        recent_short = df[df['signal_short']].tail(10)
        if len(recent_short) > 0:
            for _, row in recent_short.iterrows():
                print(f"    {row['date'].strftime('%Y-%m-%d')}: 分位数={row['pct_rank']:.3f}, RSI={row['rsi']:.1f}")
        else:
            print("    无")
    
    print("\n" + "=" * 80)
    print("诊断完成")
    print("=" * 80)


def test_single_symbol():
    """测试单个品种"""
    print("\n" + "=" * 80)
    print("单品种测试")
    print("=" * 80)
    
    strategy = OptimizedQuantileStrategy(OptimizedParams())
    
    # 测试TA (PTA) - 之前最成功的品种
    result = strategy.backtest_single_symbol(
        symbol="TA",
        start_date="2020-01-01",
        end_date="2025-12-31",
        initial_capital=10000,
    )
    
    if 'error' in result and result.get('total_trades', 0) == 0:
        print("无交易信号")
    elif 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"\n品种: {result['symbol']}")
        print(f"初始资金: {result['initial_capital']:,.0f}元")
        print(f"期末资金: {result['final_capital']:,.0f}元")
        print(f"总收益率: {result['total_return_pct']:.2f}%")
        print(f"交易次数: {result['total_trades']} (多:{result['long_trades']}, 空:{result['short_trades']})")
        print(f"胜率: {result['win_rate_pct']:.1f}%")
        print(f"盈亏比: {result['profit_factor']:.2f}")
        print(f"最大回撤: {result['max_drawdown_pct']:.2f}%")
        print(f"夏普比率: {result['sharpe_ratio']:.2f}")
        print(f"\n出场原因:")
        for reason, count in result['exit_reasons'].items():
            print(f"  {reason}: {count}次")


if __name__ == "__main__":
    diagnose_signals()
    test_single_symbol()
