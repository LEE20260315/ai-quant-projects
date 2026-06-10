#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from dataclasses import dataclass

from data.data_loader import ParquetLoader, calc_atr, FuturesSpec
from strategies.deviation_signal import DeviationSignal, DeviationParams
from strategies.momentum_signal import MomentumSignal, MomentumParams
from strategies.mean_revert_signal import MeanRevertSignal, MeanRevertParams
from strategies.volatility_signal import VolatilitySignal, VolatilityParams
from core.darwinian_weights import DarwinianWeightManager
from execution.guard_pipeline import GuardPipeline, GuardConfig


@dataclass
class PortfolioPosition:
    symbol: str
    direction: int
    entry_price: float
    entry_date: pd.Timestamp
    size: int
    stop_loss: float
    take_profit: float
    highest_profit_pct: float = 0.0
    strategy_name: str = ''


class Path1BacktestEngine:
    def __init__(self, initial_capital=10000,
                 commission_rate=0.00015,
                 slippage_rate=0.0002):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.loader = ParquetLoader()
        self.strategies = {}
        self._init_strategies()

    def _init_strategies(self):
        self.strategies['deviation'] = DeviationSignal(params=DeviationParams(), loader=self.loader)
        self.strategies['momentum'] = MomentumSignal(params=MomentumParams(), loader=self.loader)
        self.strategies['mean_revert'] = MeanRevertSignal(params=MeanRevertParams(), loader=self.loader)
        self.strategies['volatility'] = VolatilitySignal(params=VolatilityParams(), loader=self.loader)

    def run(self, symbols: list, start_date='2020-01-01', end_date='2025-12-31') -> dict:
        print('=' * 60)
        print('路径一：AI增强多策略系统 - 回测引擎')
        print(f'品种: {symbols} | 日期: {start_date} ~ {end_date}')
        print('=' * 60)

        all_data = {}
        for sym in symbols:
            df = self.loader.load_symbol(sym, start_date, end_date)
            if df is not None and len(df) > 200:
                all_data[sym] = df
                df['atr'] = calc_atr(df, 14)

        if not all_data:
            return {'error': '无有效数据'}

        dir_cols = {'deviation': 'dev_direction', 'momentum': 'mom_direction',
                    'mean_revert': 'mr_direction', 'volatility': 'vol_direction'}
        str_cols = {'deviation': 'dev_strength', 'momentum': 'mom_strength',
                    'mean_revert': 'mr_strength', 'volatility': 'vol_strength'}

        print('预计算各策略指标...')
        prepared_data = {}
        for sym in symbols:
            if sym not in all_data:
                continue
            prepared_data[sym] = {}
            for sname, strat in self.strategies.items():
                try:
                    df_prep = strat.prepare_data(sym, start_date, end_date)
                    if df_prep is not None and len(df_prep) > 0:
                        df_prep = strat.generate_daily_signal(df_prep)
                        prepared_data[sym][sname] = df_prep
                        dir_col = dir_cols.get(sname, f'{sname}_direction')
                        sig_count = (df_prep[dir_col] != 0).sum()
                        print(f'  {sym}/{sname}: {len(df_prep)}行, {sig_count}个信号')
                    else:
                        prepared_data[sym][sname] = None
                except Exception as e:
                    print(f'  {sym}/{sname}: 准备失败 - {e}')
                    prepared_data[sym][sname] = None

        all_dates = sorted(set().union(*[set(d['date']) for d in all_data.values()]))
        capital = self.initial_capital
        positions = {}
        trades = []
        equity_curve = []

        darwin = DarwinianWeightManager(list(self.strategies.keys()))
        guard = GuardPipeline(GuardConfig(max_positions=3, max_drawdown_pct=0.30))

        for date in all_dates:
            guard.update_capital(capital)
            equity_curve.append({'date': date, 'capital': capital})

            for sym, pos in list(positions.items()):
                if sym not in all_data:
                    continue
                row = all_data[sym][all_data[sym]['date'] == date]
                if row.empty:
                    continue
                row = row.iloc[0]

                exit_reason = None
                exit_price = row['close']
                if pos.direction == 1 and row['low'] <= pos.stop_loss:
                    exit_reason = 'stop_loss'
                    exit_price = pos.stop_loss
                elif pos.direction == -1 and row['high'] >= pos.stop_loss:
                    exit_reason = 'stop_loss'
                    exit_price = pos.stop_loss
                elif pos.direction == 1 and row['high'] >= pos.take_profit:
                    exit_reason = 'take_profit'
                    exit_price = pos.take_profit
                elif pos.direction == -1 and row['low'] <= pos.take_profit:
                    exit_reason = 'take_profit'
                    exit_price = pos.take_profit
                else:
                    hold_days = (date - pos.entry_date).days
                    if hold_days >= 10:
                        exit_reason = f'timeout_{hold_days}'

                if exit_reason:
                    spec = self.loader.get_spec(sym)
                    pnl = ((exit_price - pos.entry_price) * pos.direction *
                           spec.multiplier * pos.size)
                    cost = ((pos.entry_price + exit_price) * spec.multiplier *
                            pos.size * (self.commission_rate + self.slippage_rate))
                    net_pnl = pnl - cost
                    capital += net_pnl
                    trades.append({
                        'symbol': sym, 'direction': pos.direction,
                        'entry_date': pos.entry_date, 'exit_date': date,
                        'entry_price': pos.entry_price, 'exit_price': exit_price,
                        'size': pos.size, 'pnl': net_pnl,
                        'hold_days': (date - pos.entry_date).days,
                        'exit_reason': exit_reason, 'strategy': pos.strategy_name,
                    })
                    darwin.update_performance(pos.strategy_name, net_pnl)
                    guard.remove_position(sym)
                    del positions[sym]

            weights = darwin.rebalance_weights()
            for sym in symbols:
                if sym in positions or sym not in all_data:
                    continue
                row = all_data[sym][all_data[sym]['date'] == date]
                if row.empty:
                    continue
                row = row.iloc[0]

                daily_signals = {}
                for sname in self.strategies:
                    df_prep = prepared_data.get(sym, {}).get(sname)
                    if df_prep is None:
                        daily_signals[sname] = {'direction': 0, 'strength': 0.0}
                        continue
                    sig_row = df_prep[df_prep['date'] == date]
                    if sig_row.empty:
                        daily_signals[sname] = {'direction': 0, 'strength': 0.0}
                        continue
                    r = sig_row.iloc[0]
                    dcol = dir_cols.get(sname, f'{sname}_direction')
                    scol = str_cols.get(sname, f'{sname}_strength')
                    daily_signals[sname] = {
                        'direction': int(r.get(dcol, 0)) if pd.notna(r.get(dcol)) else 0,
                        'strength': float(r.get(scol, 0.0)) if pd.notna(r.get(scol)) else 0.0,
                    }

                final_direction, final_strength = darwin.get_combined_signal(daily_signals)
                if final_direction != 0 and final_strength > 0.05:
                    spec = self.loader.get_spec(sym)
                    atr_val = row.get('atr', spec.multiplier * 50)
                    if pd.isna(atr_val):
                        atr_val = row['close'] * 0.03

                    # T+1 开盘价执行: 使用次日开盘价作为入场价
                    date_idx = all_dates.index(date) if date in all_dates else -1
                    if date_idx >= 0 and date_idx + 1 < len(all_dates):
                        next_date = all_dates[date_idx + 1]
                        next_row = all_data[sym][all_data[sym]['date'] == next_date]
                        if not next_row.empty:
                            entry_price = float(next_row.iloc[0]['open'])
                        else:
                            entry_price = row['close']
                    else:
                        entry_price = row['close']

                    position_value = capital * min(0.25, final_strength)
                    size = max(1, int(position_value / (entry_price * spec.multiplier)))
                    margin_needed = entry_price * spec.multiplier * size * spec.margin_ratio
                    can_open, checks = guard.can_open(sym, final_direction, capital, margin_needed)
                    if can_open:
                        atr_stop_mult = 1.8
                        atr_take_mult = 2.5
                        if final_direction == 1:
                            sl = entry_price - atr_val * atr_stop_mult
                            tp = entry_price + atr_val * atr_take_mult
                        else:
                            sl = entry_price + atr_val * atr_stop_mult
                            tp = entry_price - atr_val * atr_take_mult
                        best_strategy = max(daily_signals, key=lambda k: daily_signals[k]['strength'])
                        positions[sym] = PortfolioPosition(
                            symbol=sym, direction=final_direction,
                            entry_price=entry_price, entry_date=date,
                            size=size, stop_loss=sl, take_profit=tp,
                            strategy_name=best_strategy,
                        )
                        guard.add_position(sym, final_direction, entry_price, size)

        result = self._calculate_metrics(capital, trades, equity_curve, self.initial_capital)
        output = {
            **result,
            'symbols': symbols,
            'start_date': start_date,
            'end_date': end_date,
            'trades': trades,
            'final_weights': darwin.get_weights(),
            'strategy_performances': {
                n: {'total_pnl': p.total_pnl, 'trades': p.total_trades,
                    'win_rate': p.win_rate, 'sharpe': p.sharpe, 'weight': p.weight}
                for n, p in darwin.performances.items()
            },
        }
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs('results', exist_ok=True)
        with open(f'results/path1_backtest_{ts}.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        return output

    def _calculate_metrics(self, capital, trades, equity_curve, init_capital):
        if not equity_curve:
            return {'error': '无权益曲线'}
        eq_df = pd.DataFrame(equity_curve)
        total_return_pct = (capital / init_capital - 1) * 100
        years = max((eq_df['date'].max() - eq_df['date'].min()).days / 365.25, 1)
        annual_return_pct = ((capital / init_capital) ** (1 / years) - 1) * 100
        eq_df['peak'] = eq_df['capital'].cummax()
        eq_df['dd'] = (eq_df['peak'] - eq_df['capital']) / eq_df['peak']
        max_dd = eq_df['dd'].max() * 100
        eq_df['daily_ret'] = eq_df['capital'].pct_change()
        sharpe = eq_df['daily_ret'].mean() / eq_df['daily_ret'].std() * np.sqrt(252) if eq_df['daily_ret'].std() > 0 else 0
        calmar = annual_return_pct / abs(max_dd) if max_dd != 0 else 0
        win_trades = [t for t in trades if t['pnl'] > 0]
        loss_trades = [t for t in trades if t['pnl'] <= 0]
        avg_win = sum(t['pnl'] for t in win_trades) / len(win_trades) if win_trades else 0
        avg_loss = abs(sum(t['pnl'] for t in loss_trades)) / len(loss_trades) if loss_trades else 0
        pf = avg_win / avg_loss if avg_loss > 0 else 0
        wr = len(win_trades) / len(trades) * 100 if trades else 0
        return {
            'initial_capital': init_capital,
            'final_capital': round(capital, 2),
            'total_return_pct': round(total_return_pct, 2),
            'annual_return_pct': round(annual_return_pct, 2),
            'max_drawdown_pct': round(max_dd, 2),
            'sharpe_ratio': round(sharpe, 4),
            'calmar_ratio': round(calmar, 4),
            'total_trades': len(trades),
            'win_rate_pct': round(wr, 2),
            'profit_factor': round(pf, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
        }


if __name__ == '__main__':
    engine = Path1BacktestEngine(initial_capital=10000)
    result = engine.run(['TA', 'RM', 'MA'], start_date='2020-01-01', end_date='2025-12-31')

    print('\n' + '=' * 60)
    print('回测结果')
    print('=' * 60)
    if 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"初始资金:   {result['initial_capital']:,.0f}元")
        print(f"期末资金:   {result['final_capital']:,.0f}元")
        print(f"总收益率:   {result['total_return_pct']:+.2f}%")
        print(f"年化收益:   {result['annual_return_pct']:+.2f}%")
        print(f"最大回撤:   {result['max_drawdown_pct']:.2f}%")
        print(f"夏普比率:   {result['sharpe_ratio']:.4f}")
        print(f"Calmar比率: {result['calmar_ratio']:.4f}")
        print(f"交易次数:   {result['total_trades']}笔")
        print(f"胜率:       {result['win_rate_pct']:.1f}%")
        print(f"盈亏比:     {result['profit_factor']:.2f}")

        print('\nDarwinian权重:')
        for name, w in result.get('final_weights', {}).items():
            print(f"  {name}: {w:.2f}")

        print('\n各策略表现:')
        for name, perf in result.get('strategy_performances', {}).items():
            print(f"  {name}: 盈亏{perf['total_pnl']:+.0f}元 | "
                  f"{perf['trades']}笔 | 胜率{perf['win_rate']:.1%} | "
                  f"夏普{perf['sharpe']:.2f} | 权重{perf['weight']:.2f}")
