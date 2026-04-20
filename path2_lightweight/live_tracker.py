#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.parquet_loader import (
    ParquetLoader, calc_atr, calc_ema, calc_sma, calc_rsi,
    calc_percentile_rank, calc_bollinger_bands, calc_keltner_channels, calc_zscore,
)
from strategies.quantile_short_term_v2 import OptimizedParams
from fusion.signal_fusion import SignalFusion
from data_updater import update_parquet_data, get_realtime_price, SYMBOLS_MAP

SYMBOLS = ['TA', 'RM', 'MA']
INITIAL_CAPITAL = 10000
PARAMS = OptimizedParams(
    percentile_window=40, long_entry_pct=0.25, short_entry_pct=0.75,
    atr_stop_mult=1.5, atr_take_mult=2.0, max_hold_days=7,
    trend_filter_enabled=True,
)

TRACKING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracking')
os.makedirs(TRACKING_DIR, exist_ok=True)


class LiveTracker:
    def __init__(self):
        self.loader = ParquetLoader()
        self.fusion = SignalFusion(
            symbols=SYMBOLS,
            sl_tighten_atr=0.3, tp_widen_atr=0.0,
            hold_extend_days=0, hold_reduce_days=1,
        )
        self.state_file = os.path.join(TRACKING_DIR, 'tracker_state.json')
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'capital': INITIAL_CAPITAL,
            'peak_capital': INITIAL_CAPITAL,
            'positions': {},
            'trade_log': [],
            'daily_log': [],
            'start_date': datetime.now().strftime('%Y-%m-%d'),
            'version': 'v1.1',
        }

    def _save_state(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2, default=str)

    def _get_latest_data(self, symbol, days=120):
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        df = self.loader.load_symbol(symbol, start_date, end_date)
        return df

    def _calc_signals(self, symbol, df):
        if df is None or len(df) < 50:
            return None
        df['pct_rank'] = calc_percentile_rank(df['close'], PARAMS.percentile_window)
        df['ema_trend'] = calc_ema(df['close'], 50)
        df['atr'] = calc_atr(df, 14)
        df['signal_long'] = False
        df['signal_short'] = False
        df['signal_strength'] = 0.0
        if PARAMS.trend_filter_enabled:
            long_cond = (df['pct_rank'] < PARAMS.long_entry_pct) & (df['close'] > df['ema_trend'])
            short_cond = (df['pct_rank'] > PARAMS.short_entry_pct) & (df['close'] < df['ema_trend'])
        else:
            long_cond = df['pct_rank'] < PARAMS.long_entry_pct
            short_cond = df['pct_rank'] > PARAMS.short_entry_pct
        df.loc[long_cond, 'signal_long'] = True
        df.loc[long_cond, 'signal_strength'] = 1 - df.loc[long_cond, 'pct_rank']
        df.loc[short_cond, 'signal_short'] = True
        df.loc[short_cond, 'signal_strength'] = df.loc[short_cond, 'pct_rank']
        return df

    def run_daily(self):
        today = datetime.now().strftime('%Y-%m-%d')
        print(f'\n{"=" * 60}')
        print(f'实盘跟踪日报 | {today} | v1.1')
        print(f'{"=" * 60}')

        print('\n[1/3] 更新日K数据...')
        update_parquet_data(SYMBOLS)

        capital = self.state['capital']
        peak = self.state['peak_capital']
        dd = (peak - capital) / peak if peak > 0 else 0

        print(f'\n[2/3] 信号扫描')
        print(f'\n--- 账户状态 ---')
        print(f'  当前资金: {capital:,.2f}元')
        print(f'  峰值资金: {peak:,.2f}元')
        print(f'  当前回撤: {dd:.1%}')
        print(f'  累计收益: {(capital / INITIAL_CAPITAL - 1) * 100:+.1f}%')
        print(f'  持仓数量: {len(self.state["positions"])}')
        print(f'  历史交易: {len(self.state["trade_log"])}笔')

        if self.state['positions']:
            print(f'\n--- 当前持仓 ---')
            for sym, pos in self.state['positions'].items():
                direction = '多' if pos['direction'] == 1 else '空'
                hold_days = (datetime.now() - pd.Timestamp(pos['entry_date'])).days
                print(f'  {sym}: {direction} | 入场价={pos["entry_price"]:.0f} | '
                      f'止损={pos["stop_loss"]:.0f} | 止盈={pos["take_profit"]:.0f} | '
                      f'持仓{hold_days}天 | 融合={pos.get("fusion", "none")}')

        print(f'\n--- 信号扫描 ---')
        self.fusion.symbols = SYMBOLS
        init_start = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
        init_end = today
        self.fusion.initialize(init_start, init_end)

        new_signals = []
        for symbol in SYMBOLS:
            df = self._get_latest_data(symbol)
            if df is None or len(df) < 2:
                print(f'  {symbol}: 数据不足')
                continue
            df = self._calc_signals(symbol, df)
            if df is None:
                print(f'  {symbol}: 指标计算失败')
                continue

            latest = df.iloc[-1]
            price = latest['close']
            atr = latest['atr']
            pct_rank = latest['pct_rank']

            if symbol in self.state['positions']:
                pos = self.state['positions'][symbol]
                direction = pos['direction']
                hold_days = (datetime.now() - pd.Timestamp(pos['entry_date'])).days
                max_hold = pos.get('max_hold_days', 7)

                if direction == 1:
                    unrealized = (price - pos['entry_price']) * self.loader.get_spec(symbol).multiplier * pos.get('size', 1)
                else:
                    unrealized = (pos['entry_price'] - price) * self.loader.get_spec(symbol).multiplier * pos.get('size', 1)

                exit_reason = None
                if direction == 1 and latest.get('low', price) <= pos['stop_loss']:
                    exit_reason = 'hard_stop'
                elif direction == -1 and latest.get('high', price) >= pos['stop_loss']:
                    exit_reason = 'hard_stop'
                if exit_reason is None:
                    if direction == 1 and latest.get('high', price) >= pos['take_profit']:
                        exit_reason = 'atr_tp'
                    elif direction == -1 and latest.get('low', price) <= pos['take_profit']:
                        exit_reason = 'atr_tp'
                if exit_reason is None and hold_days >= max_hold:
                    exit_reason = f'timeout_{hold_days}'

                if exit_reason:
                    print(f'  {symbol}: [平仓信号] {exit_reason} | 浮盈={unrealized:+.0f}元')
                else:
                    print(f'  {symbol}: [持仓中] 浮盈={unrealized:+.0f}元 | '
                          f'PctRank={pct_rank:.2f} | ATR={atr:.0f}')
            else:
                has_long = latest.get('signal_long', False)
                has_short = latest.get('signal_short', False)
                if has_long or has_short:
                    p2_dir = 1 if has_long else -1
                    p2_str = latest.get('signal_strength', 0)
                    fused = self.fusion.fuse(p2_dir, p2_str, symbol, latest['date'])
                    direction = '多' if p2_dir == 1 else '空'
                    fusion_info = fused.enhancement_applied
                    print(f'  {symbol}: [新信号] {direction} | 强度={p2_str:.2f} | '
                          f'PctRank={pct_rank:.2f} | ATR={atr:.0f} | '
                          f'融合={fusion_info}')
                    new_signals.append({
                        'symbol': symbol, 'direction': p2_dir,
                        'strength': p2_str, 'price': price,
                        'atr': atr, 'fusion': fused,
                    })
                else:
                    print(f'  {symbol}: [无信号] PctRank={pct_rank:.2f} | ATR={atr:.0f}')

        print(f'\n[3/3] 风控检查')
        self._risk_check(dd)

        if self.state['trade_log']:
            wins = sum(1 for t in self.state['trade_log'] if t.get('pnl', 0) > 0)
            total = len(self.state['trade_log'])
            avg_win = np.mean([t['pnl'] for t in self.state['trade_log'] if t.get('pnl', 0) > 0]) if wins > 0 else 0
            avg_loss = abs(np.mean([t['pnl'] for t in self.state['trade_log'] if t.get('pnl', 0) <= 0])) if total > wins else 0
            print(f'\n--- 交易统计 ---')
            print(f'  胜率: {wins}/{total} ({wins/total*100:.0f}%)')
            print(f'  盈亏比: {avg_win/avg_loss:.2f}' if avg_loss > 0 else '  盈亏比: N/A')
            print(f'  期望/笔: {np.mean([t["pnl"] for t in self.state["trade_log"]]):.0f}元')

        daily_record = {
            'date': today,
            'capital': capital,
            'drawdown': round(dd * 100, 2),
            'return_pct': round((capital / INITIAL_CAPITAL - 1) * 100, 2),
            'positions': len(self.state['positions']),
            'new_signals': len(new_signals),
        }
        self.state['daily_log'].append(daily_record)
        self._save_state()

        report_file = os.path.join(TRACKING_DIR, f'daily_{today}.json')
        report = {
            'date': today,
            'version': 'v1.1',
            'account': {
                'capital': capital,
                'peak_capital': peak,
                'drawdown_pct': round(dd * 100, 2),
                'total_return_pct': round((capital / INITIAL_CAPITAL - 1) * 100, 2),
            },
            'positions': self.state['positions'],
            'new_signals': [{
                'symbol': s['symbol'],
                'direction': 'long' if s['direction'] == 1 else 'short',
                'strength': round(s['strength'], 4),
                'price': round(s['price'], 2),
                'fusion': s['fusion'].enhancement_applied,
            } for s in new_signals],
            'trade_stats': {
                'total_trades': len(self.state['trade_log']),
                'win_rate': round(sum(1 for t in self.state['trade_log'] if t.get('pnl', 0) > 0) / max(len(self.state['trade_log']), 1) * 100, 1),
            },
        }
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f'\n日报已保存: {report_file}')
        return report

    def run_realtime_risk(self, interval=60):
        print(f'\n{"=" * 60}')
        print(f'实时风控监控 | v1.1 | 间隔{interval}秒')
        print(f'{"=" * 60}')

        if not self.state['positions']:
            print('当前无持仓，无需实时监控')
            return

        print(f'\n监控持仓:')
        for sym, pos in self.state['positions'].items():
            direction = '多' if pos['direction'] == 1 else '空'
            print(f'  {sym}: {direction} | 入场={pos["entry_price"]:.0f} | '
                  f'止损={pos["stop_loss"]:.0f} | 止盈={pos["take_profit"]:.0f}')

        alert_log_file = os.path.join(TRACKING_DIR, 'realtime_alerts.log')
        check_count = 0
        try:
            while True:
                check_count += 1
                now = datetime.now().strftime('%H:%M:%S')
                has_alert = False

                for sym, pos in list(self.state['positions'].items()):
                    rt = get_realtime_price(SYMBOLS_MAP.get(sym, {}).get('ak_code', f'{sym}0'))
                    if rt is None:
                        continue

                    current_price = rt['price']
                    direction = pos['direction']
                    alert_msg = None

                    if direction == 1:
                        unrealized = (current_price - pos['entry_price']) * self.loader.get_spec(sym).multiplier * pos.get('size', 1)
                        if current_price <= pos['stop_loss']:
                            alert_msg = f'[STOP] {sym} 止损触发! 现价{current_price:.0f}<=止损{pos["stop_loss"]:.0f}'
                        elif current_price >= pos['take_profit']:
                            alert_msg = f'[PROFIT] {sym} 止盈触发! 现价{current_price:.0f}>=止盈{pos["take_profit"]:.0f}'
                        elif current_price <= pos['stop_loss'] * 1.02:
                            alert_msg = f'[WARN] {sym} 接近止损! 现价{current_price:.0f}, 止损{pos["stop_loss"]:.0f}'
                    else:
                        unrealized = (pos['entry_price'] - current_price) * self.loader.get_spec(sym).multiplier * pos.get('size', 1)
                        if current_price >= pos['stop_loss']:
                            alert_msg = f'[STOP] {sym} 止损触发! 现价{current_price:.0f}>=止损{pos["stop_loss"]:.0f}'
                        elif current_price <= pos['take_profit']:
                            alert_msg = f'[PROFIT] {sym} 止盈触发! 现价{current_price:.0f}<=止盈{pos["take_profit"]:.0f}'
                        elif current_price >= pos['stop_loss'] * 0.98:
                            alert_msg = f'[WARN] {sym} 接近止损! 现价{current_price:.0f}, 止损{pos["stop_loss"]:.0f}'

                    if alert_msg:
                        has_alert = True
                        print(f'[{now}] {alert_msg}')
                        with open(alert_log_file, 'a', encoding='utf-8') as f:
                            f.write(f'[{datetime.now().isoformat()}] {alert_msg}\n')

                if not has_alert and check_count % 10 == 0:
                    prices = []
                    for sym in self.state['positions']:
                        rt = get_realtime_price(SYMBOLS_MAP.get(sym, {}).get('ak_code', f'{sym}0'))
                        if rt:
                            prices.append(f'{sym}={rt["price"]:.0f}')
                    print(f'[{now}] 心跳 | {" | ".join(prices) if prices else "无行情"}')

                time.sleep(interval)
        except KeyboardInterrupt:
            print(f'\n实时监控已停止 (共检查{check_count}次)')

    def _risk_check(self, dd):
        print(f'\n--- 风控检查 ---')
        if dd >= 0.35:
            print(f'  [XXX] 三级风控: 回撤{dd:.1%}>=35%, 建议平掉所有持仓')
        elif dd >= 0.27:
            print(f'  [RED] 二级风控: 回撤{dd:.1%}>=27%, 停止开新仓')
        elif dd >= 0.20:
            print(f'  [YLW] 一级风控: 回撤{dd:.1%}>=20%, 新仓仓位减半')
        else:
            print(f'  [GRN] 正常: 回撤{dd:.1%}<20%')

        if self.state['trade_log']:
            consecutive_losses = 0
            for t in reversed(self.state['trade_log']):
                if t.get('pnl', 0) < 0:
                    consecutive_losses += 1
                else:
                    break
            if consecutive_losses >= 3:
                print(f'  [WARN] 连亏保护: 连续{consecutive_losses}笔亏损, 建议暂停交易3天')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='实盘跟踪系统 v1.1')
    parser.add_argument('mode', nargs='?', default='daily',
                        choices=['daily', 'risk', 'both'],
                        help='运行模式: daily=日K信号扫描, risk=实时风控, both=先daily再risk')
    parser.add_argument('--interval', type=int, default=60,
                        help='实时风控检查间隔(秒), 默认60')
    args = parser.parse_args()

    tracker = LiveTracker()

    if args.mode in ('daily', 'both'):
        tracker.run_daily()

    if args.mode in ('risk', 'both'):
        tracker.run_realtime_risk(interval=args.interval)
