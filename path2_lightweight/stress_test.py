import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import json
from datetime import datetime, timedelta

class StressTester:
    def __init__(self, initial_capital=10000):
        self.initial_capital = initial_capital
        
    def create_stress_scenario(self, scenario_type, length=30):
        """创建不同的压力测试场景"""
        scenarios = {
            'continuous_losses': self._create_continuous_losses,
            'high_volatility': self._create_high_volatility,
            'sudden_crash': self._create_sudden_crash,
            'liquidity_crisis': self._create_liquidity_crisis
        }
        
        if scenario_type not in scenarios:
            raise ValueError(f'未知场景类型: {scenario_type}')
        
        return scenarios[scenario_type](length)
    
    def _create_continuous_losses(self, length):
        """连续亏损场景"""
        returns = np.random.normal(-0.02, 0.01, length)
        return returns
    
    def _create_high_volatility(self, length):
        """高波动率场景"""
        returns = np.random.normal(0, 0.05, length)
        return returns
    
    def _create_sudden_crash(self, length):
        """突然崩溃场景"""
        returns = np.random.normal(0.005, 0.01, length)
        # 在中间位置添加一个大崩溃
        crash_day = length // 2
        returns[crash_day] = -0.2  # 20%的单日跌幅
        return returns
    
    def _create_liquidity_crisis(self, length):
        """流动性危机场景"""
        # 前半段正常，后半段波动加大
        returns = np.concatenate([
            np.random.normal(0.003, 0.01, length//2),
            np.random.normal(-0.01, 0.03, length//2)
        ])
        return returns
    
    def test_strategy(self, returns, position_size=0.1):
        """测试策略在给定收益序列下的表现"""
        capital = self.initial_capital
        equity_curve = [capital]
        drawdowns = []
        peak = capital
        
        for r in returns:
            # 计算本次交易的盈亏
            pnl = capital * position_size * r
            capital = max(0, capital + pnl)
            equity_curve.append(capital)
            
            # 计算回撤
            if capital > peak:
                peak = capital
            drawdown = (peak - capital) / peak
            drawdowns.append(drawdown)
        
        # 计算指标
        final_capital = equity_curve[-1]
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        max_drawdown = max(drawdowns)
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        
        return {
            'equity_curve': equity_curve,
            'final_capital': final_capital,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio
        }
    
    def run_stress_tests(self):
        """运行所有压力测试场景"""
        scenarios = ['continuous_losses', 'high_volatility', 'sudden_crash', 'liquidity_crisis']
        results = {}
        
        for scenario in scenarios:
            print(f'运行 {scenario} 场景...')
            returns = self.create_stress_scenario(scenario)
            result = self.test_strategy(returns)
            results[scenario] = result
            
            print(f'  最终资金: {result["final_capital"]:.2f}')
            print(f'  总收益率: {result["total_return"]:.2%}')
            print(f'  最大回撤: {result["max_drawdown"]:.2%}')
            print(f'  夏普比率: {result["sharpe_ratio"]:.4f}')
            print()
        
        return results
    
    def plot_results(self, results):
        """绘制压力测试结果"""
        plt.figure(figsize=(15, 10))
        
        for scenario, result in results.items():
            plt.plot(result['equity_curve'], label=scenario)
        
        plt.axhline(y=self.initial_capital, color='gray', linestyle='--', label='初始资金')
        plt.title('压力测试结果 - 资金曲线')
        plt.xlabel('交易次数')
        plt.ylabel('资金 (元)')
        plt.legend()
        plt.grid(True)
        plt.savefig('stress_test_results.png')
        
        # 绘制最大回撤对比
        plt.figure(figsize=(10, 6))
        scenarios = list(results.keys())
        max_drawdowns = [result['max_drawdown'] for result in results.values()]
        plt.bar(scenarios, max_drawdowns)
        plt.title('各场景最大回撤对比')
        plt.xlabel('场景')
        plt.ylabel('最大回撤')
        plt.xticks(rotation=45)
        plt.grid(True, axis='y')
        plt.savefig('max_drawdown_comparison.png')
    
    def run_full_stress_test(self):
        """运行完整的压力测试"""
        print('开始压力测试...')
        print(f'初始资金: {self.initial_capital} 元')
        print()
        
        results = self.run_stress_tests()
        self.plot_results(results)
        
        # 保存结果
        stress_test_result = {
            'timestamp': datetime.now().isoformat(),
            'initial_capital': self.initial_capital,
            'results': results
        }
        
        with open('stress_test_results.json', 'w', encoding='utf-8') as f:
            json.dump(stress_test_result, f, ensure_ascii=False, indent=2)
        
        print('压力测试完成，结果已保存到 stress_test_results.json')

if __name__ == '__main__':
    tester = StressTester(initial_capital=10000)
    tester.run_full_stress_test()
