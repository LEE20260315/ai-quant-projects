#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.quantile_short_term_v2 import OptimizedParams
from portfolio.portfolio_backtest import PortfolioConfig
from fusion.fusion_backtest import FusionBacktestEngine
from monte_carlo_analysis import MonteCarloAnalyzer
from stress_test_enhanced import EnhancedStressTester

SYMBOLS = ['TA', 'RM', 'MA']

PARAM_GRID = {
    'percentile_window': [30, 40, 50],
    'long_entry_pct': [0.20, 0.25, 0.30],
    'short_entry_pct': [0.70, 0.75, 0.80],
    'atr_stop_mult': [1.2, 1.5, 1.8],
    'atr_take_mult': [1.5, 2.0, 2.5],
    'max_hold_days': [5, 7, 10],
}

WF_FOLDS = [
    ('2020-01-01', '2022-12-31', '2023-01-01', '2023-12-31'),
    ('2020-01-01', '2023-12-31', '2024-01-01', '2024-06-30'),
    ('2021-01-01', '2023-12-31', '2024-01-01', '2024-06-30'),
    ('2021-01-01', '2024-06-30', '2024-07-01', '2025-06-30'),
    ('2022-01-01', '2024-12-31', '2025-01-01', '2025-12-31'),
]

DEFAULT_PARAMS = OptimizedParams(
    percentile_window=40, long_entry_pct=0.25, short_entry_pct=0.75,
    atr_stop_mult=1.5, atr_take_mult=2.0, max_hold_days=7,
    trend_filter_enabled=True,
)


def _grid_search_is(is_start, is_end, max_combos=30):
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    all_combos = list(product(*values))
    np.random.seed(42)
    if len(all_combos) > max_combos:
        indices = np.random.choice(len(all_combos), max_combos, replace=False)
        sampled = [all_combos[i] for i in indices]
    else:
        sampled = all_combos

    best_sharpe = -999
    best_params = DEFAULT_PARAMS

    config = PortfolioConfig(
        start_date=is_start, end_date=is_end,
        dynamic_position_enabled=True,
        volatility_target_enabled=True,
        symbol_rotation_enabled=True,
    )

    for combo in sampled:
        params = OptimizedParams(
            percentile_window=combo[0],
            long_entry_pct=combo[1],
            short_entry_pct=combo[2],
            atr_stop_mult=combo[3],
            atr_take_mult=combo[4],
            max_hold_days=combo[5],
            trend_filter_enabled=True,
        )
        try:
            engine = FusionBacktestEngine(config=config, fusion_enabled=False)
            result = engine.run(SYMBOLS, params, is_start, is_end)
            sharpe = result.get('sharpe_ratio', -999)
            trades = result.get('total_trades', 0)
            if trades >= 5 and sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params
        except Exception:
            continue

    return best_params, best_sharpe


def run_full_period_backtest():
    print('=' * 60)
    print('全周期回测 (2020-2025)')
    print('=' * 60)

    config = PortfolioConfig(
        start_date='2020-01-01', end_date='2025-12-31',
        dynamic_position_enabled=True,
        volatility_target_enabled=True,
        symbol_rotation_enabled=True,
    )

    baseline_engine = FusionBacktestEngine(config=config, fusion_enabled=False)
    baseline = baseline_engine.run(SYMBOLS, DEFAULT_PARAMS, '2020-01-01', '2025-12-31')

    fusion_engine = FusionBacktestEngine(config=config, fusion_enabled=True)
    fused = fusion_engine.run(SYMBOLS, DEFAULT_PARAMS, '2020-01-01', '2025-12-31')

    print(f'\n  基线: 收益={baseline.get("total_return_pct", 0):+.1f}%, '
          f'夏普={baseline.get("sharpe_ratio", 0):.2f}, '
          f'回撤={baseline.get("max_drawdown_pct", 0):.1f}%')
    print(f'  融合: 收益={fused.get("total_return_pct", 0):+.1f}%, '
          f'夏普={fused.get("sharpe_ratio", 0):.2f}, '
          f'回撤={fused.get("max_drawdown_pct", 0):.1f}%')

    return baseline, fused


def walk_forward_validation():
    print('\n' + '=' * 60)
    print('Walk-Forward 验证 (5折, IS期参数优化)')
    print('=' * 60)

    results = []
    for i, (is_start, is_end, oos_start, oos_end) in enumerate(WF_FOLDS):
        print(f'\n--- Fold {i+1}/5: IS={is_start}~{is_end}, OOS={oos_start}~{oos_end} ---')

        print(f'  IS期参数搜索...')
        is_best_params, is_best_sharpe = _grid_search_is(is_start, is_end)
        print(f'  IS最优: pct_win={is_best_params.percentile_window}, '
              f'long_pct={is_best_params.long_entry_pct}, '
              f'short_pct={is_best_params.short_entry_pct}, '
              f'sl={is_best_params.atr_stop_mult}, tp={is_best_params.atr_take_mult}, '
              f'hold={is_best_params.max_hold_days}, IS夏普={is_best_sharpe:.2f}')

        config = PortfolioConfig(start_date=oos_start, end_date=oos_end,
                                dynamic_position_enabled=True,
                                volatility_target_enabled=True,
                                symbol_rotation_enabled=True)

        baseline_engine = FusionBacktestEngine(config=config, fusion_enabled=False)
        baseline = baseline_engine.run(SYMBOLS, is_best_params, oos_start, oos_end)

        fusion_engine = FusionBacktestEngine(config=config, fusion_enabled=True)
        fused = fusion_engine.run(SYMBOLS, is_best_params, oos_start, oos_end)

        b_sharpe = baseline.get('sharpe_ratio', 0)
        f_sharpe = fused.get('sharpe_ratio', 0)
        b_ret = baseline.get('total_return_pct', 0)
        f_ret = fused.get('total_return_pct', 0)
        b_dd = baseline.get('max_drawdown_pct', 0)
        f_dd = fused.get('max_drawdown_pct', 0)

        print(f'  OOS基线: 收益={b_ret:+.1f}%, 夏普={b_sharpe:.2f}, 回撤={b_dd:.1f}%')
        print(f'  OOS融合: 收益={f_ret:+.1f}%, 夏普={f_sharpe:.2f}, 回撤={f_dd:.1f}%')
        print(f'  改善: 收益={f_ret-b_ret:+.1f}%, 夏普={f_sharpe-b_sharpe:+.2f}')

        results.append({
            'fold': i+1, 'oos_period': f'{oos_start}~{oos_end}',
            'is_best_sharpe': round(is_best_sharpe, 4),
            'is_best_params': {
                'percentile_window': is_best_params.percentile_window,
                'long_entry_pct': is_best_params.long_entry_pct,
                'short_entry_pct': is_best_params.short_entry_pct,
                'atr_stop_mult': is_best_params.atr_stop_mult,
                'atr_take_mult': is_best_params.atr_take_mult,
                'max_hold_days': is_best_params.max_hold_days,
            },
            'baseline_sharpe': b_sharpe, 'fused_sharpe': f_sharpe,
            'baseline_return': b_ret, 'fused_return': f_ret,
            'baseline_dd': b_dd, 'fused_dd': f_dd,
            'sharpe_improvement': round(f_sharpe - b_sharpe, 4),
            'return_improvement': round(f_ret - b_ret, 2),
        })

    avg_b_sharpe = np.mean([r['baseline_sharpe'] for r in results])
    avg_f_sharpe = np.mean([r['fused_sharpe'] for r in results])
    avg_b_ret = np.mean([r['baseline_return'] for r in results])
    avg_f_ret = np.mean([r['fused_return'] for r in results])
    wins = sum(1 for r in results if r['sharpe_improvement'] > 0)

    print(f'\n--- Walk-Forward 汇总 ---')
    print(f'  OOS平均夏普: 基线={avg_b_sharpe:.2f}, 融合={avg_f_sharpe:.2f}, 改善={avg_f_sharpe-avg_b_sharpe:+.2f}')
    print(f'  OOS平均收益: 基线={avg_b_ret:.1f}%, 融合={avg_f_ret:.1f}%, 改善={avg_f_ret-avg_b_ret:+.1f}%')
    print(f'  融合胜率: {wins}/{len(results)} 折 ({wins/len(results)*100:.0f}%)')

    return results


def monte_carlo_from_trades(trades_list, label=''):
    print(f'\n{"=" * 60}')
    print(f'蒙特卡罗分析 - {label} (5000次, 块自助重采样)')
    print('=' * 60)

    analyzer = MonteCarloAnalyzer(initial_capital=10000, num_simulations=5000, block_size=10)
    trades = analyzer.load_trades_from_list(trades_list)
    if not trades:
        print('无交易数据')
        return None

    stats, results = analyzer.run_analysis(trades, target_trades=100, bankruptcy_threshold=0.5)
    print(f'  破产概率(>50%回撤): {results["bankruptcy_prob"]:.1%}')
    print(f'  盈利概率: {results["profit_prob"]:.1%}')
    print(f'  平均最终资金: {results["avg_final_capital"]:.0f}元')
    print(f'  95%分位最大回撤: {results["p95_max_drawdown"]:.1%}')

    return {'stats': stats, 'results': results}


def stress_test_from_trades(trades_list, label=''):
    print(f'\n{"=" * 60}')
    print(f'增强压力测试 - {label} (6场景)')
    print('=' * 60)

    tester = EnhancedStressTester(initial_capital=10000)
    trades = tester.load_trades_from_list(trades_list)
    if not trades:
        print('无交易数据')
        return None

    pnl_list = [t['pnl'] for t in trades]
    scenarios = [
        ('黑天鹅(30%暴跌)', tester.scenario_black_swan(pnl_list, 0.30)),
        ('黑天鹅(50%暴跌)', tester.scenario_black_swan(pnl_list, 0.50)),
        ('闪崩(15%跌+10%涨)', tester.scenario_flash_crash(pnl_list)),
        ('连续亏损(5笔额外5%)', tester.scenario_losing_streak(pnl_list)),
        ('波动率收缩(收益减半)', tester.scenario_volatility_squeeze(pnl_list)),
        ('追加保证金(50%回撤强平)', tester.scenario_margin_call(pnl_list)),
    ]

    results = {}
    all_survive = True
    for name, (final_cap, max_dd) in scenarios:
        status = 'SURVIVE' if final_cap > 3000 else 'DANGER'
        if status == 'DANGER':
            all_survive = False
        results[name] = {'final_capital': round(final_cap, 2), 'max_dd': round(max_dd * 100, 2), 'status': status}
        print(f'  {name}: 资金={final_cap:,.0f}元, 回撤={max_dd:.1%}, [{status}]')

    print(f'\n  压力测试结果: {"全部通过" if all_survive else "存在风险"}')
    return results


def run_full_validation():
    baseline_full, fused_full = run_full_period_backtest()

    mc_baseline = monte_carlo_from_trades(baseline_full.get('trades', []), '基线(Path2)')
    mc_fused = monte_carlo_from_trades(fused_full.get('trades', []), '融合(Path2+Path1)')

    stress_baseline = stress_test_from_trades(baseline_full.get('trades', []), '基线(Path2)')
    stress_fused = stress_test_from_trades(fused_full.get('trades', []), '融合(Path2+Path1)')

    wf_results = walk_forward_validation()

    full_sharpe = fused_full.get('sharpe_ratio', 0)
    full_dd = fused_full.get('max_drawdown_pct', 0)
    avg_wf_sharpe = np.mean([r['fused_sharpe'] for r in wf_results])

    report = {
        'timestamp': datetime.now().isoformat(),
        'full_period': {
            'baseline': {k: v for k, v in baseline_full.items() if k != 'trades'},
            'fused': {k: v for k, v in fused_full.items() if k != 'trades'},
        },
        'walk_forward': wf_results,
        'walk_forward_summary': {
            'avg_oos_sharpe_baseline': round(np.mean([r['baseline_sharpe'] for r in wf_results]), 4),
            'avg_oos_sharpe_fused': round(np.mean([r['fused_sharpe'] for r in wf_results]), 4),
            'fusion_win_rate': f'{sum(1 for r in wf_results if r["sharpe_improvement"] > 0)}/{len(wf_results)}',
        },
        'monte_carlo': {
            'baseline': mc_baseline,
            'fused': mc_fused,
        },
        'stress_test': {
            'baseline': stress_baseline,
            'fused': stress_fused,
        },
        'one_vote_veto': {
            'full_sharpe_gt_074': full_sharpe > 0.74,
            'full_max_dd_lt_30': full_dd < 30,
            'mc_bankruptcy_lt_15': mc_fused['results']['bankruptcy_prob'] < 0.15 if mc_fused else False,
            'wf_oos_sharpe_gt_05': avg_wf_sharpe > 0.5,
            'stress_all_survive': all(v['status'] == 'SURVIVE' for v in stress_fused.values()) if stress_fused else False,
        },
    }

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(base_dir, 'results'), exist_ok=True)
    with open(os.path.join(base_dir, 'results', 'fusion_validation_report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print('\n' + '=' * 60)
    print('一票否决检查')
    print('=' * 60)
    veto = report['one_vote_veto']
    checks = [
        ('全周期夏普>0.74', veto['full_sharpe_gt_074'], f'夏普={full_sharpe:.2f}'),
        ('全周期最大回撤<30%', veto['full_max_dd_lt_30'], f'回撤={full_dd:.1f}%'),
        ('MC破产概率<15%', veto['mc_bankruptcy_lt_15'],
         f'破产概率={mc_fused["results"]["bankruptcy_prob"]:.1%}' if mc_fused else '无数据'),
        ('WF OOS平均夏普>0.5', veto['wf_oos_sharpe_gt_05'], f'夏普={avg_wf_sharpe:.2f}'),
        ('压力测试全部通过', veto['stress_all_survive'], ''),
    ]
    for name, passed, detail in checks:
        status = 'PASS' if passed else 'FAIL'
        print(f'  {name}: {status} ({detail})')

    if mc_baseline and mc_fused:
        b_bankrupt = mc_baseline['results']['bankruptcy_prob']
        f_bankrupt = mc_fused['results']['bankruptcy_prob']
        print(f'\n  基线MC破产概率: {b_bankrupt:.1%} | 融合MC破产概率: {f_bankrupt:.1%} | 差异: {f_bankrupt-b_bankrupt:+.1%}')

    all_pass = all(veto.values())
    print(f'\n  最终结论: {"融合方案通过验证" if all_pass else "融合方案未通过验证，回退纯路径2"}')

    return report


if __name__ == '__main__':
    run_full_validation()
