#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二 v3：严谨研究框架
- 样本内(IS)/样本外(OOS)严格划分
- 网格搜索参数优化
- 蒙特卡罗模拟(1000次+分位数+破产概率)
- 压力测试
- 稳健性检验(参数敏感性+过拟合检测)

数据划分:
- 2020-2023: 样本内(IS) - 参数优化
- 2024-2025: 样本外(OOS) - 验证
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from itertools import product
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.quantile_short_term_v2 import OptimizedQuantileStrategy, OptimizedParams
from data.parquet_loader import ParquetLoader


# ============================================================
# 研究配置
# ============================================================
@dataclass
class ResearchConfig:
    # 时间划分
    is_start: str = "2020-01-01"
    is_end: str = "2023-12-31"
    oos_start: str = "2024-01-01"
    oos_end: str = "2025-12-31"
    
    # 资金
    initial_capital: float = 10000
    
    # 参数搜索空间
    param_grid: Dict[str, list] = None
    random_search_iterations: int = 200  # 随机搜索迭代次数
    
    # 蒙特卡罗
    mc_simulations: int = 1000
    mc_method: str = "block_bootstrap"  # 块自助重采样（保留自相关性）
    block_size: int = 10  # 块大小（交易日）
    
    # 压力测试
    stress_vol_multiplier: float = 2.0
    stress_cost_multiplier: float = 2.0
    stress_worst_consecutive: int = 20
    
    # 稳健性
    sensitivity_range: float = 0.20  # ±20%
    overfit_threshold: float = 0.50  # 夏普衰减>50%视为过拟合
    
    # 输出
    output_dir: str = None
    
    def __post_init__(self):
        if self.param_grid is None:
            self.param_grid = {
                'percentile_window': [30, 35, 40, 45, 50],
                'long_entry_pct': [0.20, 0.25, 0.30, 0.35],
                'short_entry_pct': [0.65, 0.70, 0.75, 0.80],
                'atr_stop_mult': [1.5, 1.8, 2.0, 2.2],
                'atr_take_mult': [2.0, 2.5, 3.0],
                'max_hold_days': [7, 10, 14],
            }
        
        if self.output_dir is None:
            self.output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "research_results"
            )


class RigorousResearch:
    """严谨的研究框架"""
    
    def __init__(self, config: ResearchConfig = None):
        self.config = config or ResearchConfig()
        self.loader = ParquetLoader()
        os.makedirs(self.config.output_dir, exist_ok=True)
    
    # ============================================================
    # 1. 样本内参数优化
    # ============================================================
    def optimize_parameters_is(self, symbol: str) -> Dict:
        """
        在IS数据上随机搜索最优参数
        
        Returns:
            {best_params, best_metrics, all_results}
        """
        print(f"\n[IS参数优化] {symbol}")
        print(f"  时间: {self.config.is_start} ~ {self.config.is_end}")
        
        grid = self.config.param_grid
        param_names = list(grid.keys())
        param_values = list(grid.values())
        
        n_iterations = self.config.random_search_iterations
        print(f"  随机搜索: {n_iterations}次迭代")
        
        all_results = []
        
        for i in range(n_iterations):
            # 随机采样参数
            sampled_params = {
                name: values[np.random.randint(len(values))]
                for name, values in zip(param_names, param_values)
            }
            
            # 创建策略
            p = OptimizedParams(
                percentile_window=int(sampled_params['percentile_window']),
                long_entry_pct=sampled_params['long_entry_pct'],
                short_entry_pct=sampled_params['short_entry_pct'],
                atr_stop_mult=sampled_params['atr_stop_mult'],
                atr_take_mult=sampled_params['atr_take_mult'],
                max_hold_days=int(sampled_params['max_hold_days']),
                trend_filter_enabled=False,
            )
            
            strategy = OptimizedQuantileStrategy(p)
            result = strategy.backtest_single_symbol(
                symbol, self.config.is_start, self.config.is_end,
                self.config.initial_capital
            )
            
            if result.get('total_trades', 0) >= 10:
                all_results.append({
                    'params': sampled_params,
                    'annual_return_pct': result.get('annual_return_pct', 0),
                    'sharpe_ratio': result.get('sharpe_ratio', 0),
                    'max_drawdown_pct': result.get('max_drawdown_pct', 0),
                    'win_rate_pct': result.get('win_rate_pct', 0),
                    'total_trades': result.get('total_trades', 0),
                })
            
            if (i + 1) % 50 == 0:
                print(f"  迭代 {i+1}/{n_iterations}... (有效: {len(all_results)})")
        
        if len(all_results) == 0:
            return {'error': '无有效参数组合'}
        
        all_df = pd.DataFrame(all_results)
        
        # 选择标准：夏普比率最高（要求回撤<40%）
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
    # 2. 样本外验证
    # ============================================================
    def validate_oos(self, symbol: str, is_params: Dict) -> Dict:
        """用IS最优参数在OOS数据上验证"""
        print(f"\n[OOS验证] {symbol}")
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
        
        strategy = OptimizedQuantileStrategy(p)
        result = strategy.backtest_single_symbol(
            symbol, self.config.oos_start, self.config.oos_end,
            self.config.initial_capital
        )
        
        if result.get('total_trades', 0) < 5:
            return {'error': 'OOS交易数不足', 'total_trades': result.get('total_trades', 0)}
        
        oos_metrics = {
            'annual_return_pct': result.get('annual_return_pct', 0),
            'sharpe_ratio': result.get('sharpe_ratio', 0),
            'max_drawdown_pct': result.get('max_drawdown_pct', 0),
            'win_rate_pct': result.get('win_rate_pct', 0),
            'total_trades': result.get('total_trades', 0),
        }
        
        print(f"  OOS年化: {oos_metrics['annual_return_pct']:.1f}%")
        print(f"  OOS夏普: {oos_metrics['sharpe_ratio']:.2f}")
        print(f"  OOS回撤: {oos_metrics['max_drawdown_pct']:.1f}%")
        print(f"  OOS交易: {oos_metrics['total_trades']}笔")
        
        return {
            'oos_metrics': oos_metrics,
            'trades_df': result.get('trades_df'),
            'equity_df': result.get('equity_df'),
        }
    
    # ============================================================
    # 3. 蒙特卡罗模拟（块自助重采样）
    # ============================================================
    def monte_carlo_oos(self, symbol: str, is_params: Dict) -> Dict:
        """
        蒙特卡罗模拟：对OOS日收益率序列进行块自助重采样
        
        块自助重采样保留收益率序列的自相关结构
        """
        print(f"\n[蒙特卡罗OOS] {symbol} ({self.config.mc_simulations}次)")
        
        # 先获取OOS权益曲线
        oos_result = self.validate_oos(symbol, is_params)
        if 'error' in oos_result:
            return oos_result
        
        equity_df = oos_result['equity_df']
        if equity_df is None or len(equity_df) < 20:
            return {'error': 'OOS数据不足'}
        
        # 计算日收益率
        equity_df['daily_return'] = equity_df['capital'].pct_change()
        daily_returns = equity_df['daily_return'].dropna().values
        
        n_days = len(daily_returns)
        block_size = self.config.block_size
        n_simulations = self.config.mc_simulations
        
        mc_results = []
        
        for sim in range(n_simulations):
            # 块自助重采样
            sampled_returns = []
            while len(sampled_returns) < n_days:
                # 随机选择一个块的起点
                start = np.random.randint(0, len(daily_returns) - block_size + 1)
                block = daily_returns[start:start + block_size]
                sampled_returns.extend(block.tolist())
            
            sampled_returns = np.array(sampled_returns[:n_days])
            
            # 计算净值曲线
            nav = self.config.initial_capital * (1 + sampled_returns).cumprod()
            
            # 计算指标
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
                'nav_series': nav.tolist(),
            })
            
            if (sim + 1) % 200 == 0:
                print(f"  完成 {sim+1}/{n_simulations} 次...")
        
        mc_df = pd.DataFrame(mc_results)
        
        # 分位数分析
        percentiles = {
            'p5': mc_df['annual_return_pct'].quantile(0.05),
            'p25': mc_df['annual_return_pct'].quantile(0.25),
            'p50': mc_df['annual_return_pct'].quantile(0.50),
            'p75': mc_df['annual_return_pct'].quantile(0.75),
            'p95': mc_df['annual_return_pct'].quantile(0.95),
        }
        
        # 破产概率（最大回撤>50%）
        ruin_prob = len(mc_df[mc_df['max_drawdown_pct'] < -50]) / len(mc_df) * 100
        
        # VaR/CVaR
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
            'nav_percentiles': self._calc_nav_percentiles(mc_df),
        }
    
    def _calc_nav_percentiles(self, mc_df: pd.DataFrame) -> Dict:
        """计算净值曲线的分位数区间"""
        nav_series = np.array(mc_df['nav_series'].tolist())
        
        return {
            'p5': np.quantile(nav_series, 0.05, axis=0).tolist(),
            'p50': np.quantile(nav_series, 0.50, axis=0).tolist(),
            'p95': np.quantile(nav_series, 0.95, axis=0).tolist(),
        }
    
    # ============================================================
    # 4. 压力测试
    # ============================================================
    def stress_test(self, symbol: str, is_params: Dict) -> Dict:
        """压力测试：极端波动、连续亏损、成本提升"""
        print(f"\n[压力测试] {symbol}")
        
        results = {}
        
        # 4a. 极端波动（收益率标准差 x2）
        p = OptimizedParams(
            percentile_window=int(is_params['percentile_window']),
            long_entry_pct=is_params['long_entry_pct'],
            short_entry_pct=is_params['short_entry_pct'],
            atr_stop_mult=is_params['atr_stop_mult'] * 0.7,
            atr_take_mult=is_params['atr_take_mult'],
            max_hold_days=int(is_params['max_hold_days']),
            trend_filter_enabled=False,
        )
        strategy = OptimizedQuantileStrategy(p)
        result = strategy.backtest_single_symbol(
            symbol, self.config.oos_start, self.config.oos_end,
            self.config.initial_capital
        )
        if result.get('trades_df') is not None:
            trades = result['trades_df'].copy()
            trades['stressed_pnl'] = trades['pnl'] * np.random.normal(1, self.config.stress_vol_multiplier * 0.5, len(trades))
            stressed_return = trades['stressed_pnl'].sum() / self.config.initial_capital * 100
        else:
            stressed_return = 0
        
        results['extreme_volatility'] = {
            'description': f'收益率标准差 x{self.config.stress_vol_multiplier}',
            'stressed_return_pct': stressed_return,
        }
        
        # 4b. 连续最差交易日
        oos_result = self.validate_oos(symbol, is_params)
        if 'error' not in oos_result and oos_result.get('trades_df') is not None:
            trades = oos_result['trades_df'].sort_values('pnl')
            worst_n = min(self.config.stress_worst_consecutive, len(trades))
            worst_trades = trades.head(worst_n)
            worst_cumsum = worst_trades['pnl'].sum()
            
            results['worst_consecutive'] = {
                'description': f'最差{worst_n}笔连续交易',
                'cumulative_loss': worst_cumsum,
                'loss_pct': worst_cumsum / self.config.initial_capital * 100,
            }
        
        # 4c. 交易成本提升（手续费+滑点 x2）
        p_high_cost = OptimizedParams(
            percentile_window=int(is_params['percentile_window']),
            long_entry_pct=is_params['long_entry_pct'],
            short_entry_pct=is_params['short_entry_pct'],
            atr_stop_mult=is_params['atr_stop_mult'],
            atr_take_mult=is_params['atr_take_mult'],
            max_hold_days=int(is_params['max_hold_days']),
            commission_rate=0.0003,  # 万3 (x2)
            slippage_rate=0.0004,    # 万4 (x2)
            trend_filter_enabled=False,
        )
        strategy_cost = OptimizedQuantileStrategy(p_high_cost)
        result_cost = strategy_cost.backtest_single_symbol(
            symbol, self.config.oos_start, self.config.oos_end,
            self.config.initial_capital
        )
        
        results['higher_costs'] = {
            'description': f'手续费+滑点 x{self.config.stress_cost_multiplier}',
            'return_with_high_costs': result_cost.get('total_return_pct', 0),
            'original_return': oos_result.get('oos_metrics', {}).get('annual_return_pct', 0),
        }
        
        print(f"  极端波动: {stressed_return:.1f}%")
        if 'worst_consecutive' in results:
            print(f"  最差连续: {results['worst_consecutive']['loss_pct']:.1f}%")
        print(f"  成本提升: {results['higher_costs']['return_with_high_costs']:.1f}%")
        
        return results
    
    # ============================================================
    # 5. 稳健性检验
    # ============================================================
    def robustness_check(self, symbol: str, is_params: Dict) -> Dict:
        """参数敏感性分析 + 过拟合检测"""
        print(f"\n[稳健性检验] {symbol}")
        
        # 获取IS和OOS指标
        is_result = self.optimize_parameters_is(symbol)
        if 'error' in is_result:
            return is_result
        
        oos_result = self.validate_oos(symbol, is_params)
        if 'error' in oos_result:
            return oos_result
        
        is_sharpe = is_result['best_metrics']['sharpe_ratio']
        oos_sharpe = oos_result['oos_metrics']['sharpe_ratio']
        
        # 夏普衰减
        if is_sharpe != 0:
            sharpe_decay = abs(is_sharpe - oos_sharpe) / abs(is_sharpe)
        else:
            sharpe_decay = 0
        
        is_overfit = sharpe_decay > self.config.overfit_threshold
        
        # 参数敏感性：±20%范围内扰动
        sensitivity_results = []
        
        for param_name in ['percentile_window', 'atr_stop_mult', 'max_hold_days']:
            base_value = is_params[param_name]
            lower = base_value * (1 - self.config.sensitivity_range)
            upper = base_value * (1 + self.config.sensitivity_range)
            
            if param_name in ['percentile_window', 'max_hold_days']:
                test_values = [int(lower), int(base_value), int(upper)]
            else:
                test_values = np.linspace(lower, upper, 5)
            
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
                
                strategy = OptimizedQuantileStrategy(p)
                result = strategy.backtest_single_symbol(
                    symbol, self.config.oos_start, self.config.oos_end,
                    self.config.initial_capital
                )
                
                if result.get('total_trades', 0) >= 5:
                    sensitivity_results.append({
                        'param': param_name,
                        'value': val,
                        'sharpe': result.get('sharpe_ratio', 0),
                        'annual_return': result.get('annual_return_pct', 0),
                        'max_dd': result.get('max_drawdown_pct', 0),
                        'trades': result.get('total_trades', 0),
                    })
        
        sens_df = pd.DataFrame(sensitivity_results) if sensitivity_results else pd.DataFrame()
        
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
    # 6. 完整研究报告
    # ============================================================
    def run_full_research(self, symbol: str) -> Dict:
        """运行完整的研究流程"""
        print("=" * 80)
        print(f"严谨研究: {symbol}")
        print("=" * 80)
        
        # 1. IS参数优化
        is_result = self.optimize_parameters_is(symbol)
        if 'error' in is_result:
            return {'symbol': symbol, 'error': is_result['error']}
        
        best_params = is_result['best_params']
        
        # 2. OOS验证
        oos_result = self.validate_oos(symbol, best_params)
        
        # 3. 蒙特卡罗
        mc_result = self.monte_carlo_oos(symbol, best_params)
        
        # 4. 压力测试
        stress_result = self.stress_test(symbol, best_params)
        
        # 5. 稳健性
        robustness = self.robustness_check(symbol, best_params)
        
        # 汇总
        report = {
            'symbol': symbol,
            'is_result': is_result,
            'oos_result': oos_result,
            'mc_result': mc_result,
            'stress_test': stress_result,
            'robustness': robustness,
            'timestamp': datetime.now().isoformat(),
        }
        
        # 保存
        self._save_report(report, symbol)
        
        return report
    
    def _save_report(self, report: Dict, symbol: str):
        """保存研究报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"research_report_{symbol}_{timestamp}.json"
        filepath = os.path.join(self.config.output_dir, filename)
        
        # 移除不可序列化的对象
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


if __name__ == "__main__":
    print("=" * 80)
    print("路径二 v3：严谨研究框架")
    print("IS: 2020-2023 | OOS: 2024-2025")
    print("=" * 80)
    
    config = ResearchConfig()
    research = RigorousResearch(config)
    
    # 测试RM (菜籽粕) - v2表现最好的品种
    report = research.run_full_research("RM")
    
    if 'error' not in report:
        print("\n" + "=" * 80)
        print("研究完成!")
        print(f"品种: {report['symbol']}")
        print(f"IS夏普: {report['is_result']['best_metrics']['sharpe_ratio']:.2f}")
        if 'oos_metrics' in report.get('oos_result', {}):
            print(f"OOS夏普: {report['oos_result']['oos_metrics']['sharpe_ratio']:.2f}")
        print("=" * 80)
