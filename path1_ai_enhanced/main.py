#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import Path1BacktestEngine


def main():
    print("=" * 60)
    print("路径一：AI增强多策略系统")
    print("4策略并行 + Darwinian权重 + GuardPipeline安全检查")
    print("=" * 60)

    engine = Path1BacktestEngine(initial_capital=10000)
    result = engine.run(
        symbols=['TA', 'RM', 'MA'],
        start_date='2020-01-01',
        end_date='2025-12-31',
    )

    print('\n' + '=' * 60)
    print('路径一 回测结果')
    print('=' * 60)
    if 'error' in result:
        print(f"错误: {result['error']}")
        return

    print(f"初始资金:   {result['initial_capital']:,.0f}元")
    print(f"期末资金:   {result['final_capital']:,.0f}元")
    print(f"总收益率:   {result['total_return_pct']:+.2f}%")
    print(f"年化收益:   {result['annual_return_pct']:+.2f}%")
    print(f"最大回撤:   {result['max_drawdown_pct']:.2f}%")
    print(f"夏普比率:   {result['sharpe_ratio']:.4f}")
    print(f"Calmar比率: {result['calmar_ratio']:.4f}")
    print(f"交易次数:   {result['total_trades']}笔")
    print(f"胜率:       {result['win_rate_pct']:.1f}%")
    print(f"盈亏比:     {result['profit_factor']:.2f}")

    print('\nDarwinian最终权重:')
    for name, w in result.get('final_weights', {}).items():
        print(f"  {name}: {w:.2f}")

    print('\n各策略表现:')
    for name, perf in result.get('strategy_performances', {}).items():
        print(f"  {name}: 盈亏{perf['total_pnl']:+.0f}元 | "
              f"{perf['trades']}笔 | 胜率{perf['win_rate']:.1%} | "
              f"夏普{perf['sharpe']:.2f} | 权重{perf['weight']:.2f}")


if __name__ == '__main__':
    main()
