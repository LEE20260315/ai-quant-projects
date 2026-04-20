#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime
from itertools import product
from strategies.quantile_short_term_v2 import OptimizedParams
from portfolio_backtest import PortfolioBacktest, PortfolioConfig


def optimize_parameters():
    print("=" * 60)
    print("参数调优 - TA+RM+MA 三品种组合")
    print("=" * 60)

    test_symbols = ['TA', 'RM', 'MA']

    param_grid = {
        'atr_stop_mult': [1.5, 2.0, 2.5],
        'atr_take_mult': [2.0, 2.5, 3.0, 3.5],
        'max_hold_days': [7, 10, 14],
        'long_entry_pct': [0.25, 0.30],
        'short_entry_pct': [0.70, 0.75],
    }

    results = []
    param_combos = list(product(
        param_grid['atr_stop_mult'],
        param_grid['atr_take_mult'],
        param_grid['max_hold_days'],
        param_grid['long_entry_pct'],
        param_grid['short_entry_pct'],
    ))

    total = len(param_combos)
    print(f"总参数组合: {total}")

    for i, combo in enumerate(param_combos):
        atr_stop, atr_take, hold_days, long_pct, short_pct = combo

        if atr_take <= atr_stop:
            continue

        params = OptimizedParams(
            percentile_window=40,
            long_entry_pct=long_pct,
            short_entry_pct=short_pct,
            atr_stop_mult=atr_stop,
            atr_take_mult=atr_take,
            max_hold_days=hold_days,
            trend_filter_enabled=True,
        )

        config = PortfolioConfig(
            start_date="2020-01-01",
            end_date="2025-12-31",
            dynamic_position_enabled=True,
            volatility_target_enabled=True,
            symbol_rotation_enabled=True,
        )

        portfolio = PortfolioBacktest(config)
        result = portfolio.run(test_symbols, params)

        if 'error' in result:
            continue

        row = {
            'atr_stop': atr_stop,
            'atr_take': atr_take,
            'hold_days': hold_days,
            'long_pct': long_pct,
            'short_pct': short_pct,
            'return_pct': result['total_return_pct'],
            'annual_pct': result['annual_return_pct'],
            'win_rate': result['win_rate_pct'],
            'profit_factor': result['profit_factor'],
            'max_dd': result['max_drawdown_pct'],
            'sharpe': result['sharpe_ratio'],
            'calmar': result['calmar_ratio'],
            'trades': result['total_trades'],
        }
        results.append(row)

        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{total}")

    if not results:
        print("无有效结果")
        return

    df = pd.DataFrame(results)
    df['score'] = df['sharpe'] * 0.4 + df['calmar'] * 0.3 + (1 + df['return_pct'] / 100) * 0.3
    df = df.sort_values('score', ascending=False)

    print("\n" + "=" * 60)
    print("TOP 10 参数组合")
    print("=" * 60)
    for i, row in df.head(10).iterrows():
        print(f"  收益:{row['return_pct']:+.1f}% | 夏普:{row['sharpe']:.2f} | "
              f"回撤:{row['max_dd']:.1f}% | 胜率:{row['win_rate']:.0f}% | "
              f"ATR:{row['atr_stop']}/{row['atr_take']} | 持仓:{row['hold_days']}天 | "
              f"阈值:{row['long_pct']}/{row['short_pct']}")

    best = df.iloc[0]
    print(f"\n最佳参数:")
    print(f"  ATR止损/止盈: {best['atr_stop']}/{best['atr_take']}")
    print(f"  持仓天数: {best['hold_days']}")
    print(f"  多空阈值: {best['long_pct']}/{best['short_pct']}")
    print(f"  预期收益: {best['return_pct']:+.1f}%")
    print(f"  预期夏普: {best['sharpe']:.2f}")
    print(f"  预期回撤: {best['max_dd']:.1f}%")

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = f"results/param_opt_{ts}.csv"
    os.makedirs('results', exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    optimize_parameters()
