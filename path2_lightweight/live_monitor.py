#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import time
from datetime import datetime
from pathlib import Path


class LiveMonitor:
    def __init__(self, config_path='live_monitor_config.json'):
        self.config = self._load_config(config_path)
        self.state = {
            'capital': self.config['initial_capital'],
            'peak_capital': self.config['initial_capital'],
            'positions': {},
            'daily_pnl': [],
            'alerts': [],
            'trade_log': [],
        }

    def _load_config(self, path):
        default = {
            'initial_capital': 10000,
            'max_drawdown_pct': 0.25,
            'warning_drawdown_pct': 0.15,
            'max_positions': 3,
            'max_single_loss_pct': 0.03,
            'daily_loss_limit_pct': 0.05,
            'position_timeout_days': 7,
            'check_interval_seconds': 60,
            'symbols': ['TA', 'RM', 'MA'],
            'alert_channels': ['console', 'file'],
        }
        if Path(path).exists():
            with open(path, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                default.update(saved)
        return default

    def check_drawdown(self):
        dd = (self.state['peak_capital'] - self.state['capital']) / self.state['peak_capital']
        if dd >= self.config['max_drawdown_pct']:
            self._alert('CRITICAL', f'回撤{dd:.1%}超过最大限制{self.config["max_drawdown_pct"]:.1%}, 暂停交易')
            return False
        if dd >= self.config['warning_drawdown_pct']:
            self._alert('WARNING', f'回撤{dd:.1%}接近警告线{self.config["warning_drawdown_pct"]:.1%}')
        return True

    def check_position_limit(self):
        if len(self.state['positions']) >= self.config['max_positions']:
            self._alert('INFO', f'持仓数{len(self.state["positions"])}已达上限{self.config["max_positions"]}')
            return False
        return True

    def check_daily_loss(self, today_pnl):
        daily_loss = abs(min(today_pnl, 0))
        limit = self.state['capital'] * self.config['daily_loss_limit_pct']
        if daily_loss >= limit:
            self._alert('WARNING', f'当日亏损{daily_loss:.0f}元超过限额{limit:.0f}元')
            return False
        return True

    def check_position_timeout(self, current_date):
        for sym, pos in list(self.state['positions'].items()):
            hold_days = (current_date - pos['entry_date']).days
            if hold_days >= self.config['position_timeout_days']:
                self._alert('INFO', f'{sym}持仓{hold_days}天超时, 建议平仓')

    def _alert(self, level, message):
        alert = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
        }
        self.state['alerts'].append(alert)
        print(f'[{level}] {message}')
        if 'file' in self.config['alert_channels']:
            with open('monitor_alerts.log', 'a', encoding='utf-8') as f:
                f.write(f"[{alert['timestamp']}] [{level}] {message}\n")

    def update_capital(self, new_capital):
        self.state['capital'] = new_capital
        if new_capital > self.state['peak_capital']:
            self.state['peak_capital'] = new_capital

    def add_position(self, symbol, direction, entry_price, size):
        self.state['positions'][symbol] = {
            'direction': direction,
            'entry_price': entry_price,
            'size': size,
            'entry_date': datetime.now(),
        }

    def remove_position(self, symbol):
        if symbol in self.state['positions']:
            del self.state['positions'][symbol]

    def generate_daily_report(self):
        dd = (self.state['peak_capital'] - self.state['capital']) / self.state['peak_capital']
        report = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'capital': self.state['capital'],
            'peak_capital': self.state['peak_capital'],
            'drawdown_pct': round(dd * 100, 2),
            'positions': len(self.state['positions']),
            'total_return_pct': round((self.state['capital'] / self.config['initial_capital'] - 1) * 100, 2),
            'alerts_today': len([a for a in self.state['alerts']
                                if a['timestamp'].startswith(datetime.now().strftime('%Y-%m-%d'))]),
        }
        with open('daily_report.json', 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return report

    def save_config(self, path='live_monitor_config.json'):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    monitor = LiveMonitor()
    print('实盘监控系统已初始化')
    print(f'初始资金: {monitor.config["initial_capital"]}元')
    print(f'最大回撤限制: {monitor.config["max_drawdown_pct"]:.1%}')
    print(f'警告回撤: {monitor.config["warning_drawdown_pct"]:.1%}')
    print(f'最大持仓数: {monitor.config["max_positions"]}')
    print(f'监控品种: {monitor.config["symbols"]}')

    report = monitor.generate_daily_report()
    print(f'\n日报: 资金{report["capital"]}元, 回撤{report["drawdown_pct"]}%, '
          f'收益{report["total_return_pct"]}%')
