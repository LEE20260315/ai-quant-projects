#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二：轻量级分位数短线系统
核心策略 - 纯期货单边分位数交易

策略逻辑:
1. 枯水蓄势：40日分位数 < 0.30 且 EMA17 > EMA48 → 做多
2. 汛期反转：40日分位数 > 0.70 且 RSI > 70 → 做空
3. ATR自适应止损止盈
4. 7天超时平仓
5. 移动止损（盈利>1%启动）
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# 导入数据加载器
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.parquet_loader import (
    ParquetLoader, calc_ema, calc_atr, calc_rsi, 
    calc_percentile_rank, calc_ma, LOW_MARGIN_SYMBOLS
)


# ============================================================
# 策略参数（可调）
# ============================================================
@dataclass
class StrategyParams:
    """策略参数"""
    # 分位数
    percentile_window: int = 40           # 分位数计算窗口
    long_entry_pct: float = 0.30          # 做多入场分位数阈值（枯水）
    short_entry_pct: float = 0.70         # 做空入场分位数阈值（汛期）
    
    # 趋势确认
    ema_fast: int = 17                    # 快EMA
    ema_slow: int = 48                    # 慢EMA
    rsi_period: int = 14                  # RSI周期
    rsi_overbought: float = 70            # RSI超买阈值（做空确认）
    rsi_oversold: float = 30              # RSI超卖阈值（做多确认）
    
    # 止损止盈
    atr_period: int = 14                  # ATR周期
    atr_stop_mult: float = 1.2            # ATR止损倍数
    atr_take_mult: float = 2.0            # ATR止盈倍数
    min_stop_pct: float = 0.008           # 最小止损 0.8%
    max_stop_pct: float = 0.035           # 最大止损 3.5%
    
    # 移动止损
    trailing_trigger: float = 0.01        # 盈利1%启动移动止损
    trailing_pct_low: float = 0.10        # 盈利<50%时回撤10%
    trailing_pct_mid: float = 0.15        # 盈利50-100%时回撤15%
    trailing_pct_high: float = 0.25       # 盈利>100%时回撤25%
    
    # 超时平仓
    max_hold_days: int = 7                # 最大持仓天数
    
    # 交易成本
    commission_rate: float = 0.00015      # 手续费 万1.5
    slippage_rate: float = 0.0002         # 滑点 万2


# ============================================================
# 信号和持仓定义
# ============================================================
class SignalType(Enum):
    LONG = 1
    SHORT = -1
    CLOSE = 0


@dataclass
class Signal:
    """交易信号"""
    date: pd.Timestamp
    symbol: str
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    atr_value: float
    reason: str


@dataclass
class Position:
    """持仓"""
    symbol: str
    direction: int            # 1=多, -1=空
    entry_date: pd.Timestamp
    entry_price: float
    size: int                 # 手数（固定1手）
    stop_loss: float
    take_profit: float
    atr_at_entry: float
    highest_profit_pct: float = 0.0   # 最高盈利百分比（用于移动止损）
    
    def update_trailing_stop(self, current_price: float) -> float:
        """
        更新移动止损价格
        
        Returns:
            新的止损价格
        """
        if self.direction == 1:  # 多头
            profit_pct = (current_price - self.entry_price) / self.entry_price
        else:  # 空头
            profit_pct = (self.entry_price - current_price) / self.entry_price
        
        # 更新最高盈利
        self.highest_profit_pct = max(self.highest_profit_pct, profit_pct)
        
        # 未达到触发条件，不移动
        if self.highest_profit_pct < trailing_trigger:
            return self.stop_loss
        
        # 根据盈利幅度确定回撤比例
        if self.highest_profit_pct > 1.00:
            trail = trailing_pct_high
        elif self.highest_profit_pct > 0.50:
            trail = trailing_pct_mid
        else:
            trail = trailing_pct_low
        
        # 计算新的移动止损价
        if self.direction == 1:
            new_stop = current_price * (1 - trail)
            return max(self.stop_loss, new_stop)  # 只上移，不下移
        else:
            new_stop = current_price * (1 + trail)
            return min(self.stop_loss, new_stop)  # 只下移，不上移


# 从StrategyParams获取移动止损参数
trailing_trigger = 0.01
trailing_pct_low = 0.10
trailing_pct_mid = 0.15
trailing_pct_high = 0.25


# ============================================================
# 核心策略引擎
# ============================================================
class QuantileShortTermStrategy:
    """
    分位数短线策略
    
    纯期货单边交易，分位数入场，ATR止损，移动止损，超时平仓
    """
    
    def __init__(self, params: StrategyParams = None):
        self.params = params or StrategyParams()
        self.loader = ParquetLoader()
        
        # 更新移动止损参数
        global trailing_trigger, trailing_pct_low, trailing_pct_mid, trailing_pct_high
        trailing_trigger = self.params.trailing_trigger
        trailing_pct_low = self.params.trailing_pct_low
        trailing_pct_mid = self.params.trailing_pct_mid
        trailing_pct_high = self.params.trailing_pct_high
    
    def prepare_data(self, symbol: str, 
                     start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        准备策略所需的所有指标数据
        
        Returns:
            DataFrame with additional columns: 
            ema_fast, ema_slow, rsi, atr, percentile_rank, 
            signal_long, signal_short
        """
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < 100:
            return None
        
        # 计算技术指标
        df['ema_fast'] = calc_ema(df['close'], self.params.ema_fast)
        df['ema_slow'] = calc_ema(df['close'], self.params.ema_slow)
        df['rsi'] = calc_rsi(df['close'], self.params.rsi_period)
        df['atr'] = calc_atr(df, self.params.atr_period)
        df['pct_rank'] = calc_percentile_rank(df['close'], self.params.percentile_window)
        
        # 标记信号
        # 做多信号：分位数 < long_entry_pct 且 EMA快 > EMA慢 且 RSI < 超卖
        df['signal_long'] = (
            (df['pct_rank'] < self.params.long_entry_pct) &
            (df['ema_fast'] > df['ema_slow']) &
            (df['rsi'] < self.params.rsi_oversold)
        )
        
        # 做空信号：分位数 > short_entry_pct 且 RSI > 超买
        df['signal_short'] = (
            (df['pct_rank'] > self.params.short_entry_pct) &
            (df['rsi'] > self.params.rsi_overbought)
        )
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        从预处理的数据中生成交易信号
        
        Returns:
            List of Signal
        """
        signals = []
        
        for i, row in df.iterrows():
            if pd.isna(row.get('atr')) or pd.isna(row.get('close')):
                continue
            
            atr = row['atr']
            close = row['close']
            
            # 计算止损止盈
            stop_distance = max(
                atr * self.params.atr_stop_mult,
                close * self.params.min_stop_pct
            )
            stop_distance = min(stop_distance, close * self.params.max_stop_pct)
            
            take_distance = atr * self.params.atr_take_mult
            
            if row.get('signal_long'):
                signals.append(Signal(
                    date=row['date'],
                    symbol=row.get('symbol', 'unknown'),
                    signal_type=SignalType.LONG,
                    entry_price=close,
                    stop_loss=close - stop_distance,
                    take_profit=close + take_distance,
                    atr_value=atr,
                    reason=f"枯水蓄势: pct={row['pct_rank']:.2f}, "
                           f"ema_fast={row['ema_fast']:.1f}>{row['ema_slow']:.1f}, "
                           f"rsi={row['rsi']:.1f}"
                ))
            
            elif row.get('signal_short'):
                signals.append(Signal(
                    date=row['date'],
                    symbol=row.get('symbol', 'unknown'),
                    signal_type=SignalType.SHORT,
                    entry_price=close,
                    stop_loss=close + stop_distance,
                    take_profit=close - take_distance,
                    atr_value=atr,
                    reason=f"汛期反转: pct={row['pct_rank']:.2f}, "
                           f"rsi={row['rsi']:.1f}"
                ))
        
        return signals
    
    def backtest_single_symbol(self, symbol: str,
                               start_date: str, end_date: str,
                               initial_capital: float = 10000) -> Dict:
        """
        对单个品种进行回测
        
        Returns:
            回测结果字典
        """
        spec = self.loader.get_spec(symbol)
        if spec is None:
            return {'error': f'品种{symbol}规格未知'}
        
        df = self.prepare_data(symbol, start_date, end_date)
        if df is None:
            return {'error': f'品种{symbol}数据不足'}
        
        signals = self.generate_signals(df)
        
        # 回测执行
        capital = initial_capital
        position: Optional[Position] = None
        trades = []
        equity_curve = []
        
        for i, row in df.iterrows():
            current_date = row['date']
            current_price = row['close']
            
            # 如果有持仓，检查出场条件
            if position is not None:
                exit_reason = None
                exit_price = current_price
                
                # 1. 硬止损
                if position.direction == 1:
                    if current_price <= position.stop_loss:
                        exit_reason = '硬止损'
                else:
                    if current_price >= position.stop_loss:
                        exit_reason = '硬止损'
                
                # 2. 止盈
                if exit_reason is None:
                    if position.direction == 1:
                        if current_price >= position.take_profit:
                            exit_reason = 'ATR止盈'
                    else:
                        if current_price <= position.take_profit:
                            exit_reason = 'ATR止盈'
                
                # 3. 超时平仓
                if exit_reason is None:
                    hold_days = (current_date - position.entry_date).days
                    if hold_days >= self.params.max_hold_days:
                        exit_reason = f'超时{hold_days}天'
                
                # 4. 移动止损
                if exit_reason is None:
                    new_stop = position.update_trailing_stop(current_price)
                    if new_stop != position.stop_loss:
                        position.stop_loss = new_stop
                        # 检查是否触发新的移动止损
                        if position.direction == 1:
                            if current_price <= position.stop_loss:
                                exit_reason = '移动止损'
                        else:
                            if current_price >= position.stop_loss:
                                exit_reason = '移动止损'
                
                # 执行出场
                if exit_reason:
                    # 计算盈亏（含手续费和滑点）
                    if position.direction == 1:
                        pnl_per_contract = (exit_price - position.entry_price) * spec.multiplier
                    else:
                        pnl_per_contract = (position.entry_price - exit_price) * spec.multiplier
                    
                    # 交易成本
                    cost = (position.entry_price + exit_price) * spec.multiplier * \
                           position.size * (self.params.commission_rate + self.params.slippage_rate)
                    
                    net_pnl = pnl_per_contract * position.size - cost
                    capital += net_pnl
                    
                    hold_days = (current_date - position.entry_date).days
                    
                    trades.append({
                        'symbol': symbol,
                        'direction': '多' if position.direction == 1 else '空',
                        'entry_date': position.entry_date,
                        'exit_date': current_date,
                        'entry_price': position.entry_price,
                        'exit_price': exit_price,
                        'size': position.size,
                        'pnl': net_pnl,
                        'hold_days': hold_days,
                        'exit_reason': exit_reason,
                        'capital_after': capital,
                    })
                    
                    position = None
            
            # 如果没有持仓，检查入场信号
            if position is None:
                # 查找今天的信号
                today_signals = [s for s in signals if s.date == current_date]
                for sig in today_signals:
                    # T+1执行：用下一天的开盘价
                    if i + 1 < len(df):
                        next_row = df.iloc[i + 1]
                        exec_price = next_row['open']
                        exec_date = next_row['date']
                    else:
                        exec_price = current_price
                        exec_date = current_date
                    
                    # 检查保证金是否足够
                    margin_needed = spec.calc_margin(exec_price)
                    if margin_needed > capital * 0.35:  # 保证金不超过35%资金
                        continue
                    
                    # 计算实际止损止盈（考虑滑点）
                    if sig.signal_type == SignalType.LONG:
                        actual_sl = exec_price * (1 - self.params.slippage_rate) - \
                                   (sig.stop_loss - sig.entry_price) / sig.entry_price * exec_price
                        actual_tp = exec_price * (1 + self.params.slippage_rate) + \
                                   (sig.take_profit - sig.entry_price) / sig.entry_price * exec_price
                    else:
                        actual_sl = exec_price * (1 + self.params.slippage_rate) + \
                                   (sig.stop_loss - sig.entry_price) / sig.entry_price * exec_price
                        actual_tp = exec_price * (1 - self.params.slippage_rate) - \
                                   (sig.take_profit - sig.entry_price) / sig.entry_price * exec_price
                    
                    position = Position(
                        symbol=symbol,
                        direction=1 if sig.signal_type == SignalType.LONG else -1,
                        entry_date=exec_date,
                        entry_price=exec_price,
                        size=1,
                        stop_loss=actual_sl,
                        take_profit=actual_tp,
                        atr_at_entry=sig.atr_value,
                    )
                    break
            
            # 记录权益曲线
            equity_curve.append({
                'date': current_date,
                'capital': capital,
                'position_value': position.entry_price * spec.multiplier if position else 0,
            })
        
        # 回测统计
        if len(trades) == 0:
            return {
                'symbol': symbol,
                'total_trades': 0,
                'error': '无交易',
            }
        
        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve)
        
        total_pnl = trades_df['pnl'].sum()
        win_trades = trades_df[trades_df['pnl'] > 0]
        lose_trades = trades_df[trades_df['pnl'] <= 0]
        
        win_rate = len(win_trades) / len(trades_df) if len(trades_df) > 0 else 0
        avg_win = win_trades['pnl'].mean() if len(win_trades) > 0 else 0
        avg_lose = lose_trades['pnl'].mean() if len(lose_trades) > 0 else 0
        profit_factor = abs(avg_win / avg_lose) if avg_lose != 0 else float('inf')
        
        # 最大回撤
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['capital'] - equity_df['peak']) / equity_df['peak']
        max_drawdown = equity_df['drawdown'].min()
        
        # 年化收益率
        days = (df['date'].max() - df['date'].min()).days
        years = days / 365.25
        annual_return = (capital / initial_capital) ** (1 / years) - 1 if years > 0 else 0
        
        # 夏普比率（简化）
        daily_returns = equity_df['capital'].pct_change().dropna()
        sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0
        
        # 出场原因统计
        exit_reasons = trades_df['exit_reason'].value_counts().to_dict()
        
        return {
            'symbol': symbol,
            'initial_capital': initial_capital,
            'final_capital': capital,
            'total_return_pct': total_pnl / initial_capital * 100,
            'annual_return_pct': annual_return * 100,
            'total_trades': len(trades_df),
            'win_trades': len(win_trades),
            'lose_trades': len(lose_trades),
            'win_rate_pct': win_rate * 100,
            'avg_win': avg_win,
            'avg_lose': avg_lose,
            'profit_factor': profit_factor,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe,
            'calmar_ratio': annual_return / abs(max_drawdown) if max_drawdown != 0 else 0,
            'exit_reasons': exit_reasons,
            'trades_df': trades_df,
            'equity_df': equity_df,
        }


# ============================================================
# 快速测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("路径二：分位数短线策略 - 单品种测试")
    print("=" * 60)
    
    strategy = QuantileShortTermStrategy()
    
    # 测试螺纹钢
    result = strategy.backtest_single_symbol(
        symbol="RB",
        start_date="2024-01-01",
        end_date="2025-12-31",
        initial_capital=10000,
    )
    
    if 'error' in result and result['error'] == '无交易':
        print("无交易信号")
    elif 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"\n品种: {result['symbol']}")
        print(f"初始资金: {result['initial_capital']:,.0f}元")
        print(f"期末资金: {result['final_capital']:,.0f}元")
        print(f"总收益率: {result['total_return_pct']:.2f}%")
        print(f"年化收益率: {result['annual_return_pct']:.2f}%")
        print(f"交易次数: {result['total_trades']}")
        print(f"胜率: {result['win_rate_pct']:.1f}%")
        print(f"盈亏比: {result['profit_factor']:.2f}")
        print(f"最大回撤: {result['max_drawdown_pct']:.2f}%")
        print(f"夏普比率: {result['sharpe_ratio']:.2f}")
        print(f"\n出场原因:")
        for reason, count in result['exit_reasons'].items():
            print(f"  {reason}: {count}次")
    
    print("\n" + "=" * 60)
