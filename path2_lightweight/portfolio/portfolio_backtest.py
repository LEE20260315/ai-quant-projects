#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二 v4：组合回测引擎
- 1万元共享账户
- 多品种信号竞争
- 单品种≤50%仓位
- 同时持有≤3品种
- 按信号质量/保证金适配度排序
"""
import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.quantile_short_term_v2 import OptimizedQuantileStrategy, OptimizedParams
from data.parquet_loader import ParquetLoader, LOW_MARGIN_SYMBOLS


# ============================================================
# 组合回测配置
# ============================================================
@dataclass
class PortfolioConfig:
    initial_capital: float = 10000
    max_positions: int = 3               # 最多同时持有3个品种
    max_position_pct: float = 0.50       # 单品种最大仓位50%
    start_date: str = "2020-01-01"
    end_date: str = "2025-12-31"
    commission_rate: float = 0.00015
    slippage_rate: float = 0.0002


@dataclass
class PortfolioPosition:
    symbol: str
    direction: int
    entry_date: pd.Timestamp
    entry_price: float
    size: int
    stop_loss: float
    take_profit: float
    margin_used: float
    highest_profit_pct: float = 0.0


class PortfolioBacktest:
    """
    组合回测引擎
    
    规则:
    1. 所有品种同时产生信号
    2. 按信号强度排序
    3. 优先开仓：信号强 + 保证金低 + 品种历史表现好
    4. 有仓位时最多3个品种
    5. 单品种保证金≤总资金×50%
    6. T+1开盘价执行
    """
    
    def __init__(self, config: PortfolioConfig = None):
        self.config = config or PortfolioConfig()
        self.loader = ParquetLoader()
    
    def prepare_all_symbols(self, symbols: List[str], 
                           params: OptimizedParams) -> Dict[str, pd.DataFrame]:
        """
        准备所有品种的数据和信号
        
        Returns:
            {symbol: DataFrame with signals}
        """
        all_data = {}
        
        for symbol in symbols:
            df = self.loader.load_symbol(symbol, self.config.start_date, self.config.end_date)
            if df is None or len(df) < 100:
                continue
            
            spec = self.loader.get_spec(symbol)
            if spec is None:
                continue
            
            # 计算指标
            df['symbol'] = symbol
            df['ema_fast'] = df['close'].ewm(span=params.ema_fast, adjust=False).mean()
            df['ema_slow'] = df['close'].ewm(span=params.ema_slow, adjust=False).mean()
            
            # RSI
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=params.rsi_period).mean()
            avg_loss = loss.rolling(window=params.rsi_period).mean()
            rs = avg_gain / avg_loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # ATR
            high = df['high']
            low = df['low']
            close = df['close']
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            df['atr'] = true_range.rolling(window=params.atr_period).mean()
            
            # 分位数
            df['pct_rank'] = df['close'].rolling(window=params.percentile_window).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
            )
            
            # 信号
            df['signal_long'] = (
                (df['pct_rank'] < params.long_entry_pct) &
                (df['ema_fast'] > df['ema_slow'])
            )
            df['signal_short'] = (
                (df['pct_rank'] > params.short_entry_pct) &
                (df['rsi'] > params.rsi_overbought)
            )
            
            # 信号强度（用于排序）
            # 做多：分位数越低越强，EMA差值越大越强
            df['signal_strength'] = 0.0
            df.loc[df['signal_long'], 'signal_strength'] = (
                (params.long_entry_pct - df.loc[df['signal_long'], 'pct_rank']) / params.long_entry_pct * 0.5 +
                ((df.loc[df['signal_long'], 'ema_fast'] - df.loc[df['signal_long'], 'ema_slow']) / 
                 df.loc[df['signal_long'], 'ema_slow']).clip(0, 0.1) / 0.1 * 0.5
            )
            df.loc[df['signal_short'], 'signal_strength'] = (
                (df.loc[df['signal_short'], 'pct_rank'] - params.short_entry_pct) / (1 - params.short_entry_pct) * 0.5 +
                ((df.loc[df['signal_short'], 'rsi'] - params.rsi_overbought) / (100 - params.rsi_overbought)) * 0.5
            )
            
            # 保证金需求
            df['margin_needed'] = df['close'] * spec.multiplier * spec.margin_ratio
            
            all_data[symbol] = df
        
        return all_data
    
    def run(self, symbols: List[str], 
            params: OptimizedParams) -> Dict:
        """
        运行组合回测
        
        Returns:
            回测结果
        """
        all_data = self.prepare_all_symbols(symbols, params)
        
        if len(all_data) == 0:
            return {'error': '无有效品种数据'}
        
        # 获取所有日期
        all_dates = set()
        for df in all_data.values():
            all_dates.update(df['date'].tolist())
        all_dates = sorted(all_dates)
        
        # 回测状态
        capital = self.config.initial_capital
        positions: Dict[str, PortfolioPosition] = {}  # symbol -> position
        trades = []
        equity_curve = []
        signal_log = []
        
        for current_date in all_dates:
            # 1. 检查现有持仓的出场条件
            symbols_to_close = []
            
            for symbol, pos in positions.items():
                if symbol not in all_data:
                    continue
                
                df = all_data[symbol]
                row_mask = df['date'] == current_date
                if not row_mask.any():
                    continue
                
                row = df[row_mask].iloc[0]
                current_close = row['close']
                current_high = row['high']
                current_low = row['low']
                
                exit_reason = None
                exit_price = current_close
                
                # 硬止损
                if pos.direction == 1:
                    if current_low <= pos.stop_loss:
                        exit_reason = '硬止损'
                        exit_price = pos.stop_loss * 0.999
                else:
                    if current_high >= pos.stop_loss:
                        exit_reason = '硬止损'
                        exit_price = pos.stop_loss * 1.001
                
                # 止盈
                if exit_reason is None:
                    if pos.direction == 1:
                        if current_high >= pos.take_profit:
                            exit_reason = 'ATR止盈'
                            exit_price = pos.take_profit
                    else:
                        if current_low <= pos.take_profit:
                            exit_reason = 'ATR止盈'
                            exit_price = pos.take_profit
                
                # 超时
                if exit_reason is None:
                    hold_days = (current_date - pos.entry_date).days
                    if hold_days >= params.max_hold_days:
                        exit_reason = f'超时{hold_days}天'
                
                # 移动止损
                if exit_reason is None:
                    if pos.direction == 1:
                        profit_pct = (current_close - pos.entry_price) / pos.entry_price
                    else:
                        profit_pct = (pos.entry_price - current_close) / pos.entry_price
                    
                    pos.highest_profit_pct = max(pos.highest_profit_pct, profit_pct)
                    
                    if pos.highest_profit_pct >= params.trailing_trigger:
                        if pos.highest_profit_pct > 1.00:
                            trail = params.trailing_pct_high
                        elif pos.highest_profit_pct > 0.50:
                            trail = params.trailing_pct_mid
                        else:
                            trail = params.trailing_pct_low
                        
                        if pos.direction == 1:
                            new_stop = current_close * (1 - trail)
                            if new_stop > pos.stop_loss:
                                pos.stop_loss = new_stop
                            if current_low <= pos.stop_loss:
                                exit_reason = '移动止损'
                                exit_price = pos.stop_loss
                        else:
                            new_stop = current_close * (1 + trail)
                            if new_stop < pos.stop_loss:
                                pos.stop_loss = new_stop
                            if current_high >= pos.stop_loss:
                                exit_reason = '移动止损'
                                exit_price = pos.stop_loss
                
                # 执行出场
                if exit_reason:
                    spec = self.loader.get_spec(symbol)
                    if pos.direction == 1:
                        pnl = (exit_price - pos.entry_price) * spec.multiplier
                    else:
                        pnl = (pos.entry_price - exit_price) * spec.multiplier
                    
                    cost = (pos.entry_price + exit_price) * spec.multiplier * \
                           pos.size * (self.config.commission_rate + self.config.slippage_rate)
                    
                    net_pnl = pnl * pos.size - cost
                    capital += net_pnl
                    
                    hold_days = (current_date - pos.entry_date).days
                    
                    trades.append({
                        'symbol': symbol,
                        'direction': '多' if pos.direction == 1 else '空',
                        'entry_date': pos.entry_date,
                        'exit_date': current_date,
                        'entry_price': pos.entry_price,
                        'exit_price': exit_price,
                        'size': pos.size,
                        'pnl': net_pnl,
                        'hold_days': hold_days,
                        'exit_reason': exit_reason,
                        'capital_after': capital,
                    })
                    
                    symbols_to_close.append(symbol)
            
            for s in symbols_to_close:
                del positions[s]
            
            # 2. 收集当天的所有信号
            today_signals = []
            
            for symbol, df in all_data.items():
                row_mask = df['date'] == current_date
                if not row_mask.any():
                    continue
                
                row = df[row_mask].iloc[0]
                
                if row.get('signal_long'):
                    today_signals.append({
                        'symbol': symbol,
                        'direction': 1,
                        'signal_strength': row['signal_strength'],
                        'margin_needed': row['margin_needed'],
                        'atr': row['atr'],
                        'close': row['close'],
                        'open_next': None,  # T+1开盘价
                        'date_next': None,
                    })
                elif row.get('signal_short'):
                    today_signals.append({
                        'symbol': symbol,
                        'direction': -1,
                        'signal_strength': row['signal_strength'],
                        'margin_needed': row['margin_needed'],
                        'atr': row['atr'],
                        'close': row['close'],
                        'open_next': None,
                        'date_next': None,
                    })
            
            # 3. 获取T+1开盘价
            for sig in today_signals:
                symbol = sig['symbol']
                df = all_data[symbol]
                future_rows = df[df['date'] > current_date]
                if len(future_rows) > 0:
                    next_row = future_rows.iloc[0]
                    sig['open_next'] = next_row['open']
                    sig['date_next'] = next_row['date']
                else:
                    sig['open_next'] = sig['close']
                    sig['date_next'] = current_date
            
            # 4. 信号排序和过滤
            # 过滤：已持仓的品种不再开仓
            today_signals = [s for s in today_signals if s['symbol'] not in positions]
            
            # 排序：信号强度降序，保证金需求升序
            # 综合得分 = signal_strength * 0.6 + (1 - margin_rank) * 0.4
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
            
            # 5. 执行开仓（最多到max_positions）
            for sig in today_signals:
                if len(positions) >= self.config.max_positions:
                    break
                
                symbol = sig['symbol']
                exec_price = sig['open_next']
                exec_date = sig['date_next']
                
                if exec_price is None or pd.isna(exec_price):
                    continue
                
                spec = self.loader.get_spec(symbol)
                margin_needed = spec.calc_margin(exec_price)
                
                # 保证金检查：单品种≤50%资金
                if margin_needed > capital * self.config.max_position_pct:
                    continue
                
                # 计算止损止盈
                atr = sig['atr']
                if pd.isna(atr):
                    continue
                
                atr_stop_mult = params.get_atr_stop_mult(symbol)
                stop_distance = max(
                    atr * atr_stop_mult,
                    exec_price * params.min_stop_pct
                )
                stop_distance = min(stop_distance, exec_price * params.max_stop_pct)
                take_distance = atr * params.atr_take_mult
                
                if sig['direction'] == 1:
                    actual_sl = exec_price * (1 - self.config.slippage_rate) - stop_distance
                    actual_tp = exec_price * (1 + self.config.slippage_rate) + take_distance
                else:
                    actual_sl = exec_price * (1 + self.config.slippage_rate) + stop_distance
                    actual_tp = exec_price * (1 - self.config.slippage_rate) - take_distance
                
                positions[symbol] = PortfolioPosition(
                    symbol=symbol,
                    direction=sig['direction'],
                    entry_date=exec_date,
                    entry_price=exec_price,
                    size=1,
                    stop_loss=actual_sl,
                    take_profit=actual_tp,
                    margin_used=margin_needed,
                )
                
                signal_log.append({
                    'date': current_date,
                    'exec_date': exec_date,
                    'symbol': symbol,
                    'direction': '多' if sig['direction'] == 1 else '空',
                    'entry_price': exec_price,
                    'margin_used': margin_needed,
                    'signal_strength': sig['signal_strength'],
                    'capital': capital,
                    'positions_count': len(positions),
                })
            
            # 记录权益
            current_margin = sum(p.margin_used for p in positions.values())
            equity_curve.append({
                'date': current_date,
                'capital': capital,
                'margin_used': current_margin,
                'positions': len(positions),
                'position_symbols': ','.join(positions.keys()),
            })
        
        # 关闭所有剩余持仓（按最后一天收盘价）
        for symbol, pos in list(positions.items()):
            df = all_data[symbol]
            last_row = df.iloc[-1]
            exit_price = last_row['close']
            
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
                'symbol': symbol,
                'direction': '多' if pos.direction == 1 else '空',
                'entry_date': pos.entry_date,
                'exit_date': last_row['date'],
                'entry_price': pos.entry_price,
                'exit_price': exit_price,
                'size': pos.size,
                'pnl': net_pnl,
                'hold_days': (last_row['date'] - pos.entry_date).days,
                'exit_reason': '回测结束',
                'capital_after': capital,
            })
        
        # 统计
        if len(trades) == 0:
            return {'error': '无交易', 'symbols_tested': symbols}
        
        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve)
        signal_df = pd.DataFrame(signal_log) if signal_log else pd.DataFrame()
        
        total_pnl = trades_df['pnl'].sum()
        win_trades = trades_df[trades_df['pnl'] > 0]
        lose_trades = trades_df[trades_df['pnl'] <= 0]
        
        win_rate = len(win_trades) / len(trades_df)
        avg_win = win_trades['pnl'].mean() if len(win_trades) > 0 else 0
        avg_lose = lose_trades['pnl'].mean() if len(lose_trades) > 0 else 0
        profit_factor = abs(avg_win / avg_lose) if avg_lose != 0 else float('inf')
        
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['capital'] - equity_df['peak']) / equity_df['peak']
        max_drawdown = equity_df['drawdown'].min()
        
        days = (pd.to_datetime(self.config.end_date) - pd.to_datetime(self.config.start_date)).days
        years = days / 365.25
        annual_return = (capital / self.config.initial_capital) ** (1 / years) - 1 if years > 0 else 0
        
        daily_returns = equity_df['capital'].pct_change().dropna()
        sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0
        
        # 品种表现分解
        symbol_stats = {}
        for sym in trades_df['symbol'].unique():
            sym_trades = trades_df[trades_df['symbol'] == sym]
            sym_wins = sym_trades[sym_trades['pnl'] > 0]
            symbol_stats[sym] = {
                'trades': len(sym_trades),
                'win_rate': len(sym_wins) / len(sym_trades) * 100 if len(sym_trades) > 0 else 0,
                'total_pnl': sym_trades['pnl'].sum(),
                'avg_pnl': sym_trades['pnl'].mean(),
            }
        
        # 持仓时间分布
        equity_df['utilization_pct'] = equity_df['margin_used'] / equity_df['capital'] * 100
        
        return {
            'initial_capital': self.config.initial_capital,
            'final_capital': capital,
            'total_return_pct': total_pnl / self.config.initial_capital * 100,
            'annual_return_pct': annual_return * 100,
            'total_trades': len(trades_df),
            'win_rate_pct': win_rate * 100,
            'avg_win': avg_win,
            'avg_lose': avg_lose,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe,
            'calmar_ratio': annual_return / abs(max_drawdown) if max_drawdown != 0 else 0,
            'avg_positions': equity_df['positions'].mean(),
            'avg_utilization_pct': equity_df['utilization_pct'].mean(),
            'symbol_stats': symbol_stats,
            'exit_reasons': trades_df['exit_reason'].value_counts().to_dict(),
            'trades_df': trades_df,
            'equity_df': equity_df,
            'signal_log': signal_df,
            'symbols_tested': symbols,
        }


# ============================================================
# 运行
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("路径二 v4：组合回测引擎")
    print("1万元共享账户 | 单品种≤50% | 同时持有≤3品种")
    print("=" * 80)
    
    config = PortfolioConfig(
        start_date="2020-01-01",
        end_date="2025-12-31",
    )
    
    params = OptimizedParams(
        percentile_window=30,
        long_entry_pct=0.35,
        short_entry_pct=0.65,
        atr_stop_mult=1.8,
        atr_take_mult=3.0,
        max_hold_days=7,
        trend_filter_enabled=False,
    )
    
    portfolio = PortfolioBacktest(config)
    
    # 测试品种组合：基于v3严谨研究结果
    # CS(玉米淀粉)和MA(甲醇)是唯二通过严谨检验的品种
    test_symbols = ['CS', 'MA']
    
    print(f"\n测试品种: {', '.join(test_symbols)}")
    print(f"时间: {config.start_date} ~ {config.end_date}")
    print(f"初始资金: {config.initial_capital:,.0f}元")
    
    result = portfolio.run(test_symbols, params)
    
    if 'error' in result:
        print(f"\n错误: {result['error']}")
    else:
        print(f"\n{'=' * 60}")
        print("组合回测结果")
        print(f"{'=' * 60}")
        print(f"初始资金:     {result['initial_capital']:>12,.0f}元")
        print(f"期末资金:     {result['final_capital']:>12,.0f}元")
        print(f"总收益率:     {result['total_return_pct']:>12.2f}%")
        print(f"年化收益率:   {result['annual_return_pct']:>12.2f}%")
        print(f"交易次数:     {result['total_trades']:>12d}笔")
        print(f"胜率:         {result['win_rate_pct']:>12.1f}%")
        print(f"盈亏比:       {result['profit_factor']:>12.2f}")
        print(f"最大回撤:     {result['max_drawdown_pct']:>12.2f}%")
        print(f"夏普比率:     {result['sharpe_ratio']:>12.2f}")
        print(f"Calmar比率:   {result['calmar_ratio']:>12.2f}")
        print(f"平均持仓数:   {result['avg_positions']:>12.1f}")
        print(f"平均资金利用率: {result['avg_utilization_pct']:>11.1f}%")
        
        print(f"\n品种表现:")
        for sym, stats in result['symbol_stats'].items():
            print(f"  {sym:4s} | {stats['trades']:3d}笔 | 胜率:{stats['win_rate']:5.1f}% | "
                  f"盈亏:{stats['total_pnl']:+8.0f}元 | 平均:{stats['avg_pnl']:+7.0f}元")
        
        print(f"\n出场原因:")
        for reason, count in result['exit_reasons'].items():
            print(f"  {reason}: {count}次")
    
    print("\n" + "=" * 80)
