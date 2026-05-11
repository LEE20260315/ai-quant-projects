#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from email_sender import send_email, generate_weekly_report_html

TRACKING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracking')
STATE_FILE = os.path.join(TRACKING_DIR, 'tracker_state.json')
INITIAL_CAPITAL = 10000


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def get_week_range():
    today = datetime.now()
    weekday = today.weekday()
    monday = today - timedelta(days=weekday)
    friday = monday + timedelta(days=4)
    return monday.strftime('%Y-%m-%d'), friday.strftime('%Y-%m-%d')


def analyze_trend(daily_log, trade_log):
    signal_count = 0
    for d in daily_log[-7:]:
        sig = d.get('signals_count', 0)
        signal_count += sig

    if signal_count == 0:
        signal_freq = '0/week (quiet)'
    elif signal_count <= 3:
        signal_freq = f'{signal_count}/week (low)'
    elif signal_count <= 7:
        signal_freq = f'{signal_count}/week (normal)'
    else:
        signal_freq = f'{signal_count}/week (active)'

    if not daily_log:
        return {'signal_freq': signal_freq, 'market_regime': 'N/A', 'health': 'N/A'}

    recent_returns = [d.get('return_pct', 0) for d in daily_log[-7:]]
    recent_dd = [d.get('drawdown', 0) for d in daily_log[-7:]]

    avg_return = np.mean(recent_returns) if recent_returns else 0
    max_dd = max(recent_dd) if recent_dd else 0

    if avg_return > 1:
        market_regime = 'Uptrend'
    elif avg_return < -1:
        market_regime = 'Downtrend'
    else:
        market_regime = 'Range-bound'

    if max_dd < 10 and len(trade_log) > 0:
        win_rate = sum(1 for t in trade_log if t.get('pnl', 0) > 0) / len(trade_log)
        if win_rate > 0.5:
            health = 'good'
        else:
            health = 'caution'
    elif max_dd >= 20:
        health = 'danger'
    else:
        health = 'stable'

    return {
        'signal_freq': signal_freq,
        'market_regime': market_regime,
        'health': health,
    }


def generate_key_findings(state, daily_log, trade_log):
    findings = []
    capital = state.get('capital', INITIAL_CAPITAL)
    total_return = (capital / INITIAL_CAPITAL - 1) * 100
    positions = state.get('positions', {})

    if total_return > 5:
        findings.append({'priority': 'high', 'text': f'Weekly return {total_return:+.1f}%, strategy performing well'})
    elif total_return < -5:
        findings.append({'priority': 'high', 'text': f'Weekly return {total_return:+.1f}%, strategy underperforming'})

    if positions:
        findings.append({'priority': 'medium', 'text': f'{len(positions)} open position(s): {", ".join(positions.keys())}'})
    else:
        findings.append({'priority': 'low', 'text': 'No open positions - market in neutral zone'})

    recent_dd = [d.get('drawdown', 0) for d in daily_log[-7:]] if daily_log else [0]
    max_dd = max(recent_dd)
    if max_dd >= 20:
        findings.append({'priority': 'high', 'text': f'Max drawdown reached {max_dd:.1f}%, risk control activated'})
    elif max_dd >= 10:
        findings.append({'priority': 'medium', 'text': f'Drawdown at {max_dd:.1f}%, approaching risk threshold'})

    if trade_log:
        week_trades = [t for t in trade_log if t.get('exit_date', '') >= daily_log[-7].get('date', '') if daily_log]
        if week_trades:
            wins = sum(1 for t in week_trades if t.get('pnl', 0) > 0)
            findings.append({'priority': 'medium', 'text': f'{len(week_trades)} trades this week, win rate {wins/len(week_trades)*100:.0f}%'})

    consecutive_no_signal = 0
    for d in reversed(daily_log):
        if d.get('positions', 0) == 0 and d.get('signals_count', 0) == 0:
            consecutive_no_signal += 1
        else:
            break
    if consecutive_no_signal >= 5:
        findings.append({'priority': 'medium', 'text': f'No signals for {consecutive_no_signal} consecutive days, market may be in low-volatility regime'})

    if not findings:
        findings.append({'priority': 'low', 'text': 'System operating normally, no significant events this week'})

    return findings


def generate_suggestions(state, daily_log, trade_log, trend):
    suggestions = []
    health = trend.get('health', 'stable')
    regime = trend.get('market_regime', 'N/A')

    if regime == 'Range-bound':
        suggestions.append({
            'text': 'Market in range-bound mode: consider widening PctRank entry thresholds (0.20/0.80) to capture more signals',
            'effort': 'low',
        })
    elif regime == 'Downtrend':
        suggestions.append({
            'text': 'Downtrend detected: consider tightening stop-loss (1.2 ATR) or pausing long entries',
            'effort': 'medium',
        })

    if health == 'danger':
        suggestions.append({
            'text': 'High drawdown: review position sizing, consider reducing MAX_POS_PCT from 30% to 20%',
            'effort': 'high',
        })
    elif health == 'caution':
        suggestions.append({
            'text': 'Low win rate: review recent losing trades for pattern, check if trend filter needs adjustment',
            'effort': 'medium',
        })

    if not trade_log:
        suggestions.append({
            'text': 'No trades generated: evaluate if current PctRank thresholds (0.25/0.75) are too strict for current market',
            'effort': 'low',
        })

    consecutive_no_signal = 0
    for d in reversed(daily_log):
        if d.get('positions', 0) == 0:
            consecutive_no_signal += 1
        else:
            break
    if consecutive_no_signal >= 7:
        suggestions.append({
            'text': f'No positions for {consecutive_no_signal} days: consider adding more symbols or adjusting strategy parameters',
            'effort': 'high',
        })

    if not suggestions:
        suggestions.append({
            'text': 'System stable: no immediate optimization needed, continue monitoring',
            'effort': 'none',
        })

    return suggestions


def run_weekly_report():
    print('=' * 60)
    print('Weekly Report Generator')
    print('=' * 60)

    state = load_state()
    if state is None:
        print('ERROR: No state file found')
        return

    week_start, week_end = get_week_range()
    daily_log = state.get('daily_log', [])
    trade_log = state.get('trade_log', [])

    week_dailies = [d for d in daily_log if week_start <= d.get('date', '') <= week_end]
    if not week_dailies:
        week_dailies = daily_log[-7:] if len(daily_log) >= 7 else daily_log

    week_trades = [t for t in trade_log if week_start <= t.get('exit_date', '') <= week_end]

    for d in week_dailies:
        if 'signals_count' not in d:
            d['signals_count'] = 0
        d['signals'] = f"{d.get('signals_count', 0)} signals"

    trend = analyze_trend(week_dailies, trade_log)
    findings = generate_key_findings(state, week_dailies, week_trades)
    suggestions = generate_suggestions(state, week_dailies, trade_log, trend)

    week_data = {
        'week_start': week_start,
        'week_end': week_end,
        'daily_summaries': week_dailies,
        'trade_log': week_trades,
        'key_findings': findings,
        'trend_analysis': trend,
        'suggestions': suggestions,
    }

    html = generate_weekly_report_html(week_data)

    report_file = os.path.join(TRACKING_DIR, f'weekly_{week_start}_{week_end}.json')
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(week_data, f, ensure_ascii=False, indent=2, default=str)
    print(f'Weekly report saved: {report_file}')

    subject = f'量化融合周报 {week_start}~{week_end} | {trend.get("market_regime","N/A")} | {trend.get("health","N/A")} | QuantFusion Weekly'
    send_email(subject, html, attachments=[report_file])


if __name__ == '__main__':
    run_weekly_report()
