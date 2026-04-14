#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二 v5：组合严谨研究框架
- 全品种组合（所有1万元可开仓品种）
- 1万元共享账户
- 单品种≤50%仓位，同时持有≤3品种
- IS/OOS严格划分
- 蒙特卡罗1000次
- 压力测试 + 稳健性检验
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from portfolio.portfolio_backtest import PortfolioBacktest, PortfolioConfig, PortfolioPosition
from strategies.quantile_short_term_v2 import OptimizedParams
from data.parquet_loader import ParquetLoader, LOW_MARGIN_SYMBOLS


# ============================================================
# 组合严谨研究配置
# ============================================================
@dataclass
class PortfolioResearchConfig:
    # 时间划分
    is_start: str = "2020-01-01"
    is_end: str = "2023-12-31"
    oos_start: str = "2024-01-01"
    oos_end: str = "2025-12-31"
    
    # 资金
    initial_capital: float = 10000
    
    # 组合限制
    max_positions: int = 3
    max_position_pct: float = 0.50
    max_total_position_pct: float = 0.80  # 总仓位上限80%
    
    # 参数搜索空间
    param_grid: Dict[str, list] = None
    random_search_iterations: int = 100
    
    # 蒙特卡罗
    mc_simulations: int = 1000
    block_size: int = 10
    
    # 压力测试
    stress_vol_multiplier: float = 2.0
    stress_cost_multiplier: float = 2.0
    stress_worst_consecutive: int = 20
    
    # 稳健性
    sensitivity_range: float = 0.20
    overfit_threshold: float = 0.50
    
    # 输出
    output_dir: str = None
    
    def __post_init__(self):
        if self.param_grid is None:
            self.param_grid = {
                'percentile_window': [30, 40, 50],
                'long_entry_pct': [0.25, 0.30, 0.35],
                'short_entry_pct': [0.65, 0.70, 0.75],
                'atr_stop_mult': [1.5, 1.8, 2.0],
                'atr_take_mult': [2.0, 2.5, 3.0],
                'max_hold_days': [7, 10, 14],
            }
        
        if self.output_dir is None:
            self.output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "portfolio_research_results"
            )


class PortfolioRigorousStudy:
    """组合严谨研究框架"""
    
    def __init__(self, config: PortfolioResearchConfig = None):
        self.config = config or PortfolioResearchConfig()
        self.loader = ParquetLoader()
        os.makedirs(self.config.output_dir, exist_ok=True)
    
    def get_eligible_symbols(self) -> List[str]:
        """获取所有1万元可开仓的品种"""
        availability = self.loader.check_data_availability()
        # 需要至少250天数据，且文件存在
        eligible = availability[
            (availability['file_exists'] == True) & 
            (availability['row_count'] >= 250)
        ]
        symbols = eligible['symbol'].tolist()
        print(f"可开仓品种: {len(symbols)}个")
        print(f"品种列表: {', '.join(symbols)}")
        return symbols
    
    # ============================================================
    # 1. IS参数优化（组合模式）
    # ============================================================
    def optimize_parameters_is(self, symbols: List[str]) -> Dict:
        """在IS数据上随机搜索最优参数（组合模式）- 带缓存"""
        cache_key = f"is_cache_{'_'.join(sorted(symbols))}_{self.config.is_start}_{self.config.is_end}_{self.config.random_search_iterations}.json"
        cache_path = os.path.join(self.config.output_dir, cache_key)
        
        if os.path.exists(cache_path):
            print(f"\n[IS组合参数优化] 使用缓存结果: {cache_key}")
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            # 从缓存恢复
            all_results = cached['all_results']
            print(f"  已缓存 {len(all_results)} 次迭代结果")
            # 仍需要跑完剩余迭代
            grid = self.config.param_grid
            param_names = list(grid.keys())
            param_values = list(grid.values())
            n_iterations = self.config.random_search_iterations
            start_i = len(all_results)
            if start_i >= n_iterations:
                print(f"  缓存已完整，跳过IS优化")
            else:
                print(f"  从第 {start_i+1} 次继续...")
        else:
            all_results = []
            print(f"\n[IS组合参数优化]")
            print(f"  品种: {', '.join(symbols)}")
            print(f"  时间: {self.config.is_start} ~ {self.config.is_end}")
            
            grid = self.config.param_grid
            param_names = list(grid.keys())
            param_values = list(grid.values())
            
            n_iterations = self.config.random_search_iterations
            print(f"  随机搜索: {n_iterations}次迭代")
            start_i = 0
        
        for i in range(start_i, n_iterations):
            sampled_params = {
                name: values[np.random.randint(len(values))]
                for name, values in zip(param_names, param_values)
            }
            
            p = OptimizedParams(
                percentile_window=int(sampled_params['percentile_window']),
                long_entry_pct=sampled_params['long_entry_pct'],
                short_entry_pct=sampled_params['short_entry_pct'],
                atr_stop_mult=sampled_params['atr_stop_mult'],
                atr_take_mult=sampled_params['atr_take_mult'],
                max_hold_days=int(sampled_params['max_hold_days']),
                trend_filter_enabled=False,
            )
            
            pf_config = PortfolioConfig(
                initial_capital=self.config.initial_capital,
                max_positions=self.config.max_positions,
                max_position_pct=self.config.max_position_pct,
                max_total_position_pct=self.config.max_total_position_pct,
                start_date=self.config.is_start,
                end_date=self.config.is_end,
            )
            
            portfolio = PortfolioBacktest(pf_config)
            result = portfolio.run(symbols, p)
            
            if result.get('total_trades', 0) >= 20:
                all_results.append({
                    'params': sampled_params,
                    'annual_return_pct': result.get('annual_return_pct', 0),
                    'sharpe_ratio': result.get('sharpe_ratio', 0),
                    'max_drawdown_pct': result.get('max_drawdown_pct', 0),
                    'win_rate_pct': result.get('win_rate_pct', 0),
                    'total_trades': result.get('total_trades', 0),
                })
            
            if (i + 1) % 20 == 0:
                print(f"  迭代 {i+1}/{n_iterations}... (有效: {len(all_results)})")
                # 保存进度缓存
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump({'all_results': all_results}, f, ensure_ascii=False, default=str)
                print(f"  进度已缓存")
        
        if len(all_results) == 0:
            return {'error': '无有效参数组合'}
        
        # 最终保存缓存
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({'all_results': all_results}, f, ensure_ascii=False, default=str)
        
        all_df = pd.DataFrame(all_results)
        valid = all_df[all_df['max_drawdown_pct'].abs() < 40]
        if len(valid) > 0:
            best_idx = valid['sharpe_ratio'].idxmax()
        else:
            best_idx = all_df['sharpe_ratio'].idxmax()
        
        best = all_results[best_idx]
        
        print(f"  有效组合: {len(all_df)} / {n_iterations}")
        print(f"  最优夏普: {best['sharpe_ratio']:.2f}")
        print(f"  最优年化: {best['annual_return_pct']:.1f}%")
        print(f"  最优回撤: {best['max_drawdown_pct']:.1f}%")
        print(f"  最优参数:")
        for k, v in best['params'].items():
            print(f"    {k}: {v}")
        
        return {
            'best_params': best['params'],
            'best_metrics': {
                'annual_return_pct': best['annual_return_pct'],
                'sharpe_ratio': best['sharpe_ratio'],
                'max_drawdown_pct': best['max_drawdown_pct'],
                'win_rate_pct': best['win_rate_pct'],
                'total_trades': best['total_trades'],
            },
            'all_results': all_results,
        }
    
    # ============================================================
    # 2. OOS验证
    # ============================================================
    def validate_oos(self, symbols: List[str], is_params: Dict) -> Dict:
        """用IS最优参数在OOS上验证"""
        print(f"\n[OOS组合验证]")
        print(f"  时间: {self.config.oos_start} ~ {self.config.oos_end}")
        
        p = OptimizedParams(
            percentile_window=int(is_params['percentile_window']),
            long_entry_pct=is_params['long_entry_pct'],
            short_entry_pct=is_params['short_entry_pct'],
            atr_stop_mult=is_params['atr_stop_mult'],
            atr_take_mult=is_params['atr_take_mult'],
            max_hold_days=int(is_params['max_hold_days']),
            trend_filter_enabled=False,
        )
        
        pf_config = PortfolioConfig(
            initial_capital=self.config.initial_capital,
            max_positions=self.config.max_positions,
            max_position_pct=self.config.max_position_pct,
            max_total_position_pct=self.config.max_total_position_pct,
            start_date=self.config.oos_start,
            end_date=self.config.oos_end,
        )
        
        portfolio = PortfolioBacktest(pf_config)
        result = portfolio.run(symbols, p)
        
        if result.get('total_trades', 0) < 10:
            return {'error': 'OOS交易数不足', 'total_trades': result.get('total_trades', 0)}
        
        oos_metrics = {
            'annual_return_pct': result.get('annual_return_pct', 0),
            'sharpe_ratio': result.get('sharpe_ratio', 0),
            'max_drawdown_pct': result.get('max_drawdown_pct', 0),
            'win_rate_pct': result.get('win_rate_pct', 0),
            'total_trades': result.get('total_trades', 0),
            'final_capital': result.get('final_capital', 0),
            'symbol_stats': result.get('symbol_stats', {}),
        }
        
        print(f"  OOS年化: {oos_metrics['annual_return_pct']:.1f}%")
        print(f"  OOS夏普: {oos_metrics['sharpe_ratio']:.2f}")
        print(f"  OOS回撤: {oos_metrics['max_drawdown_pct']:.1f}%")
        print(f"  OOS交易: {oos_metrics['total_trades']}笔")
        print(f"  期末资金: {oos_metrics['final_capital']:,.0f}元")
        
        # 品种分解
        if oos_metrics.get('symbol_stats'):
            print(f"  品种表现:")
            for sym, stats in oos_metrics['symbol_stats'].items():
                print(f"    {sym:4s} | {stats['trades']:3d}笔 | 胜率:{stats['win_rate']:5.1f}% | "
                      f"盈亏:{stats['total_pnl']:+8.0f}元")
        
        return {
            'oos_metrics': oos_metrics,
            'trades_df': result.get('trades_df'),
            'equity_df': result.get('equity_df'),
        }
    
    # ============================================================
    # 3. 蒙特卡罗模拟（组合日收益率块重采样）
    # ============================================================
    def monte_carlo_oos(self, symbols: List[str], is_params: Dict) -> Dict:
        """蒙特卡罗模拟：对OOS组合日收益率块重采样"""
        print(f"\n[蒙特卡罗组合OOS] {self.config.mc_simulations}次")
        
        oos_result = self.validate_oos(symbols, is_params)
        if 'error' in oos_result:
            return oos_result
        
        equity_df = oos_result['equity_df']
        if equity_df is None or len(equity_df) < 20:
            return {'error': 'OOS数据不足'}
        
        equity_df['daily_return'] = equity_df['capital'].pct_change()
        daily_returns = equity_df['daily_return'].dropna().values
        
        n_days = len(daily_returns)
        block_size = self.config.block_size
        n_simulations = self.config.mc_simulations
        
        mc_results = []
        
        for sim in range(n_simulations):
            sampled_returns = []
            while len(sampled_returns) < n_days:
                start = np.random.randint(0, len(daily_returns) - block_size + 1)
                block = daily_returns[start:start + block_size]
                sampled_returns.extend(block.tolist())
            
            sampled_returns = np.array(sampled_returns[:n_days])
            nav = self.config.initial_capital * (1 + sampled_returns).cumprod()
            
            total_return = (nav[-1] / self.config.initial_capital - 1) * 100
            years = n_days / 252
            annual_return = ((nav[-1] / self.config.initial_capital) ** (1 / years) - 1) * 100
            
            peak = np.maximum.accumulate(nav)
            drawdown = (nav - peak) / peak
            max_dd = drawdown.min() * 100
            
            sharpe = (sampled_returns.mean() / sampled_returns.std() * np.sqrt(252)) if sampled_returns.std() > 0 else 0
            
            mc_results.append({
                'simulation': sim,
                'total_return_pct': total_return,
                'annual_return_pct': annual_return,
                'max_drawdown_pct': max_dd,
                'sharpe_ratio': sharpe,
                'final_nav': nav[-1],
            })
            
            if (sim + 1) % 200 == 0:
                print(f"  完成 {sim+1}/{n_simulations} 次...")
        
        mc_df = pd.DataFrame(mc_results)
        
        percentiles = {
            'p5': mc_df['annual_return_pct'].quantile(0.05),
            'p25': mc_df['annual_return_pct'].quantile(0.25),
            'p50': mc_df['annual_return_pct'].quantile(0.50),
            'p75': mc_df['annual_return_pct'].quantile(0.75),
            'p95': mc_df['annual_return_pct'].quantile(0.95),
        }
        
        ruin_prob = len(mc_df[mc_df['max_drawdown_pct'] < -50]) / len(mc_df) * 100
        var_5 = mc_df['annual_return_pct'].quantile(0.05)
        cvar_5 = mc_df[mc_df['annual_return_pct'] <= var_5]['annual_return_pct'].mean()
        
        print(f"\n  蒙特卡罗结果:")
        print(f"    年化收益 P5/P50/P95: {percentiles['p5']:.1f}% / {percentiles['p50']:.1f}% / {percentiles['p95']:.1f}%")
        print(f"    破产概率: {ruin_prob:.1f}%")
        print(f"    VaR(5%): {var_5:.1f}%")
        print(f"    CVaR(5%): {cvar_5:.1f}%")
        
        return {
            'mc_results': mc_df,
            'percentiles': percentiles,
            'ruin_probability': ruin_prob,
            'var_5': var_5,
            'cvar_5': cvar_5,
        }
    
    # ============================================================
    # 4. 压力测试
    # ============================================================
    def stress_test(self, symbols: List[str], is_params: Dict, oos_result: Dict = None) -> Dict:
        """压力测试"""
        print(f"\n[压力测试]")
        results = {}
        
        # 4a. 交易成本提升
        p_high_cost = OptimizedParams(
            percentile_window=int(is_params['percentile_window']),
            long_entry_pct=is_params['long_entry_pct'],
            short_entry_pct=is_params['short_entry_pct'],
            atr_stop_mult=is_params['atr_stop_mult'],
            atr_take_mult=is_params['atr_take_mult'],
            max_hold_days=int(is_params['max_hold_days']),
            commission_rate=0.0003,
            slippage_rate=0.0004,
            trend_filter_enabled=False,
        )
        
        pf_config = PortfolioConfig(
            initial_capital=self.config.initial_capital,
            max_positions=self.config.max_positions,
            max_position_pct=self.config.max_position_pct,
            start_date=self.config.oos_start,
            end_date=self.config.oos_end,
            commission_rate=0.0003,
            slippage_rate=0.0004,
        )
        
        portfolio = PortfolioBacktest(pf_config)
        result_cost = portfolio.run(symbols, p_high_cost)
        
        oos_annual = oos_result.get('oos_metrics', {}).get('annual_return_pct', 0) if oos_result and 'error' not in oos_result else 0
        
        results['higher_costs'] = {
            'description': f'手续费+滑点 x{self.config.stress_cost_multiplier}',
            'return_with_high_costs': result_cost.get('total_return_pct', 0),
            'original_return': oos_annual,
        }
        
        # 4b. 最差连续亏损
        if oos_result and 'error' not in oos_result and oos_result.get('trades_df') is not None:
            trades = oos_result['trades_df'].sort_values('pnl')
            worst_n = min(self.config.stress_worst_consecutive, len(trades))
            worst_trades = trades.head(worst_n)
            worst_cumsum = worst_trades['pnl'].sum()
            
            results['worst_consecutive'] = {
                'description': f'最差{worst_n}笔连续交易',
                'cumulative_loss': worst_cumsum,
                'loss_pct': worst_cumsum / self.config.initial_capital * 100,
            }
        
        print(f"  成本提升: {results['higher_costs']['return_with_high_costs']:.1f}%")
        if 'worst_consecutive' in results:
            print(f"  最差连续: {results['worst_consecutive']['loss_pct']:.1f}%")
        
        return results
    
    # ============================================================
    # 5. 稳健性检验
    # ============================================================
    def robustness_check(self, symbols: List[str], is_params: Dict, is_sharpe: float, oos_sharpe: float) -> Dict:
        """参数敏感性 + 过拟合检测"""
        print(f"\n[稳健性检验]")
        
        if is_sharpe != 0:
            sharpe_decay = abs(is_sharpe - oos_sharpe) / abs(is_sharpe)
        else:
            sharpe_decay = 0
        
        is_overfit = sharpe_decay > self.config.overfit_threshold
        
        # 参数敏感性：±20%
        sensitivity_results = []
        
        for param_name in ['percentile_window', 'atr_stop_mult', 'max_hold_days']:
            base_value = is_params[param_name]
            lower = base_value * (1 - self.config.sensitivity_range)
            upper = base_value * (1 + self.config.sensitivity_range)
            
            if param_name in ['percentile_window', 'max_hold_days']:
                test_values = [int(max(1, lower)), int(base_value), int(min(100, upper))]
            else:
                test_values = np.round(np.linspace(lower, upper, 5), 2)
            
            for val in test_values:
                test_params = is_params.copy()
                test_params[param_name] = val
                
                p = OptimizedParams(
                    percentile_window=int(test_params['percentile_window']),
                    long_entry_pct=test_params['long_entry_pct'],
                    short_entry_pct=test_params['short_entry_pct'],
                    atr_stop_mult=test_params['atr_stop_mult'],
                    atr_take_mult=test_params['atr_take_mult'],
                    max_hold_days=int(test_params['max_hold_days']),
                    trend_filter_enabled=False,
                )
                
                pf_config = PortfolioConfig(
                    initial_capital=self.config.initial_capital,
                    max_positions=self.config.max_positions,
                    max_position_pct=self.config.max_position_pct,
                    start_date=self.config.oos_start,
                    end_date=self.config.oos_end,
                )
                
                portfolio = PortfolioBacktest(pf_config)
                result = portfolio.run(symbols, p)
                
                if result.get('total_trades', 0) >= 10:
                    sensitivity_results.append({
                        'param': param_name,
                        'value': val,
                        'sharpe': result.get('sharpe_ratio', 0),
                        'annual_return': result.get('annual_return_pct', 0),
                        'max_dd': result.get('max_drawdown_pct', 0),
                        'trades': result.get('total_trades', 0),
                    })
        
        print(f"  IS夏普: {is_sharpe:.2f}")
        print(f"  OOS夏普: {oos_sharpe:.2f}")
        print(f"  夏普衰减: {sharpe_decay:.1%}")
        print(f"  过拟合: {'是 ⚠️' if is_overfit else '否 ✅'}")
        
        return {
            'is_sharpe': is_sharpe,
            'oos_sharpe': oos_sharpe,
            'sharpe_decay': sharpe_decay,
            'is_overfit': is_overfit,
            'sensitivity_results': sensitivity_results,
        }
    
    # ============================================================
    # 6. 完整运行
    # ============================================================
    def run_full_study(self, symbols: List[str]) -> Dict:
        """运行完整组合严谨研究"""
        print("=" * 80)
        print(f"组合严谨研究: {len(symbols)}个品种")
        print("=" * 80)
        
        # 1. IS参数优化
        is_result = self.optimize_parameters_is(symbols)
        if 'error' in is_result:
            return {'error': is_result['error']}
        
        best_params = is_result['best_params']
        
        # 2. OOS验证
        oos_result = self.validate_oos(symbols, best_params)
        
        # 3. 蒙特卡罗
        mc_result = self.monte_carlo_oos(symbols, best_params)
        
        # 4. 压力测试
        stress_result = self.stress_test(symbols, best_params, oos_result)
        
        # 5. 稳健性
        is_sharpe = is_result['best_metrics']['sharpe_ratio']
        oos_sharpe = oos_result.get('oos_metrics', {}).get('sharpe_ratio', 0) if 'error' not in oos_result else 0
        robustness = self.robustness_check(symbols, best_params, is_sharpe, oos_sharpe)
        
        # 汇总
        report = {
            'symbols': symbols,
            'is_result': is_result,
            'oos_result': oos_result,
            'mc_result': mc_result,
            'stress_test': stress_result,
            'robustness': robustness,
            'timestamp': datetime.now().isoformat(),
        }
        
        self._save_report(report)
        
        return report
    
    def _save_report(self, report: Dict):
        """保存报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"portfolio_research_report_{timestamp}.json"
        filepath = os.path.join(self.config.output_dir, filename)
        
        clean_report = {}
        for k, v in report.items():
            if isinstance(v, pd.DataFrame):
                clean_report[k] = v.to_dict()
            elif isinstance(v, dict):
                clean_report[k] = {k2: (v2.to_dict() if isinstance(v2, pd.DataFrame) else v2)
                                   for k2, v2 in v.items()}
            else:
                clean_report[k] = v
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(clean_report, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"\n报告已保存: {filepath}")


# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("路径二 v5：组合严谨研究 - MA+TA+RB+M 四品种对比")
    print("1万元共享 | 总仓位≤80% | 单品种≤50%")
    print("=" * 80)
    
    config = PortfolioResearchConfig(
        random_search_iterations=50,
        mc_simulations=500,
    )
    study = PortfolioRigorousStudy(config)
    
    symbols = ['MA', 'RM', 'TA', 'M']
    print(f"\n测试品种: {', '.join(symbols)}")
    
    # ========== 第1轮：原时间划分 IS:2020-2023, OOS:2024-2025 ==========
    print(f"\n{'='*60}")
    print(f"第1轮：IS 2020-2023 | OOS 2024-2025")
    print(f"{'='*60}")
    
    report1 = study.run_full_study(symbols)
    
    if 'error' not in report1:
        print(f"\n第1轮完成!")
        is_m1 = report1['is_result']['best_metrics']
        oos_m1 = report1['oos_result'].get('oos_metrics', {})
        mc1 = report1['mc_result']
        robust1 = report1['robustness']
        print(f"IS:  年化{is_m1['annual_return_pct']:.1f}% | 夏普{is_m1['sharpe_ratio']:.2f} | 回撤{is_m1['max_drawdown_pct']:.1f}%")
        if oos_m1:
            print(f"OOS: 年化{oos_m1['annual_return_pct']:.1f}% | 夏普{oos_m1['sharpe_ratio']:.2f} | 回撤{oos_m1['max_drawdown_pct']:.1f}%")
            print(f"OOS期末资金: {oos_m1.get('final_capital', 0):,.0f}元")
            if oos_m1.get('symbol_stats'):
                for sym, stats in oos_m1['symbol_stats'].items():
                    print(f"  {sym:4s} | {stats['trades']:3d}笔 | 胜率:{stats['win_rate']:5.1f}% | 盈亏:{stats['total_pnl']:+8.0f}元")
        print(f"MC_P50: {mc1.get('percentiles', {}).get('p50', 0):.1f}% | MC_P5: {mc1.get('percentiles', {}).get('p5', 0):.1f}%")
        print(f"破产率: {mc1.get('ruin_probability', 0):.1f}%")
        print(f"夏普衰减: {robust1.get('sharpe_decay', 0):.1%} | 过拟合: {'是 ⚠️' if robust1.get('is_overfit') else '否 ✅'}")
    
    # ========== 第2轮：换时间划分 IS:2018-2022, OOS:2023 ==========
    print(f"\n{'='*60}")
    print(f"第2轮：IS 2018-2022 | OOS 2023")
    print(f"{'='*60}")
    
    study2_config = PortfolioResearchConfig(
        is_start="2018-01-01",
        is_end="2022-12-31",
        oos_start="2023-01-01",
        oos_end="2023-12-31",
        random_search_iterations=50,
        mc_simulations=500,
    )
    study2 = PortfolioRigorousStudy(study2_config)
    
    report2 = study2.run_full_study(symbols)
    
    if 'error' not in report2:
        print(f"\n第2轮完成!")
        is_m2 = report2['is_result']['best_metrics']
        oos_m2 = report2['oos_result'].get('oos_metrics', {})
        mc2 = report2['mc_result']
        robust2 = report2['robustness']
        print(f"IS:  年化{is_m2['annual_return_pct']:.1f}% | 夏普{is_m2['sharpe_ratio']:.2f} | 回撤{is_m2['max_drawdown_pct']:.1f}%")
        if oos_m2:
            print(f"OOS: 年化{oos_m2['annual_return_pct']:.1f}% | 夏普{oos_m2['sharpe_ratio']:.2f} | 回撤{oos_m2['max_drawdown_pct']:.1f}%")
            print(f"OOS期末资金: {oos_m2.get('final_capital', 0):,.0f}元")
            if oos_m2.get('symbol_stats'):
                for sym, stats in oos_m2['symbol_stats'].items():
                    print(f"  {sym:4s} | {stats['trades']:3d}笔 | 胜率:{stats['win_rate']:5.1f}% | 盈亏:{stats['total_pnl']:+8.0f}元")
        print(f"MC_P50: {mc2.get('percentiles', {}).get('p50', 0):.1f}% | MC_P5: {mc2.get('percentiles', {}).get('p5', 0):.1f}%")
        print(f"破产率: {mc2.get('ruin_probability', 0):.1f}%")
        print(f"夏普衰减: {robust2.get('sharpe_decay', 0):.1%} | 过拟合: {'是 ⚠️' if robust2.get('is_overfit') else '否 ✅'}")
    
    # ========== 汇总对比 ==========
    print(f"\n{'='*80}")
    print(f"两轮对比汇总")
    print(f"{'='*80}")
    print(f"{'指标':15s} | {'第1轮(20-23/24-25)':>20s} | {'第2轮(18-22/23)':>20s}")
    print(f"{'-'*80}")
    if 'error' not in report1 and 'error' not in report2:
        print(f"{'IS年化':15s} | {is_m1['annual_return_pct']:>19.1f}% | {is_m2['annual_return_pct']:>19.1f}%")
        print(f"{'IS夏普':15s} | {is_m1['sharpe_ratio']:>20.2f} | {is_m2['sharpe_ratio']:>20.2f}")
        print(f"{'IS回撤':15s} | {is_m1['max_drawdown_pct']:>18.1f}% | {is_m2['max_drawdown_pct']:>18.1f}%")
        print(f"{'OOS年化':15s} | {oos_m1['annual_return_pct']:>19.1f}% | {oos_m2['annual_return_pct']:>19.1f}%")
        print(f"{'OOS夏普':15s} | {oos_m1['sharpe_ratio']:>20.2f} | {oos_m2['sharpe_ratio']:>20.2f}")
        print(f"{'OOS回撤':15s} | {oos_m1['max_drawdown_pct']:>18.1f}% | {oos_m2['max_drawdown_pct']:>18.1f}%")
        print(f"{'MC_P50':15s} | {mc1['percentiles']['p50']:>18.1f}% | {mc2['percentiles']['p50']:>18.1f}%")
        print(f"{'MC破产率':15s} | {mc1['ruin_probability']:>19.1f}% | {mc2['ruin_probability']:>19.1f}%")
        print(f"{'夏普衰减':15s} | {robust1['sharpe_decay']:>18.1%} | {robust2['sharpe_decay']:>18.1%}")
        overfit1 = '是 ⚠️' if robust1.get('is_overfit') else '否 ✅'
        overfit2 = '是 ⚠️' if robust2.get('is_overfit') else '否 ✅'
        print(f"{'过拟合':15s} | {overfit1:>20s} | {overfit2:>20s}")
        print(f"{'='*80}")
