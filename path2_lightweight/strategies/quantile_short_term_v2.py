#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二 v2：轻量级分位数短线系统 - 优化版
核心改进（基于v1诊断结果）：

1. ATR止损放宽：1.2x → 1.8x（蒙特卡罗最优区间）
2. 移动止损触发：1% → 3%（避免过早触发）
3. 做多信号放宽：去掉RSI<30硬性约束
4. 趋势过滤器：200日均线过滤逆势信号
5. 波动率自适应止损：高波动品种更大止损倍数
6. 超时平仓：7天 → 10天（给交易更多时间）
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.parquet_loader import (
    ParquetLoader, calc_ema, calc_atr, calc_rsi,
    calc_percentile_rank, calc_ma, LOW_MARGIN_SYMBOLS
)


# ============================================================
# 优化版策略参数
# ============================================================
@dataclass
class OptimizedParams:
    """优化版策略参数（基于v1诊断）"""
    # 分位数
    percentile_window: int = 40
    long_entry_pct: float = 0.30
    short_entry_pct: float = 0.70
    
    # 趋势确认
    ema_fast: int = 17
    ema_slow: int = 48
    rsi_period: int = 14
    rsi_overbought: float = 70
    
    # 趋势过滤（新增）
    trend_ma_period: int = 200          # 长期趋势均线
    trend_filter_enabled: bool = True   # 是否启用趋势过滤
    
    # 止损止盈（优化：放宽）
    atr_period: int = 14
    atr_stop_mult: float = 1.8          # v1: 1.2x → v2: 1.8x
    atr_take_mult: float = 2.5          # v1: 2.0x → v2: 2.5x
    min_stop_pct: float = 0.012         # v1: 0.8% → v2: 1.2%
    max_stop_pct: float = 0.050         # v1: 3.5% → v2: 5.0%
    
    # 移动止损（优化：提高触发阈值）
    trailing_trigger: float = 0.03      # v1: 1% → v2: 3%
    trailing_pct_low: float = 0.10
    trailing_pct_mid: float = 0.15
    trailing_pct_high: float = 0.25
    
    # 超时平仓（优化：延长）
    max_hold_days: int = 10             # v1: 7天 → v2: 10天
    
    # 交易成本
    commission_rate: float = 0.00015
    slippage_rate: float = 0.0002
    
    # 品种特异性止损调整
    symbol_atr_adjustment: Dict[str, float] = None  # 品种ATR倍数调整
    
    def __post_init__(self):
        if self.symbol_atr_adjustment is None:
            self.symbol_atr_adjustment = {
                # 高波动品种需要更大止损
                'SA': 1.3,   # 纯碱 ATR*1.3 = 2.34x
                'FG': 1.2,   # 玻璃 ATR*1.2 = 2.16x
                'EG': 1.25,  # 乙二醇 ATR*1.25 = 2.25x
                'SM': 1.25,  # 硅锰 ATR*1.25 = 2.25x
                'SF': 1.2,   # 硅铁 ATR*1.2 = 2.16x
                'I': 1.3,    # 铁矿石 ATR*1.3 = 2.34x
                # TA稳定，不需要调整
                'TA': 1.0,
            }
    
    def get_atr_stop_mult(self, symbol: str) -> float:
        """获取品种特定的ATR止损倍数"""
        adjustment = self.symbol_atr_adjustment.get(symbol, 1.0)
        return self.atr_stop_mult * adjustment


# ============================================================
# 信号和持仓
# ============================================================
class SignalType(Enum):
    LONG = 1
    SHORT = -1


@dataclass
class Position:
    symbol: str
    direction: int
    entry_date: pd.Timestamp
    entry_price: float
    size: int
    stop_loss: float
    take_profit: float
    highest_profit_pct: float = 0.0


# ============================================================
# 优化版策略引擎
# ============================================================
class OptimizedQuantileStrategy:
    """
    优化版分位数短线策略
    
    核心改进：
    1. ATR止损放宽到1.8x（高波动品种更大）
    2. 移动止损触发提高到3%
    3. 做多信号去掉RSI<30硬性约束
    4. 200日均线趋势过滤
    5. 超时平仓延长到10天
    """
    
    def __init__(self, params: OptimizedParams = None):
        self.params = params or OptimizedParams()
        self.loader = ParquetLoader()
    
    def prepare_data(self, symbol: str,
                     start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """准备数据，增加趋势过滤指标"""
        df = self.loader.load_symbol(symbol, start_date, end_date)
        if df is None or len(df) < 250:  # 需要至少250天计算200日均线
            return None
        
        # 技术指标
        df['ema_fast'] = calc_ema(df['close'], self.params.ema_fast)
        df['ema_slow'] = calc_ema(df['close'], self.params.ema_slow)
        df['rsi'] = calc_rsi(df['close'], self.params.rsi_period)
        df['atr'] = calc_atr(df, self.params.atr_period)
        df['pct_rank'] = calc_percentile_rank(df['close'], self.params.percentile_window)
        
        # 成交量均线（用于流动性过滤）
        df['volume_ma'] = calc_ma(df['volume'], 20)
        
        # 趋势过滤：200日均线
        if self.params.trend_filter_enabled:
            df['trend_ma'] = calc_ma(df['close'], self.params.trend_ma_period)
            # 趋势方向：价格在200日均线上方为上升趋势
            df['in_uptrend'] = df['close'] > df['trend_ma']
        
        # 做多信号（优化：去掉RSI<30硬性约束）
        df['signal_long'] = (
            (df['pct_rank'] < self.params.long_entry_pct) &
            (df['ema_fast'] > df['ema_slow'])
            # 去掉了 RSI < 30 的约束
        )
        
        # 做空信号（保持不变）
        df['signal_short'] = (
            (df['pct_rank'] > self.params.short_entry_pct) &
            (df['rsi'] > self.params.rsi_overbought)
        )
        
        # 趋势过滤：逆势信号过滤
        if self.params.trend_filter_enabled:
            # 上升趋势中不做空（过滤逆势做空）
            df['signal_short'] = df['signal_short'] & (~df['in_uptrend'])
            # 下降趋势中不做多（过滤逆势做多）
            df['signal_long'] = df['signal_long'] & (df['in_uptrend'])
        
        return df
    
    def backtest_single_symbol(self, symbol: str,
                               start_date: str, end_date: str,
                               initial_capital: float = 10000) -> Dict:
        """回测单个品种（使用日内高低点判断止损）"""
        spec = self.loader.get_spec(symbol)
        if spec is None:
            return {'error': f'品种{symbol}规格未知'}
        
        df = self.prepare_data(symbol, start_date, end_date)
        if df is None:
            return {'error': f'品种{symbol}数据不足'}
        
        atr_stop_mult = self.params.get_atr_stop_mult(symbol)
        
        capital = initial_capital
        position: Optional[Position] = None
        trades = []
        equity_curve = []
        
        for i, row in df.iterrows():
            current_date = row['date']
            current_close = row['close']
            current_high = row['high']
            current_low = row['low']
            
            # 出场检查（使用日内高低点）
            if position is not None:
                exit_reason = None
                exit_price = current_close
                
                # 1. 硬止损（用日内高低点判断）
                if position.direction == 1:
                    if current_low <= position.stop_loss:
                        exit_reason = '硬止损'
                        # 估算止损价（可能滑点）
                        exit_price = position.stop_loss * 0.999
                else:
                    if current_high >= position.stop_loss:
                        exit_reason = '硬止损'
                        exit_price = position.stop_loss * 1.001
                
                # 2. 止盈
                if exit_reason is None:
                    if position.direction == 1:
                        if current_high >= position.take_profit:
                            exit_reason = 'ATR止盈'
                            exit_price = position.take_profit
                    else:
                        if current_low <= position.take_profit:
                            exit_reason = 'ATR止盈'
                            exit_price = position.take_profit
                
                # 3. 超时平仓
                if exit_reason is None:
                    hold_days = (current_date - position.entry_date).days
                    if hold_days >= self.params.max_hold_days:
                        exit_reason = f'超时{hold_days}天'
                
                # 4. 移动止损
                if exit_reason is None:
                    if position.direction == 1:
                        profit_pct = (current_close - position.entry_price) / position.entry_price
                    else:
                        profit_pct = (position.entry_price - current_close) / position.entry_price
                    
                    position.highest_profit_pct = max(position.highest_profit_pct, profit_pct)
                    
                    if position.highest_profit_pct >= self.params.trailing_trigger:
                        if position.highest_profit_pct > 1.00:
                            trail = self.params.trailing_pct_high
                        elif position.highest_profit_pct > 0.50:
                            trail = self.params.trailing_pct_mid
                        else:
                            trail = self.params.trailing_pct_low
                        
                        if position.direction == 1:
                            new_stop = current_close * (1 - trail)
                            if new_stop > position.stop_loss:
                                position.stop_loss = new_stop
                            if current_low <= position.stop_loss:
                                exit_reason = '移动止损'
                                exit_price = position.stop_loss
                        else:
                            new_stop = current_close * (1 + trail)
                            if new_stop < position.stop_loss:
                                position.stop_loss = new_stop
                            if current_high >= position.stop_loss:
                                exit_reason = '移动止损'
                                exit_price = position.stop_loss
                
                # 执行出场
                if exit_reason:
                    if position.direction == 1:
                        pnl = (exit_price - position.entry_price) * spec.multiplier
                    else:
                        pnl = (position.entry_price - exit_price) * spec.multiplier
                    
                    cost = (position.entry_price + exit_price) * spec.multiplier * \
                           position.size * (self.params.commission_rate + self.params.slippage_rate)
                    
                    net_pnl = pnl * position.size - cost
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
            
            # 入场检查
            if position is None:
                if i + 1 < len(df):
                    next_row = df.iloc[i + 1]
                    exec_price = next_row['open']
                    exec_date = next_row['date']
                    
                    # 计算止损止盈
                    atr = row['atr']
                    if pd.isna(atr):
                        continue
                    
                    stop_distance = max(
                        atr * atr_stop_mult,
                        exec_price * self.params.min_stop_pct
                    )
                    stop_distance = min(stop_distance, exec_price * self.params.max_stop_pct)
                    take_distance = atr * self.params.atr_take_mult
                    
                    today_signals = [row]
                    for sig_row in today_signals:
                        # 保证金检查
                        margin_needed = spec.calc_margin(exec_price)
                        if margin_needed > capital * 0.35:
                            continue
                        
                        # 确定信号类型
                        if sig_row.get('signal_long'):
                            sig_type = 1
                            actual_sl = exec_price * (1 - self.params.slippage_rate) - stop_distance
                            actual_tp = exec_price * (1 + self.params.slippage_rate) + take_distance
                        elif sig_row.get('signal_short'):
                            sig_type = -1
                            actual_sl = exec_price * (1 + self.params.slippage_rate) + stop_distance
                            actual_tp = exec_price * (1 - self.params.slippage_rate) - take_distance
                        else:
                            continue
                        
                        position = Position(
                            symbol=symbol,
                            direction=sig_type,
                            entry_date=exec_date,
                            entry_price=exec_price,
                            size=1,
                            stop_loss=actual_sl,
                            take_profit=actual_tp,
                        )
                        break
            
            # 权益记录
            equity_curve.append({
                'date': current_date,
                'capital': capital,
            })
        
        # 统计
        if len(trades) == 0:
            return {'symbol': symbol, 'total_trades': 0, 'error': '无交易'}
        
        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve)
        
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
        
        days = (df['date'].max() - df['date'].min()).days
        years = days / 365.25
        annual_return = (capital / initial_capital) ** (1 / years) - 1 if years > 0 else 0
        
        daily_returns = equity_df['capital'].pct_change().dropna()
        sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0
        
        exit_reasons = trades_df['exit_reason'].value_counts().to_dict()
        
        # 多空分别统计
        long_trades = trades_df[trades_df['direction'] == '多']
        short_trades = trades_df[trades_df['direction'] == '空']
        
        return {
            'symbol': symbol,
            'initial_capital': initial_capital,
            'final_capital': capital,
            'total_return_pct': total_pnl / initial_capital * 100,
            'annual_return_pct': annual_return * 100,
            'total_trades': len(trades_df),
            'long_trades': len(long_trades),
            'short_trades': len(short_trades),
            'long_win_rate': len(long_trades[long_trades['pnl'] > 0]) / len(long_trades) * 100 if len(long_trades) > 0 else 0,
            'short_win_rate': len(short_trades[short_trades['pnl'] > 0]) / len(short_trades) * 100 if len(short_trades) > 0 else 0,
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


if __name__ == "__main__":
    print("=" * 60)
    print("路径二 v2：优化版策略 - 单品种测试")
    print("=" * 60)
    
    strategy = OptimizedQuantileStrategy(OptimizedParams())
    
    # 测试TA (PTA) - 之前最成功的品种
    result = strategy.backtest_single_symbol(
        symbol="TA",
        start_date="2020-01-01",
        end_date="2025-12-31",
        initial_capital=10000,
    )
    
    if 'error' in result and result.get('total_trades', 0) == 0:
        print("无交易信号")
    elif 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"\n品种: {result['symbol']}")
        print(f"初始资金: {result['initial_capital']:,.0f}元")
        print(f"期末资金: {result['final_capital']:,.0f}元")
        print(f"总收益率: {result['total_return_pct']:.2f}%")
        print(f"年化收益率: {result['annual_return_pct']:.2f}%")
        print(f"交易次数: {result['total_trades']} (多:{result['long_trades']}, 空:{result['short_trades']})")
        print(f"做多胜率: {result['long_win_rate']:.1f}%")
        print(f"做空胜率: {result['short_win_rate']:.1f}%")
        print(f"盈亏比: {result['profit_factor']:.2f}")
        print(f"最大回撤: {result['max_drawdown_pct']:.2f}%")
        print(f"夏普比率: {result['sharpe_ratio']:.2f}")
        print(f"\n出场原因:")
        for reason, count in result['exit_reasons'].items():
            print(f"  {reason}: {count}次")
    
    print("\n" + "=" * 60)
