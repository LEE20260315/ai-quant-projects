#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.parquet_loader import ParquetLoader
from strategies.quantile_short_term_v2 import OptimizedParams
from portfolio.portfolio_backtest import (
    PortfolioBacktest, PortfolioConfig, PortfolioPosition
)
from fusion.signal_fusion import SignalFusion, FusedSignal


class FusionBacktestEngine:
    def __init__(self, config: PortfolioConfig = None,
                 fusion_enabled: bool = True,
                 sl_tighten_atr: float = 0.3,
                 tp_widen_atr: float = 0.0,
                 hold_extend_days: int = 0,
                 hold_reduce_days: int = 1):
        self.config = config or PortfolioConfig()
        self.fusion_enabled = fusion_enabled
        self.base_engine = PortfolioBacktest(self.config)
        self.loader = ParquetLoader()
        self.sl_tighten_atr = sl_tighten_atr
        self.tp_widen_atr = tp_widen_atr
        self.hold_extend_days = hold_extend_days
        self.hold_reduce_days = hold_reduce_days

        if self.fusion_enabled:
            self.fusion = SignalFusion(
                symbols=[],
                sl_tighten_atr=sl_tighten_atr,
                tp_widen_atr=tp_widen_atr,
                hold_extend_days=hold_extend_days,
                hold_reduce_days=hold_reduce_days,
            )

    def run(self, symbols: List[str], params: OptimizedParams,
            start_date: str = None, end_date: str = None) -> dict:
        sd = start_date or self.config.start_date
        ed = end_date or self.config.end_date

        print('=' * 60)
        print(f'融合回测 | 融合={"ON" if self.fusion_enabled else "OFF"} | '
              f'品种={symbols} | {sd}~{ed}')
        print('=' * 60)

        all_data = self.base_engine.prepare_all_symbols(symbols, params)
        if len(all_data) == 0:
            return {'error': '无有效品种数据'}

        if self.fusion_enabled:
            self.fusion.symbols = symbols
            self.fusion.initialize(sd, ed)

        fusion_trade_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'trade_details_fusion.txt')
        with open(fusion_trade_file, 'w', encoding='utf-8') as f:
            f.write('')

        all_dates = set()
        for df in all_data.values():
            all_dates.update(df['date'].tolist())
        all_dates = sorted(all_dates)

        capital = self.config.initial_capital
        positions: Dict[str, PortfolioPosition] = {}
        trades = []
        equity_curve = []
        fusion_log = []

        for current_date in all_dates:
            for symbol, pos in list(positions.items()):
                if symbol not in all_data:
                    continue
                df = all_data[symbol]
                row_mask = df['date'] == current_date
                if not row_mask.any():
                    continue
                row = df[row_mask].iloc[0]
                exit_reason = None
                exit_price = row['close']

                if pos.direction == 1 and row['low'] <= pos.stop_loss:
                    exit_reason = 'hard_stop'
                    exit_price = pos.stop_loss
                elif pos.direction == -1 and row['high'] >= pos.stop_loss:
                    exit_reason = 'hard_stop'
                    exit_price = pos.stop_loss

                if exit_reason is None:
                    if pos.direction == 1 and row['high'] >= pos.take_profit:
                        exit_reason = 'atr_tp'
                        exit_price = pos.take_profit
                    elif pos.direction == -1 and row['low'] <= pos.take_profit:
                        exit_reason = 'atr_tp'
                        exit_price = pos.take_profit

                if exit_reason is None:
                    hold_days = (current_date - pos.entry_date).days
                    max_hold = getattr(pos, 'max_hold_days', params.max_hold_days)
                    if hold_days >= max_hold:
                        exit_reason = f'timeout_{hold_days}'

                if exit_reason is None:
                    if pos.direction == 1:
                        profit_pct = (row['close'] - pos.entry_price) / pos.entry_price
                    else:
                        profit_pct = (pos.entry_price - row['close']) / pos.entry_price
                    pos.highest_profit_pct = max(pos.highest_profit_pct, profit_pct)
                    if pos.highest_profit_pct >= params.trailing_trigger:
                        if pos.highest_profit_pct > 1.00:
                            trail = params.trailing_pct_high
                        elif pos.highest_profit_pct > 0.50:
                            trail = params.trailing_pct_mid
                        else:
                            trail = params.trailing_pct_low
                        if pos.direction == 1:
                            new_stop = row['close'] * (1 - trail)
                            if new_stop > pos.stop_loss:
                                pos.stop_loss = new_stop
                            if row['low'] <= pos.stop_loss:
                                exit_reason = 'trailing_stop'
                                exit_price = pos.stop_loss
                        else:
                            new_stop = row['close'] * (1 + trail)
                            if new_stop < pos.stop_loss:
                                pos.stop_loss = new_stop
                            if row['high'] >= pos.stop_loss:
                                exit_reason = 'trailing_stop'
                                exit_price = pos.stop_loss

                if exit_reason:
                    spec = self.loader.get_spec(symbol)
                    if pos.direction == 1:
                        pnl = (exit_price - pos.entry_price) * spec.multiplier
                    else:
                        pnl = (pos.entry_price - exit_price) * spec.multiplier
                    cost = (pos.entry_price + exit_price) * spec.multiplier * pos.size * \
                           (self.config.commission_rate + self.config.slippage_rate)
                    net_pnl = pnl * pos.size - cost
                    capital += net_pnl
                    hold_days = (current_date - pos.entry_date).days
                    trades.append({
                        'symbol': symbol,
                        'direction': 'long' if pos.direction == 1 else 'short',
                        'entry_date': pos.entry_date,
                        'exit_date': current_date,
                        'entry_price': pos.entry_price,
                        'exit_price': exit_price,
                        'size': pos.size,
                        'pnl': net_pnl,
                        'hold_days': hold_days,
                        'exit_reason': exit_reason,
                        'capital_after': capital,
                        'fusion_enhancement': getattr(pos, 'fusion_enhancement', 'none'),
                    })
                    with open(fusion_trade_file, 'a', encoding='utf-8') as f:
                        f.write(f"date:{current_date}, symbol:{symbol}, dir:{pos.direction}, "
                                f"entry:{pos.entry_price:.2f}, exit:{exit_price:.2f}, "
                                f"pnl:{net_pnl:.2f}, reason:{exit_reason}, "
                                f"fusion:{getattr(pos, 'fusion_enhancement', 'none')}, "
                                f"capital:{capital:.2f}\n")
                    if self.fusion_enabled and hasattr(pos, 'fusion_strategy'):
                        self.fusion.update_darwin(pos.fusion_strategy, net_pnl)
                        self.fusion.rebalance_darwin()
                    del positions[symbol]

            current_dd, peak_equity, realized_equity = self._calc_dd(capital, equity_curve)
            self.base_engine.position_manager.update_drawdown(current_dd, current_date)
            self.base_engine.volatility_manager.update_equity(realized_equity, current_date)

            if current_dd >= self.config.max_drawdown_stop and len(positions) > 0:
                for symbol, pos in list(positions.items()):
                    df = all_data[symbol]
                    row_mask = df['date'] == current_date
                    if not row_mask.any():
                        continue
                    row = df[row_mask].iloc[0]
                    exit_price = row['close']
                    spec = self.loader.get_spec(symbol)
                    if pos.direction == 1:
                        pnl = (exit_price - pos.entry_price) * spec.multiplier
                    else:
                        pnl = (pos.entry_price - exit_price) * spec.multiplier
                    cost = (pos.entry_price + exit_price) * spec.multiplier * pos.size * \
                           (self.config.commission_rate + self.config.slippage_rate)
                    net_pnl = pnl * pos.size - cost
                    capital += net_pnl
                    trades.append({
                        'symbol': symbol, 'direction': 'long' if pos.direction == 1 else 'short',
                        'entry_date': pos.entry_date, 'exit_date': current_date,
                        'entry_price': pos.entry_price, 'exit_price': exit_price,
                        'size': pos.size, 'pnl': net_pnl,
                        'hold_days': (current_date - pos.entry_date).days,
                        'exit_reason': f'drawdown_{current_dd:.1%}',
                        'capital_after': capital,
                        'fusion_enhancement': getattr(pos, 'fusion_enhancement', 'none'),
                    })
                positions.clear()
                self.base_engine.position_manager.update_drawdown(current_dd, current_date)

            equity_curve.append({'date': current_date, 'capital': capital})

            today_signals = []
            for symbol, df in all_data.items():
                row_mask = df['date'] == current_date
                if not row_mask.any():
                    continue
                row = df[row_mask].iloc[0]
                if row.get('signal_long'):
                    today_signals.append({
                        'symbol': symbol, 'direction': 1,
                        'signal_strength': row['signal_strength'],
                        'margin_needed': row['margin_needed'],
                        'atr': row['atr'], 'close': row['close'],
                    })
                elif row.get('signal_short'):
                    today_signals.append({
                        'symbol': symbol, 'direction': -1,
                        'signal_strength': row['signal_strength'],
                        'margin_needed': row['margin_needed'],
                        'atr': row['atr'], 'close': row['close'],
                    })

            today_signals = [s for s in today_signals if s['symbol'] not in positions]

            if self.fusion_enabled and today_signals:
                for sig in today_signals:
                    fused = self.fusion.fuse(
                        path2_direction=sig['direction'],
                        path2_strength=sig['signal_strength'],
                        symbol=sig['symbol'],
                        date=current_date,
                    )
                    sig['fusion_enhancement'] = fused.enhancement_applied
                    sig['fusion_confidence'] = fused.confidence
                    sig['path1_consensus'] = fused.path1_consensus
                    sig['path1_agreement'] = fused.path1_agreement
                    sig['sl_atr_adj'] = fused.sl_atr_adj
                    sig['tp_atr_adj'] = fused.tp_atr_adj
                    sig['hold_days_adj'] = fused.hold_days_adj

                    if fused.enhancement_applied != 'none':
                        fusion_log.append({
                            'date': current_date, 'symbol': sig['symbol'],
                            'p2_dir': fused.path2_direction,
                            'p1_consensus': fused.path1_consensus,
                            'agreement': round(fused.path1_agreement, 2),
                            'enhancement': fused.enhancement_applied,
                            'sl_adj': round(fused.sl_atr_adj, 2),
                            'tp_adj': round(fused.tp_atr_adj, 2),
                            'hold_adj': fused.hold_days_adj,
                        })

            if self.config.symbol_rotation_enabled:
                for s in today_signals:
                    weight = self.base_engine.symbol_rotation_manager.get_symbol_weight(s['symbol'])
                    s['signal_strength'] = s.get('signal_strength', 0.0) * weight

            if len(today_signals) > 1:
                margins = [s['margin_needed'] for s in today_signals]
                min_m, max_m = min(margins), max(margins)
                for s in today_signals:
                    if max_m > min_m:
                        margin_score = 1 - (s['margin_needed'] - min_m) / (max_m - min_m)
                    else:
                        margin_score = 1.0
                    s['composite_score'] = s['signal_strength'] * 0.6 + margin_score * 0.4
                today_signals.sort(key=lambda x: x['composite_score'], reverse=True)

            if self.base_engine.position_manager.can_trade(current_date):
                max_pos_pct = self.base_engine.position_manager.get_max_position_pct()
                max_total_pct = self.base_engine.position_manager.get_max_total_position_pct()
                if self.config.volatility_target_enabled:
                    vol_adj = self.base_engine.volatility_manager.get_position_adjustment()
                    max_pos_pct *= vol_adj
                    max_total_pct *= vol_adj

                current_total_margin = sum(p.margin_used for p in positions.values())
                max_total_margin = capital * max_total_pct

                for sig in today_signals:
                    if len(positions) >= self.config.max_positions:
                        break
                    symbol = sig['symbol']
                    spec = self.loader.get_spec(symbol)
                    df = all_data[symbol]
                    future_rows = df[df['date'] > current_date]
                    if len(future_rows) == 0:
                        continue
                    next_row = future_rows.iloc[0]
                    exec_price = next_row['open']
                    exec_date = next_row['date']
                    if pd.isna(exec_price):
                        continue

                    margin_needed = sig['margin_needed']
                    if margin_needed > capital * max_pos_pct:
                        margin_needed = capital * max_pos_pct
                    if current_total_margin + margin_needed > max_total_margin:
                        continue

                    size = max(1, int(margin_needed / (exec_price * spec.multiplier * spec.margin_ratio)))
                    actual_margin = exec_price * spec.multiplier * size * spec.margin_ratio
                    if actual_margin > capital * max_pos_pct:
                        size = max(1, int(capital * max_pos_pct / (exec_price * spec.multiplier * spec.margin_ratio)))
                        actual_margin = exec_price * spec.multiplier * size * spec.margin_ratio

                    atr_val = sig['atr']
                    direction = sig['direction']

                    sl_mult = params.atr_stop_mult
                    tp_mult = params.atr_take_mult
                    max_hold = params.max_hold_days

                    if self.fusion_enabled:
                        sl_mult += sig.get('sl_atr_adj', 0.0)
                        tp_mult += sig.get('tp_atr_adj', 0.0)
                        max_hold += sig.get('hold_days_adj', 0)
                        sl_mult = max(0.5, sl_mult)
                        tp_mult = max(0.5, tp_mult)
                        max_hold = max(2, max_hold)

                    if direction == 1:
                        sl = exec_price - atr_val * sl_mult
                        tp = exec_price + atr_val * tp_mult
                    else:
                        sl = exec_price + atr_val * sl_mult
                        tp = exec_price - atr_val * tp_mult

                    pos = PortfolioPosition(
                        symbol=symbol, direction=direction,
                        entry_price=exec_price, entry_date=exec_date,
                        size=size, stop_loss=sl, take_profit=tp,
                        margin_used=actual_margin,
                    )
                    pos.margin_used = actual_margin
                    pos.fusion_enhancement = sig.get('fusion_enhancement', 'none')
                    pos.fusion_strategy = 'deviation'
                    pos.max_hold_days = max_hold
                    positions[symbol] = pos
                    current_total_margin += actual_margin

        result = self._calc_metrics(capital, trades, equity_curve, self.config.initial_capital)
        result['fusion_enabled'] = self.fusion_enabled
        result['fusion_log_count'] = len(fusion_log)
        result['fusion_log_sample'] = fusion_log[:20]
        if self.fusion_enabled:
            result['darwinian_weights'] = self.fusion.darwin.get_weights()
        return result

    def _calc_dd(self, capital, equity_curve):
        realized = capital
        if equity_curve:
            peaks = [p['capital'] for p in equity_curve]
            peak = max(peaks + [realized])
        else:
            peak = max(self.config.initial_capital, realized)
        dd = (peak - realized) / peak if peak > 0 else 0
        return dd, peak, realized

    def _calc_metrics(self, capital, trades, equity_curve, init_capital):
        if not equity_curve:
            return {'error': 'no equity curve'}
        eq_df = pd.DataFrame(equity_curve)
        total_ret = (capital / init_capital - 1) * 100
        years = max((eq_df['date'].max() - eq_df['date'].min()).days / 365.25, 1)
        annual_ret = ((capital / init_capital) ** (1 / years) - 1) * 100
        eq_df['peak'] = eq_df['capital'].cummax()
        eq_df['dd'] = (eq_df['peak'] - eq_df['capital']) / eq_df['peak']
        max_dd = eq_df['dd'].max() * 100
        eq_df['daily_ret'] = eq_df['capital'].pct_change()
        sharpe = eq_df['daily_ret'].mean() / eq_df['daily_ret'].std() * np.sqrt(252) if eq_df['daily_ret'].std() > 0 else 0
        calmar = annual_ret / abs(max_dd) if max_dd != 0 else 0
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t['pnl'] for t in losses)) / len(losses) if losses else 0
        pf = avg_win / avg_loss if avg_loss > 0 else 0
        wr = len(wins) / len(trades) * 100 if trades else 0

        fusion_trades = [t for t in trades if t.get('fusion_enhancement', 'none') != 'none']
        same_dir_trades = [t for t in trades if 'same_dir' in t.get('fusion_enhancement', '')]
        conflict_trades = [t for t in trades if 'conflict' in t.get('fusion_enhancement', '')]

        return {
            'initial_capital': init_capital,
            'final_capital': round(capital, 2),
            'total_return_pct': round(total_ret, 2),
            'annual_return_pct': round(annual_ret, 2),
            'max_drawdown_pct': round(max_dd, 2),
            'sharpe_ratio': round(sharpe, 4),
            'calmar_ratio': round(calmar, 4),
            'total_trades': len(trades),
            'win_rate_pct': round(wr, 2),
            'profit_factor': round(pf, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'fusion_enhanced_trades': len(fusion_trades),
            'same_dir_enhanced': len(same_dir_trades),
            'conflict_adjusted': len(conflict_trades),
            'trades': trades,
        }


def run_comparison(symbols=['TA', 'RM', 'MA']):
    params = OptimizedParams(
        percentile_window=40,
        long_entry_pct=0.25,
        short_entry_pct=0.75,
        atr_stop_mult=1.5,
        atr_take_mult=2.0,
        max_hold_days=7,
        trend_filter_enabled=True,
    )
    config = PortfolioConfig(
        start_date='2020-01-01',
        end_date='2025-12-31',
        dynamic_position_enabled=True,
        volatility_target_enabled=True,
        symbol_rotation_enabled=True,
    )

    print('\n' + '=' * 60)
    print('基线测试: 纯路径2（无融合）')
    print('=' * 60)
    baseline_engine = FusionBacktestEngine(config=config, fusion_enabled=False)
    baseline = baseline_engine.run(symbols, params)

    print('\n' + '=' * 60)
    print('融合测试: 路径2 + 路径1自适应风险管理')
    print('=' * 60)
    fusion_engine = FusionBacktestEngine(config=config, fusion_enabled=True)
    fused = fusion_engine.run(symbols, params)

    print('\n' + '=' * 60)
    print('对比结果')
    print('=' * 60)
    metrics = ['total_return_pct', 'annual_return_pct', 'max_drawdown_pct',
               'sharpe_ratio', 'calmar_ratio', 'total_trades', 'win_rate_pct',
               'profit_factor']
    for m in metrics:
        b_val = baseline.get(m, 'N/A')
        f_val = fused.get(m, 'N/A')
        diff = ''
        if isinstance(b_val, (int, float)) and isinstance(f_val, (int, float)):
            diff = f' ({f_val - b_val:+.2f})'
        print(f'  {m:25s}: 基线={b_val} | 融合={f_val}{diff}')

    print(f'\n  融合增强交易数: {fused.get("fusion_enhanced_trades", 0)}')
    print(f'  同向增强(放宽止盈/延长持仓): {fused.get("same_dir_enhanced", 0)} | '
          f'冲突调整(收紧止损/缩短持仓): {fused.get("conflict_adjusted", 0)}')
    if 'darwinian_weights' in fused:
        print(f'  Darwinian权重: {fused["darwinian_weights"]}')

    output = {
        'timestamp': datetime.now().isoformat(),
        'baseline': {k: v for k, v in baseline.items() if k != 'trades'},
        'fused': {k: v for k, v in fused.items() if k != 'trades'},
        'comparison': {m: {
            'baseline': baseline.get(m), 'fused': fused.get(m),
            'improvement': fused.get(m, 0) - baseline.get(m, 0) if isinstance(baseline.get(m), (int, float)) and isinstance(fused.get(m), (int, float)) else None
        } for m in metrics},
    }
    os.makedirs('results', exist_ok=True)
    with open('results/fusion_comparison.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print('\n结果已保存到 results/fusion_comparison.json')
    return baseline, fused


if __name__ == '__main__':
    run_comparison()
