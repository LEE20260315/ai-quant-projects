#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import tempfile
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
from email_sender import send_email, generate_daily_report_html

SYMBOLS = ['TA', 'RM', 'MA']
INITIAL_CAPITAL = 10000
COMMISSION_RATE = 0.0001
SLIPPAGE_RATE = 0.0001
MAX_POSITIONS = 3
MAX_POS_PCT = 0.30
MAX_TOTAL_PCT = 0.60

PARAMS = OptimizedParams(
    percentile_window=40, long_entry_pct=0.30, short_entry_pct=0.70,
    atr_stop_mult=1.8, atr_take_mult=2.5, max_hold_days=10,
    trend_filter_enabled=True,
    trend_entry_enabled=True,
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
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            'capital': INITIAL_CAPITAL,
            'peak_capital': INITIAL_CAPITAL,
            'positions': {},
            'trade_log': [],
            'daily_log': [],
            'start_date': datetime.now().strftime('%Y-%m-%d'),
            'version': 'v1.2',
        }

    def _save_state(self):
        fd, tmp_path = tempfile.mkstemp(
            dir=TRACKING_DIR, suffix='.tmp', prefix='state_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, self.state_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

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
        df['ema20'] = calc_ema(df['close'], 20)
        df['atr'] = calc_atr(df, 14)
        df['atr_ma'] = calc_sma(df['atr'], 20)
        df['signal_long'] = False
        df['signal_short'] = False
        df['signal_trend_long'] = False
        df['signal_trend_short'] = False
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

        if PARAMS.trend_entry_enabled:
            trend_long_cond = (
                (df['pct_rank'] > PARAMS.trend_pct_rank_high) &
                (df['close'] > df['ema_trend']) &
                (df['ema20'] > df['ema_trend']) &
                (df['atr'] > df['atr_ma'])
            )
            trend_short_cond = (
                (df['pct_rank'] < PARAMS.trend_pct_rank_low) &
                (df['close'] < df['ema_trend']) &
                (df['ema20'] < df['ema_trend']) &
                (df['atr'] > df['atr_ma'])
            )
            df.loc[trend_long_cond, 'signal_trend_long'] = True
            df.loc[trend_long_cond, 'signal_strength'] = df.loc[trend_long_cond, 'pct_rank']
            df.loc[trend_short_cond, 'signal_trend_short'] = True
            df.loc[trend_short_cond, 'signal_strength'] = 1 - df.loc[trend_short_cond, 'pct_rank']

        return df

    def _execute_close(self, symbol, exit_price, exit_reason):
        pos = self.state['positions'].get(symbol)
        if pos is None:
            return
        spec = self.loader.get_spec(symbol)
        size = pos.get('size', 1)
        direction = pos['direction']
        entry_price = pos['entry_price']

        if direction == 1:
            gross_pnl = (exit_price - entry_price) * spec.multiplier * size
        else:
            gross_pnl = (entry_price - exit_price) * spec.multiplier * size

        cost = (entry_price + exit_price) * spec.multiplier * size * (COMMISSION_RATE + SLIPPAGE_RATE)
        net_pnl = gross_pnl - cost

        self.state['capital'] += net_pnl
        if self.state['capital'] > self.state['peak_capital']:
            self.state['peak_capital'] = self.state['capital']

        hold_days = (datetime.now() - pd.Timestamp(pos['entry_date'])).days

        trade_record = {
            'symbol': symbol,
            'direction': 'long' if direction == 1 else 'short',
            'entry_date': pos['entry_date'],
            'exit_date': datetime.now().strftime('%Y-%m-%d'),
            'entry_price': round(entry_price, 2),
            'exit_price': round(exit_price, 2),
            'size': size,
            'pnl': round(net_pnl, 2),
            'hold_days': hold_days,
            'exit_reason': exit_reason,
            'capital_after': round(self.state['capital'], 2),
            'fusion': pos.get('fusion', 'none'),
        }
        self.state['trade_log'].append(trade_record)
        del self.state['positions'][symbol]

        dir_text = '多' if direction == 1 else '空'
        print(f'  [EXEC CLOSE] {symbol} {dir_text}平仓 | 原因={exit_reason} | '
              f'入场={entry_price:.0f} 出场={exit_price:.0f} | '
              f'盈亏={net_pnl:+.0f}元 | 持仓{hold_days}天')
        return trade_record

    def _execute_open(self, symbol, direction, price, atr, fused_signal, entry_type='revert'):
        spec = self.loader.get_spec(symbol)
        if spec is None:
            print(f'  [SKIP] {symbol}: 品种规格未找到')
            return None

        margin_needed = price * spec.multiplier * spec.margin_ratio
        if margin_needed > self.state['capital'] * MAX_POS_PCT:
            margin_needed = self.state['capital'] * MAX_POS_PCT

        total_margin = sum(p.get('margin_used', 0) for p in self.state['positions'].values())
        if total_margin + margin_needed > self.state['capital'] * MAX_TOTAL_PCT:
            print(f'  [SKIP] {symbol}: 总仓位超限')
            return None

        size = max(1, int(margin_needed / (price * spec.multiplier * spec.margin_ratio)))
        actual_margin = price * spec.multiplier * size * spec.margin_ratio
        if actual_margin > self.state['capital'] * MAX_POS_PCT:
            size = max(1, int(self.state['capital'] * MAX_POS_PCT / (price * spec.multiplier * spec.margin_ratio)))
            actual_margin = price * spec.multiplier * size * spec.margin_ratio

        if entry_type == 'trend' and PARAMS.trend_entry_enabled:
            sl_mult = PARAMS.trend_atr_stop_mult
            tp_mult = PARAMS.trend_atr_take_mult
            max_hold = PARAMS.trend_max_hold_days
        else:
            sl_mult = PARAMS.atr_stop_mult
            tp_mult = PARAMS.atr_take_mult
            max_hold = PARAMS.max_hold_days

        if fused_signal:
            sl_mult += fused_signal.sl_atr_adj
            tp_mult += fused_signal.tp_atr_adj
            max_hold += fused_signal.hold_days_adj
            sl_mult = max(0.5, sl_mult)
            tp_mult = max(0.5, tp_mult)
            max_hold = max(2, max_hold)

        if direction == 1:
            stop_loss = price - atr * sl_mult
            take_profit = price + atr * tp_mult
        else:
            stop_loss = price + atr * sl_mult
            take_profit = price - atr * tp_mult

        self.state['positions'][symbol] = {
            'direction': direction,
            'entry_price': round(price, 2),
            'entry_date': datetime.now().strftime('%Y-%m-%d'),
            'size': size,
            'stop_loss': round(stop_loss, 2),
            'take_profit': round(take_profit, 2),
            'max_hold_days': max_hold,
            'margin_used': round(actual_margin, 2),
            'fusion': fused_signal.enhancement_applied if fused_signal else 'none',
            'dominant_strategy': fused_signal.dominant_strategy if fused_signal else 'none',
        }

        dir_text = '多' if direction == 1 else '空'
        fusion_text = fused_signal.enhancement_applied if fused_signal else 'none'
        print(f'  [EXEC OPEN] {symbol} {dir_text}开仓 | 价格={price:.0f} | '
              f'止损={stop_loss:.0f} 止盈={take_profit:.0f} | '
              f'手数={size} 保证金={actual_margin:.0f} | '
              f'最大持仓{max_hold}天 | 融合={fusion_text}')
        return self.state['positions'][symbol]

    def run_daily(self):
        today = datetime.now().strftime('%Y-%m-%d')
        print(f'\n{"=" * 60}')
        print(f'实盘跟踪日报 | {today} | v1.2')
        print(f'{"=" * 60}')

        print('\n[1/5] 更新日K数据...')
        update_parquet_data(SYMBOLS)

        self.loader.clear_cache()

        capital = self.state['capital']
        peak = self.state['peak_capital']
        dd = (peak - capital) / peak if peak > 0 else 0

        print(f'\n[2/5] 信号扫描与交易执行')
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

        signal_list = []
        total_unrealized_pnl = 0
        position_snapshots = {}
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
                spec = self.loader.get_spec(symbol)
                size = pos.get('size', 1)

                if direction == 1:
                    unrealized = (price - pos['entry_price']) * spec.multiplier * size
                else:
                    unrealized = (pos['entry_price'] - price) * spec.multiplier * size

                total_unrealized_pnl += unrealized
                position_snapshots[symbol] = {
                    'current_price': round(price, 2),
                    'unrealized_pnl': round(unrealized, 2),
                }

                exit_reason = None
                exit_price = price
                if direction == 1 and latest.get('low', price) <= pos['stop_loss']:
                    exit_reason = 'hard_stop'
                    exit_price = pos['stop_loss']
                elif direction == -1 and latest.get('high', price) >= pos['stop_loss']:
                    exit_reason = 'hard_stop'
                    exit_price = pos['stop_loss']
                if exit_reason is None:
                    if direction == 1 and latest.get('high', price) >= pos['take_profit']:
                        exit_reason = 'atr_tp'
                        exit_price = pos['take_profit']
                    elif direction == -1 and latest.get('low', price) <= pos['take_profit']:
                        exit_reason = 'atr_tp'
                        exit_price = pos['take_profit']
                if exit_reason is None and hold_days >= max_hold:
                    exit_reason = f'timeout_{hold_days}'

                if exit_reason:
                    self._execute_close(symbol, exit_price, exit_reason)
                else:
                    print(f'  {symbol}: [持仓中] 浮盈={unrealized:+.0f}元 | '
                          f'PctRank={pct_rank:.2f} | ATR={atr:.0f}')
            else:
                has_long = latest.get('signal_long', False)
                has_short = latest.get('signal_short', False)
                has_trend_long = latest.get('signal_trend_long', False)
                has_trend_short = latest.get('signal_trend_short', False)
                has_signal = has_long or has_short or has_trend_long or has_trend_short

                if has_signal:
                    if has_trend_long:
                        p2_dir = 1
                        entry_type = 'trend'
                    elif has_trend_short:
                        p2_dir = -1
                        entry_type = 'trend'
                    elif has_long:
                        p2_dir = 1
                        entry_type = 'revert'
                    else:
                        p2_dir = -1
                        entry_type = 'revert'

                    p2_str = latest.get('signal_strength', 0)
                    fused = self.fusion.fuse(p2_dir, p2_str, symbol, latest['date'])
                    direction_text = '多' if p2_dir == 1 else '空'
                    fusion_info = fused.enhancement_applied
                    print(f'  {symbol}: [新信号] {direction_text} | 强度={p2_str:.2f} | '
                          f'PctRank={pct_rank:.2f} | ATR={atr:.0f} | '
                          f'融合={fusion_info}')

                    if len(self.state['positions']) < MAX_POSITIONS:
                        self._execute_open(symbol, p2_dir, price, atr, fused, entry_type)
                    else:
                        print(f'  [SKIP] {symbol}: 持仓数已达上限({MAX_POSITIONS})')
                    signal_list.append({
                        'symbol': symbol, 'direction': p2_dir,
                        'direction_text': direction_text,
                        'pct_rank': pct_rank, 'atr': atr,
                        'fusion': fusion_info,
                    })
                else:
                    print(f'  {symbol}: [无信号] PctRank={pct_rank:.2f} | ATR={atr:.0f}')

        print(f'\n[3/5] 风控检查与自动执行')
        self._risk_check_and_execute()

        capital = self.state['capital']
        peak = self.state['peak_capital']
        dd = (peak - capital) / peak if peak > 0 else 0

        total_equity = capital + total_unrealized_pnl
        equity_peak = max(peak, total_equity)
        equity_dd = (equity_peak - total_equity) / equity_peak if equity_peak > 0 else 0

        print(f'\n--- 权益汇总 ---')
        print(f'  已实现资金: {capital:,.2f}元')
        print(f'  浮动盈亏:   {total_unrealized_pnl:+,.2f}元')
        print(f'  账户权益:   {total_equity:,.2f}元')
        print(f'  权益收益率: {(total_equity / INITIAL_CAPITAL - 1) * 100:+.2f}%')

        if self.state['trade_log']:
            wins = sum(1 for t in self.state['trade_log'] if t.get('pnl', 0) > 0)
            total = len(self.state['trade_log'])
            avg_win = np.mean([t['pnl'] for t in self.state['trade_log'] if t.get('pnl', 0) > 0]) if wins > 0 else 0
            avg_loss = abs(np.mean([t['pnl'] for t in self.state['trade_log'] if t.get('pnl', 0) <= 0])) if total > wins else 0
            print(f'\n--- 交易统计 ---')
            print(f'  胜率: {wins}/{total} ({wins/total*100:.0f}%)')
            print(f'  盈亏比: {avg_win/avg_loss:.2f}' if avg_loss > 0 else '  盈亏比: N/A')
            print(f'  期望/笔: {np.mean([t["pnl"] for t in self.state["trade_log"]]):.0f}元')

        print(f'\n[4/5] 保存日报')
        existing_dates = {d['date'] for d in self.state['daily_log']}
        if today not in existing_dates:
            daily_record = {
                'date': today,
                'capital': capital,
                'total_equity': round(total_equity, 2),
                'unrealized_pnl': round(total_unrealized_pnl, 2),
                'drawdown': round(dd * 100, 2),
                'return_pct': round((total_equity / INITIAL_CAPITAL - 1) * 100, 2),
                'positions': len(self.state['positions']),
            }
            self.state['daily_log'].append(daily_record)
        self._save_state()

        report_file = os.path.join(TRACKING_DIR, f'daily_{today}.json')
        enriched_positions = {}
        for sym, pos in self.state['positions'].items():
            enriched = dict(pos)
            snap = position_snapshots.get(sym, {})
            enriched['current_price'] = snap.get('current_price', pos['entry_price'])
            enriched['unrealized_pnl'] = snap.get('unrealized_pnl', 0)
            enriched_positions[sym] = enriched

        report = {
            'date': today,
            'version': 'v1.2',
            'account': {
                'capital': capital,
                'total_equity': round(total_equity, 2),
                'unrealized_pnl': round(total_unrealized_pnl, 2),
                'peak_capital': peak,
                'drawdown_pct': round(dd * 100, 2),
                'total_return_pct': round((total_equity / INITIAL_CAPITAL - 1) * 100, 2),
            },
            'positions': enriched_positions,
            'trade_stats': {
                'total_trades': len(self.state['trade_log']),
                'win_rate': round(sum(1 for t in self.state['trade_log'] if t.get('pnl', 0) > 0) / max(len(self.state['trade_log']), 1) * 100, 1),
            },
        }
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f'日报已保存: {report_file}')

        print(f'\n[5/5] 发送日报邮件')
        risk_level = 'normal'
        risk_msg = f'drawdown {dd:.1%} < 20%'
        if dd >= 0.35:
            risk_level = 'level3'
            risk_msg = f'drawdown {dd:.1%} >= 35%, all positions closed'
        elif dd >= 0.27:
            risk_level = 'level2'
            risk_msg = f'drawdown {dd:.1%} >= 27%, no new positions'
        elif dd >= 0.20:
            risk_level = 'level1'
            risk_msg = f'drawdown {dd:.1%} >= 20%, half position size'

        mail_report = {
            'date': today,
            'version': 'v1.2',
            'account': report['account'],
            'positions': enriched_positions,
            'signals': signal_list,
            'trade_stats': {
                'total_trades': len(self.state['trade_log']),
                'win_rate': round(sum(1 for t in self.state['trade_log'] if t.get('pnl', 0) > 0) / max(len(self.state['trade_log']), 1) * 100, 1),
                'avg_pnl': round(np.mean([t['pnl'] for t in self.state['trade_log']]), 0) if self.state['trade_log'] else 0,
            },
            'risk': {'level': risk_level, 'message': risk_msg},
        }
        html = generate_daily_report_html(mail_report)
        subject = f'量化融合日报 {today} | {"有信号" if signal_list else "无信号"} | {risk_level.upper()} | QuantFusion Daily'
        send_email(subject, html)

        return report

    def _risk_check_and_execute(self):
        capital = self.state['capital']
        peak = self.state['peak_capital']
        dd = (peak - capital) / peak if peak > 0 else 0

        if dd >= 0.35:
            print(f'  [XXX] 三级风控: 回撤{dd:.1%}>=35%, 自动平掉所有持仓')
            for sym in list(self.state['positions'].keys()):
                df = self._get_latest_data(sym)
                if df is not None and len(df) > 0:
                    exit_price = df.iloc[-1]['close']
                else:
                    pos = self.state['positions'][sym]
                    exit_price = pos['entry_price']
                self._execute_close(sym, exit_price, f'risk_level3_dd{dd:.0%}')
            self._save_state()
            return

        if dd >= 0.27:
            print(f'  [RED] 二级风控: 回撤{dd:.1%}>=27%, 禁止开新仓(仅允许平仓)')
            self._risk_no_new_positions = True
        elif dd >= 0.20:
            print(f'  [YLW] 一级风控: 回撤{dd:.1%}>=20%, 新仓仓位减半')
            self._risk_half_position = True
        else:
            print(f'  [GRN] 正常: 回撤{dd:.1%}<20%')
            self._risk_no_new_positions = False
            self._risk_half_position = False

        if self.state['trade_log']:
            consecutive_losses = 0
            for t in reversed(self.state['trade_log']):
                if t.get('pnl', 0) < 0:
                    consecutive_losses += 1
                else:
                    break
            if consecutive_losses >= 3:
                print(f'  [WARN] 连亏保护: 连续{consecutive_losses}笔亏损, 暂停开新仓1天')
                self._risk_no_new_positions = True

    def run_realtime_risk(self, interval=60):
        print(f'\n{"=" * 60}')
        print(f'实时风控监控 | v1.2 | 间隔{interval}秒')
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
                    should_close = False
                    close_reason = None

                    if direction == 1:
                        unrealized = (current_price - pos['entry_price']) * self.loader.get_spec(sym).multiplier * pos.get('size', 1)
                        if current_price <= pos['stop_loss']:
                            alert_msg = f'[STOP] {sym} 止损触发! 现价{current_price:.0f}<=止损{pos["stop_loss"]:.0f}'
                            should_close = True
                            close_reason = 'rt_hard_stop'
                        elif current_price >= pos['take_profit']:
                            alert_msg = f'[PROFIT] {sym} 止盈触发! 现价{current_price:.0f}>=止盈{pos["take_profit"]:.0f}'
                            should_close = True
                            close_reason = 'rt_atr_tp'
                        elif current_price <= pos['stop_loss'] * 1.02:
                            alert_msg = f'[WARN] {sym} 接近止损! 现价{current_price:.0f}, 止损{pos["stop_loss"]:.0f}'
                    else:
                        unrealized = (pos['entry_price'] - current_price) * self.loader.get_spec(sym).multiplier * pos.get('size', 1)
                        if current_price >= pos['stop_loss']:
                            alert_msg = f'[STOP] {sym} 止损触发! 现价{current_price:.0f}>=止损{pos["stop_loss"]:.0f}'
                            should_close = True
                            close_reason = 'rt_hard_stop'
                        elif current_price <= pos['take_profit']:
                            alert_msg = f'[PROFIT] {sym} 止盈触发! 现价{current_price:.0f}<=止盈{pos["take_profit"]:.0f}'
                            should_close = True
                            close_reason = 'rt_atr_tp'
                        elif current_price >= pos['stop_loss'] * 0.98:
                            alert_msg = f'[WARN] {sym} 接近止损! 现价{current_price:.0f}, 止损{pos["stop_loss"]:.0f}'

                    if alert_msg:
                        has_alert = True
                        print(f'[{now}] {alert_msg}')
                        with open(alert_log_file, 'a', encoding='utf-8') as f:
                            f.write(f'[{datetime.now().isoformat()}] {alert_msg}\n')

                    if should_close:
                        self._execute_close(sym, current_price, close_reason)
                        self._save_state()

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


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='实盘跟踪系统 v1.2')
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
