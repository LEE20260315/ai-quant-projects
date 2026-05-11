#!/usr/bin/env python
# -*- coding: utf-8 -*-
import numpy as np
import json
from datetime import datetime


class EnhancedStressTester:
    def __init__(self, initial_capital=10000):
        self.initial_capital = initial_capital

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
        return trades

    def scenario_black_swan(self, pnl_list, crash_pct=0.30):
        capital = self.initial_capital
        peak = capital
        max_dd = 0
        crash_idx = len(pnl_list) // 2 if len(pnl_list) > 10 else len(pnl_list)
        for i, pnl in enumerate(pnl_list):
            if i == crash_idx:
                crash_loss = capital * crash_pct
                capital -= crash_loss
            capital += pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return capital, max_dd

    def scenario_flash_crash(self, pnl_list, crash_pct=0.15, recovery_pct=0.10):
        capital = self.initial_capital
        peak = capital
        max_dd = 0
        crash_idx = len(pnl_list) // 2 if len(pnl_list) > 10 else len(pnl_list)
        for i, pnl in enumerate(pnl_list):
            if i == crash_idx:
                crash_loss = capital * crash_pct
                capital -= crash_loss
            if i == crash_idx + 1:
                recovery = capital * recovery_pct
                capital += recovery
            capital += pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return capital, max_dd

    def scenario_losing_streak(self, pnl_list, extra_losses=5, loss_pct=0.05):
        capital = self.initial_capital
        peak = capital
        max_dd = 0
        for pnl in pnl_list:
            capital += pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak
            max_dd = max(max_dd, dd)
        for _ in range(extra_losses):
            capital -= capital * loss_pct
            dd = (peak - capital) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return capital, max_dd

    def scenario_volatility_squeeze(self, pnl_list, squeeze_factor=0.5):
        capital = self.initial_capital
        peak = capital
        max_dd = 0
        for pnl in pnl_list:
            adjusted_pnl = pnl * squeeze_factor
            capital += adjusted_pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak
            max_dd = max(max_dd, dd)
        return capital, max_dd

    def scenario_margin_call(self, pnl_list, margin_call_pct=0.50):
        capital = self.initial_capital
        peak = capital
        max_dd = 0
        forced_close = False
        for pnl in pnl_list:
            capital += pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak
            max_dd = max(max_dd, dd)
            if dd >= margin_call_pct and not forced_close:
                capital *= 0.7
                forced_close = True
                dd = (peak - capital) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)
        return capital, max_dd

    def run_all_scenarios(self):
        print('=' * 60)
        print('增强压力测试 - 6大极端场景')
        print('=' * 60)

        trades = self.load_trade_details()
        if not trades:
            print('无交易数据')
            return
        pnl_list = [t['pnl'] for t in trades]
        print(f'加载 {len(trades)} 条交易记录')
        print(f'原始盈亏: 总计{sum(pnl_list):+.0f}元, '
              f'胜率{sum(1 for p in pnl_list if p > 0)/len(pnl_list):.1%}')
        print()

        scenarios = [
            ('黑天鹅事件(30%暴跌)', lambda: self.scenario_black_swan(pnl_list, 0.30)),
            ('黑天鹅事件(50%暴跌)', lambda: self.scenario_black_swan(pnl_list, 0.50)),
            ('闪崩(15%暴跌+10%反弹)', lambda: self.scenario_flash_crash(pnl_list)),
            ('连续亏损(5笔额外5%亏损)', lambda: self.scenario_losing_streak(pnl_list)),
            ('波动率收缩(收益减半)', lambda: self.scenario_volatility_squeeze(pnl_list)),
            ('追加保证金(50%回撤强平)', lambda: self.scenario_margin_call(pnl_list)),
        ]

        results = {}
        for name, scenario_fn in scenarios:
            final_cap, max_dd = scenario_fn()
            total_ret = (final_cap / self.initial_capital - 1) * 100
            results[name] = {
                'final_capital': round(final_cap, 2),
                'total_return_pct': round(total_ret, 2),
                'max_drawdown_pct': round(max_dd * 100, 2),
            }
            status = 'SURVIVE' if final_cap > self.initial_capital * 0.3 else 'DANGER'
            print(f'  {name}:')
            print(f'    最终资金: {final_cap:,.0f}元 | 收益: {total_ret:+.1f}% | '
                  f'最大回撤: {max_dd:.1%} | [{status}]')

        output = {
            'timestamp': datetime.now().isoformat(),
            'initial_capital': self.initial_capital,
            'num_trades': len(trades),
            'scenarios': results,
        }
        with open('stress_test_enhanced.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print('\n结果已保存到 stress_test_enhanced.json')


if __name__ == '__main__':
    tester = EnhancedStressTester(initial_capital=10000)
    tester.run_all_scenarios()
