import numpy as np
import pandas as pd
import json
from datetime import datetime
from pathlib import Path


class MonteCarloAnalyzer:
    def __init__(self, initial_capital=10000, num_simulations=5000, block_size=10):
        self.initial_capital = initial_capital
        self.num_simulations = num_simulations
        self.block_size = block_size

    def load_trade_details(self, file_path='trade_details.txt'):
        trades = []
        seen = set()
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('→')[-1].split(', ')
                trade = {}
                key_parts = []
                for part in parts:
                    if ':' not in part:
                        continue
                    k, v = part.split(':', 1)
                    k, v = k.strip(), v.strip()
                    if k in ('盈亏', 'pnl'):
                        trade['pnl'] = float(v)
                    elif k in ('日期', 'date'):
                        key_parts.append(v)
                    elif k in ('品种', 'symbol'):
                        key_parts.append(v)
                key = '|'.join(key_parts) if key_parts else str(len(trades))
                if 'pnl' in trade and key not in seen:
                    seen.add(key)
                    trades.append(trade)
        print(f'加载 {len(trades)} 条唯一交易')
        return trades

    def load_trades_from_list(self, trades_list):
        trades = []
        seen = set()
        for t in trades_list:
            pnl = t.get('pnl', 0)
            key = f"{t.get('entry_date', '')}|{t.get('symbol', '')}|{t.get('direction', '')}"
            if key not in seen:
                seen.add(key)
                trades.append({'pnl': pnl})
        print(f'加载 {len(trades)} 条唯一交易(内存)')
        return trades

    def block_bootstrap(self, pnl_list, target_length):
        n = len(pnl_list)
        result = []
        while len(result) < target_length:
            start = np.random.randint(0, n)
            end = min(start + self.block_size, n)
            result.extend(pnl_list[start:end])
        return result[:target_length]

    def simulate_path(self, pnl_list, target_trades, bankruptcy_threshold=0.5):
        capital = self.initial_capital
        peak = capital
        max_dd = 0
        sampled = self.block_bootstrap(pnl_list, target_trades)
        for pnl in sampled:
            capital += pnl
            if capital <= 0:
                capital = 0
                break
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak
            if dd > max_dd:
                max_dd = dd
            if dd >= bankruptcy_threshold:
                break
        return capital, max_dd

    def run_analysis(self, trades, target_trades=100, bankruptcy_threshold=0.5):
        pnl_list = [t['pnl'] for t in trades]
        win_pnl = [p for p in pnl_list if p > 0]
        loss_pnl = [p for p in pnl_list if p <= 0]

        stats = {
            'total_trades': len(pnl_list),
            'win_rate': len(win_pnl) / len(pnl_list) if pnl_list else 0,
            'avg_win': float(np.mean(win_pnl)) if win_pnl else 0,
            'avg_loss': float(np.mean(loss_pnl)) if loss_pnl else 0,
            'profit_factor': abs(sum(win_pnl) / sum(loss_pnl)) if sum(loss_pnl) != 0 else 0,
            'expectancy': float(np.mean(pnl_list)) if pnl_list else 0,
        }
        print(f'交易统计: 胜率={stats["win_rate"]:.1%}, 盈亏比={stats["profit_factor"]:.2f}, '
              f'期望={stats["expectancy"]:.1f}元/笔')

        final_capitals = []
        max_drawdowns = []
        bankruptcies = 0

        for i in range(self.num_simulations):
            if i % 1000 == 0 and i > 0:
                print(f'  模拟进度: {i}/{self.num_simulations}')
            fc, md = self.simulate_path(pnl_list, target_trades, bankruptcy_threshold)
            final_capitals.append(fc)
            max_drawdowns.append(md)
            if md >= bankruptcy_threshold:
                bankruptcies += 1

        results = {
            'bankruptcy_prob': float(bankruptcies / self.num_simulations),
            'avg_final_capital': float(np.mean(final_capitals)),
            'median_final_capital': float(np.median(final_capitals)),
            'avg_max_drawdown': float(np.mean(max_drawdowns)),
            'p95_max_drawdown': float(np.percentile(max_drawdowns, 95)),
            'p99_max_drawdown': float(np.percentile(max_drawdowns, 99)),
            'profit_prob': float(sum(1 for c in final_capitals if c > self.initial_capital) / self.num_simulations),
            'avg_annual_return': float((np.mean(final_capitals) / self.initial_capital) ** (252 / (target_trades * 10)) - 1),
        }

        return stats, results

    def run_full(self):
        print('=' * 60)
        print('蒙特卡罗分析 - 块自助重采样法')
        print('=' * 60)

        trades = self.load_trade_details()
        if not trades:
            print('无交易数据')
            return

        for target in [50, 100, 200]:
            print(f'\n--- 目标交易数: {target} ---')
            stats, results = self.run_analysis(trades, target, bankruptcy_threshold=0.5)
            print(f'  破产概率(>50%回撤): {results["bankruptcy_prob"]:.1%}')
            print(f'  盈利概率: {results["profit_prob"]:.1%}')
            print(f'  平均最终资金: {results["avg_final_capital"]:.0f}元')
            print(f'  平均最大回撤: {results["avg_max_drawdown"]:.1%}')
            print(f'  95%分位最大回撤: {results["p95_max_drawdown"]:.1%}')

        stats, results = self.run_analysis(trades, 100, 0.5)
        output = {
            'timestamp': datetime.now().isoformat(),
            'method': 'block_bootstrap',
            'block_size': self.block_size,
            'num_simulations': self.num_simulations,
            'trade_stats': stats,
            'simulation_results': results,
        }
        with open('monte_carlo_analysis.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print('\n结果已保存到 monte_carlo_analysis.json')


if __name__ == '__main__':
    analyzer = MonteCarloAnalyzer(initial_capital=10000, num_simulations=5000, block_size=10)
    analyzer.run_full()
