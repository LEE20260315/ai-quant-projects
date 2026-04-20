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
    max_total_position_pct: float = 0.80 # 总仓位上限80%
    max_drawdown_stop: float = 0.50      # 组合最大回撤止损50%
    start_date: str = "2020-01-01"
    end_date: str = "2025-12-31"
    commission_rate: float = 0.00015
    slippage_rate: float = 0.0002

    # ===== 新增风控参数（激进型阈值）=====
    # 动态仓位管理
    dynamic_position_enabled: bool = True
    position_reduction_25: float = 0.50  # 回撤25%时仓位减半
    position_reduction_35: float = 0.25  # 回撤35%时仓位25%
    pause_days_45: int = 5               # 回撤45%暂停5天
    pause_days_55: int = 10              # 回撤55%暂停10天

    # 波动率目标控制
    volatility_target_enabled: bool = True
    target_volatility: float = 0.15      # 目标年化波动率15%
    volatility_lookback: int = 20        # 波动率计算窗口

    # 自适应品种轮动（基于夏普比率）
    symbol_rotation_enabled: bool = True
    sharpe_lookback: int = 20            # 夏普比率计算窗口
    min_trades_for_sharpe: int = 5       # 计算夏普所需最少交易次数
    weight_adjustment_rate: float = 0.5  # 权重调整速度（0-1）
    consecutive_loss_weight_penalty: float = 0.3  # 连续亏损权重惩罚


from datetime import datetime, timedelta


@dataclass
class PortfolioPosition:
    """组合持仓"""
    symbol: str
    direction: int  # 1=多, -1=空
    entry_date: datetime
    entry_price: float
    size: int
    stop_loss: float
    take_profit: float
    margin_used: float
    highest_profit_pct: float = 0.0


# ============================================================
# 风控管理器类
# ============================================================

class DynamicPositionManager:
    """动态仓位管理器 - 根据回撤水平调整仓位"""
    def __init__(self, config):
        self.config = config
        self.current_drawdown = 0.0
        self.pause_until = None
        self.position_multiplier = 1.0  # 仓位乘数
        self.drawdown_history = []  # 记录回撤触发历史

    def update_drawdown(self, drawdown, current_date):
        """根据回撤水平调整仓位（激进型阈值）"""
        self.current_drawdown = drawdown

        # 检查是否在暂停期内
        if self.pause_until is not None and current_date <= self.pause_until:
            return

        # 重置暂停期
        self.pause_until = None

        # 根据回撤水平调整仓位
        if drawdown >= 0.55:
            self.position_multiplier = 0.0  # 完全停止
            self.pause_until = None  # 永久暂停
            if drawdown >= 0.55 and (not self.drawdown_history or self.drawdown_history[-1] < 0.55):
                self.drawdown_history.append(drawdown)
                print(f"  组合回撤{drawdown:.1%}触发永久停止")

        elif drawdown >= 0.45:
            self.position_multiplier = 0.0
            self.pause_until = current_date + timedelta(days=self.config.pause_days_45)
            if drawdown >= 0.45 and (not self.drawdown_history or self.drawdown_history[-1] < 0.45):
                self.drawdown_history.append(drawdown)
                print(f"  组合回撤{drawdown:.1%}触发暂停{self.config.pause_days_45}天")

        elif drawdown >= 0.35:
            self.position_multiplier = self.config.position_reduction_35
            self.pause_until = None
            if drawdown >= 0.35 and (not self.drawdown_history or self.drawdown_history[-1] < 0.35):
                self.drawdown_history.append(drawdown)
                print(f"  组合回撤{drawdown:.1%}触发仓位降至25%")

        elif drawdown >= 0.25:
            self.position_multiplier = self.config.position_reduction_25
            self.pause_until = None
            if drawdown >= 0.25 and (not self.drawdown_history or self.drawdown_history[-1] < 0.25):
                self.drawdown_history.append(drawdown)
                print(f"  组合回撤{drawdown:.1%}触发仓位减半")

        else:
            self.position_multiplier = 1.0
            self.pause_until = None

    def get_max_position_pct(self):
        """获取调整后的最大仓位比例"""
        return self.config.max_position_pct * self.position_multiplier

    def get_max_total_position_pct(self):
        """获取调整后的总仓位比例"""
        return self.config.max_total_position_pct * self.position_multiplier

    def can_trade(self, current_date):
        """检查是否可以交易"""
        if self.pause_until is None:
            return True
        return current_date > self.pause_until


class VolatilityTargetManager:
    """波动率目标管理器 - 控制组合波动率"""
    def __init__(self, config):
        self.config = config
        self.equity_history = []  # (date, equity_value)
        self.current_volatility = 0.0

    def update_equity(self, equity_value, date):
        """更新权益历史并计算波动率"""
        self.equity_history.append((date, equity_value))

        # 保持最近N天的数据
        if len(self.equity_history) > self.config.volatility_lookback:
            self.equity_history.pop(0)

        # 计算波动率（年化）- 需要至少5个数据点
        if len(self.equity_history) >= 5:
            returns = []
            for i in range(1, len(self.equity_history)):
                prev_equity = self.equity_history[i-1][1]
                curr_equity = self.equity_history[i][1]
                if prev_equity > 0:
                    daily_return = (curr_equity - prev_equity) / prev_equity
                    returns.append(daily_return)

            if returns:
                std_daily = np.std(returns)
                self.current_volatility = std_daily * np.sqrt(252)  # 年化

    def get_position_adjustment(self):
        """根据波动率调整仓位"""
        if self.current_volatility <= 0:
            return 1.0

        # 波动率越高，仓位越低
        target_ratio = self.config.target_volatility / max(self.current_volatility, 0.01)
        # 限制调整范围在0.3到1.5之间
        return max(0.3, min(1.5, target_ratio))

    def get_current_volatility(self):
        """获取当前波动率"""
        return self.current_volatility


class AdaptiveSymbolRotation:
    """自适应品种轮动管理器 - 基于夏普比率的动态权重调整"""
    def __init__(self, config):
        self.config = config
        self.symbol_stats = {}  # symbol -> {trade_history, sharpe_ratio, consecutive_losses, weight}

    def update_symbol_stats(self, symbol, trade_result):
        """更新品种统计信息"""
        if symbol not in self.symbol_stats:
            self.symbol_stats[symbol] = {
                'trade_history': [],
                'sharpe_ratio': 0.0,
                'consecutive_losses': 0,
                'weight': 1.0,
                'last_update': None
            }

        stats = self.symbol_stats[symbol]
        stats['trade_history'].append(trade_result)

        # 记录亏损连续次数
        if trade_result['pnl'] <= 0:
            stats['consecutive_losses'] += 1
        else:
            stats['consecutive_losses'] = 0

        # 保持最近N个交易记录
        if len(stats['trade_history']) > 50:
            stats['trade_history'].pop(0)

        # 计算夏普比率（如果有足够数据）
        if len(stats['trade_history']) >= self.config.min_trades_for_sharpe:
            returns = [t['pnl'] / abs(t['entry_price']) for t in stats['trade_history']]
            if len(returns) >= 2:
                mean_return = np.mean(returns)
                std_return = np.std(returns)
                if std_return > 0:
                    stats['sharpe_ratio'] = mean_return / std_return * np.sqrt(252)

        # 更新权重
        self._update_symbol_weight(symbol)

    def _update_symbol_weight(self, symbol):
        """基于夏普比率和连续亏损更新品种权重"""
        stats = self.symbol_stats[symbol]

        # 基础权重：夏普比率越高，权重越高
        if stats['sharpe_ratio'] > 0:
            base_weight = min(2.0, max(0.1, stats['sharpe_ratio'] / 0.5))  # 夏普0.5对应权重1.0
        else:
            base_weight = 0.5  # 负夏普默认权重0.5

        # 连续亏损惩罚
        consecutive_loss_penalty = 1.0 - min(0.7, stats['consecutive_losses'] * 0.1)

        # 平滑调整权重
        new_weight = base_weight * consecutive_loss_penalty
        stats['weight'] = stats['weight'] * (1 - self.config.weight_adjustment_rate) + \
                         new_weight * self.config.weight_adjustment_rate

        # 权重范围限制
        stats['weight'] = max(0.1, min(2.0, stats['weight']))

    def get_symbol_weight(self, symbol):
        """获取品种权重（用于信号排序）"""
        if symbol not in self.symbol_stats:
            return 1.0
        return self.symbol_stats[symbol]['weight']

    def get_adjusted_signal_strength(self, symbol, original_strength):
        """获取调整后的信号强度"""
        weight = self.get_symbol_weight(symbol)
        return original_strength * weight

    def get_symbol_sharpe(self, symbol):
        """获取品种的夏普比率"""
        if symbol not in self.symbol_stats:
            return 0.0
        return self.symbol_stats[symbol]['sharpe_ratio']


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

        # 初始化风控管理器
        self.position_manager = DynamicPositionManager(self.config)
        self.volatility_manager = VolatilityTargetManager(self.config)
        self.symbol_rotation_manager = AdaptiveSymbolRotation(self.config)
    
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
            
            # 信号 - 与单个策略保持一致
            df['signal_long'] = (
                (df['pct_rank'] < params.long_entry_pct) &
                (df['ema_fast'] > df['ema_slow'])
            )
            df['signal_short'] = (
                (df['pct_rank'] > params.short_entry_pct) &
                (df['rsi'] > params.rsi_overbought)
            )
            
            # 趋势过滤（与单个策略保持一致）
            if params.trend_filter_enabled:
                df['trend_ma'] = df['close'].rolling(window=200).mean()
                df['in_uptrend'] = df['close'] > df['trend_ma']
                # 上升趋势中不做空
                df['signal_short'] = df['signal_short'] & (~df['in_uptrend'])
                # 下降趋势中不做多
                df['signal_long'] = df['signal_long'] & (df['in_uptrend'])
            
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

    def _calculate_dynamic_stop_distance(self, atr, atr_stop_mult, exec_price,
                                        min_stop_pct, max_stop_pct, symbol,
                                        current_volatility=None):
        """计算动态止损距离，考虑波动率调整"""
        # 基础止损距离
        base_stop_distance = max(
            atr * atr_stop_mult,
            exec_price * min_stop_pct
        )
        base_stop_distance = min(base_stop_distance, exec_price * max_stop_pct)

        # 如果提供了当前波动率，进行动态调整
        if current_volatility is not None and current_volatility > 0:
            # 波动率越高，止损距离越大
            # 基准波动率设为15%（目标波动率）
            volatility_ratio = current_volatility / self.config.target_volatility
            # 限制调整范围在0.7到1.5之间
            volatility_adjustment = max(0.7, min(1.5, volatility_ratio))
            base_stop_distance *= volatility_adjustment

        # 品种特异性调整（如果配置了）
        if hasattr(self, 'symbol_rotation_manager'):
            symbol_weight = self.symbol_rotation_manager.get_symbol_weight(symbol)
            # 权重低的品种（表现差）使用更大止损
            # 权重范围0.1-2.0，1.0为基准
            weight_adjustment = 1.0 / max(0.5, symbol_weight)  # 权重越低，止损越大
            base_stop_distance *= min(1.5, max(0.7, weight_adjustment))

        return base_stop_distance

    def _calculate_drawdown(self, capital, equity_curve_history):
        """计算组合回撤（只使用已实现盈亏）"""
        # 只考虑已实现盈亏（账户资金变化）
        realized_equity = capital

        # 计算历史峰值（基于已实现权益）
        if equity_curve_history:
            historical_peaks = [point['capital'] for point in equity_curve_history]
            peak_equity = max(historical_peaks + [realized_equity])
        else:
            peak_equity = max(self.config.initial_capital, realized_equity)

        # 计算回撤
        current_dd = (peak_equity - realized_equity) / peak_equity if peak_equity > 0 else 0
        return current_dd, peak_equity, realized_equity

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
        
        with open('trade_details.txt', 'w', encoding='utf-8') as f:
            f.write('')
        
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
            # 创建副本以避免在遍历过程中修改字典
            for symbol, pos in list(positions.items()):
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
                        exit_price = pos.stop_loss
                else:
                    if current_high >= pos.stop_loss:
                        exit_reason = '硬止损'
                        exit_price = pos.stop_loss
                
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
                    
                    # 诊断：打印交易详情
                    print(f"  平仓: {symbol} 方向:{pos.direction}, 入场:{pos.entry_price:.2f}, 出场:{exit_price:.2f}, 盈亏:{net_pnl:.2f}, 原因:{exit_reason}")
                    
                    # 记录交易到文件
                    with open('trade_details.txt', 'a', encoding='utf-8') as f:
                        f.write(f"日期: {current_date}, 品种: {symbol}, 方向: {pos.direction}, 入场价: {pos.entry_price:.2f}, 出场价: {exit_price:.2f}, 盈亏: {net_pnl:.2f}, 原因: {exit_reason}, 持仓天数: {hold_days}, 资金: {capital:.2f}\n")
                    
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
                    
                    # 从持仓中移除已平仓的品种
                    del positions[symbol]
                    
                    # 更新品种轮动管理器的统计信息
                    if self.config.symbol_rotation_enabled:
                        trade_result = {
                            'symbol': symbol,
                            'pnl': net_pnl,
                            'entry_price': pos.entry_price,
                            'exit_price': exit_price,
                            'entry_date': pos.entry_date,
                            'exit_date': current_date,
                            'direction': pos.direction
                        }
                        self.symbol_rotation_manager.update_symbol_stats(symbol, trade_result)
            
            # 修复：正确清理持仓
            for symbol in list(positions.keys()):
                if symbol not in positions:
                    continue
                # 检查是否需要平仓（上面已经处理）
            
            # 1b. 组合级别最大回撤检查 - 使用新的风控系统
            current_dd, peak_equity, realized_equity = self._calculate_drawdown(capital, equity_curve)

            # 更新风控管理器
            self.position_manager.update_drawdown(current_dd, current_date)
            self.volatility_manager.update_equity(realized_equity, current_date)

            # 检查是否需要强制平仓（只使用已实现盈亏计算的回撤）
            if current_dd >= self.config.max_drawdown_stop and len(positions) > 0:
                # 触发最大回撤止损，强制平仓所有持仓
                print(f"  组合回撤{current_dd:.1%}触发止损，强制平仓")
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
                        'symbol': symbol,
                        'direction': '多' if pos.direction == 1 else '空',
                        'entry_date': pos.entry_date,
                        'exit_date': current_date,
                        'entry_price': pos.entry_price,
                        'exit_price': exit_price,
                        'size': pos.size,
                        'pnl': net_pnl,
                        'hold_days': (current_date - pos.entry_date).days,
                        'exit_reason': f'组合回撤{current_dd:.1%}',
                        'capital_after': capital,
                    })
                    # 更新品种轮动统计（强制平仓）
                    if self.config.symbol_rotation_enabled:
                        trade_result = {
                            'symbol': symbol,
                            'pnl': net_pnl,
                            'entry_price': pos.entry_price,
                            'exit_price': exit_price,
                            'entry_date': pos.entry_date,
                            'exit_date': current_date,
                            'direction': pos.direction
                        }
                        self.symbol_rotation_manager.update_symbol_stats(symbol, trade_result)
                positions.clear()
                # 不再使用dd_triggered，而是通过position_manager管理暂停期
                self.position_manager.update_drawdown(current_dd, current_date)

            # 2. 收集当天的所有信号
            today_signals = []
            
            for symbol, df in all_data.items():
                row_mask = df['date'] == current_date
                if not row_mask.any():
                    continue
                
                row = df[row_mask].iloc[0]
                
                # 诊断：打印信号生成情况
                if row.get('signal_long') or row.get('signal_short'):
                    print(f"{current_date}: {symbol} 信号 - 多:{row.get('signal_long', False)}, 空:{row.get('signal_short', False)}, 分位数:{row.get('pct_rank', 0):.2f}, RSI:{row.get('rsi', 0):.1f}, EMA差:{(row.get('ema_fast', 0) - row.get('ema_slow', 0))/row.get('ema_slow', 1)*100:.2f}%")
                
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

            # 应用品种权重调整（如果启用）
            if self.config.symbol_rotation_enabled:
                for s in today_signals:
                    weight = self.symbol_rotation_manager.get_symbol_weight(s['symbol'])
                    s['signal_strength'] = s.get('signal_strength', 0.0) * weight

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
            
            # 执行开仓（最多到max_positions）- 使用风控管理器检查
            if self.position_manager.can_trade(current_date):
                # 获取动态调整后的仓位限制
                max_pos_pct = self.position_manager.get_max_position_pct()
                max_total_pct = self.position_manager.get_max_total_position_pct()

                # 应用波动率调整
                if self.config.volatility_target_enabled:
                    vol_adjustment = self.volatility_manager.get_position_adjustment()
                    max_pos_pct *= vol_adjustment
                    max_total_pct *= vol_adjustment

                current_total_margin = sum(p.margin_used for p in positions.values())
                max_total_margin = capital * max_total_pct

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

                    # 诊断：打印保证金检查情况
                    print(f"  开仓检查: {symbol} 保证金需求:{margin_needed:.2f}, 可用资金:{capital:.2f}, 最大单品种仓位:{capital * max_pos_pct:.2f}, 总保证金:{current_total_margin:.2f}, 最大总仓位:{max_total_margin:.2f}")

                    # 保证金检查1：单品种动态调整后的最大仓位
                    if margin_needed > capital * max_pos_pct:
                        print(f"  单品种仓位超限")
                        continue

                    # 保证金检查2：总仓位动态调整后的限制
                    if current_total_margin + margin_needed > max_total_margin:
                        print(f"  总仓位超限")
                        continue

                    # 计算止损止盈
                    atr = sig['atr']
                    if pd.isna(atr):
                        continue
                    
                    # 计算动态止损距离
                    atr_stop_mult = params.get_atr_stop_mult(symbol)
                    current_vol = self.volatility_manager.get_current_volatility()
                    stop_distance = self._calculate_dynamic_stop_distance(
                        atr=atr,
                        atr_stop_mult=atr_stop_mult,
                        exec_price=exec_price,
                        min_stop_pct=params.min_stop_pct,
                        max_stop_pct=params.max_stop_pct,
                        symbol=symbol,
                        current_volatility=current_vol
                    )
                    take_distance = atr * params.atr_take_mult
                    
                    # 计算止损止盈价格（考虑滑点）
                    # 做多：买入时考虑滑点（价格更高），卖出时考虑滑点（价格更低）
                    # 做空：卖出时考虑滑点（价格更低），买回时考虑滑点（价格更高）
                    if sig['direction'] == 1:
                        # 做多止损 = 入场价(考虑卖出滑点) - 止损距离
                        actual_sl = exec_price * (1 - self.config.slippage_rate) - stop_distance
                        # 做多止盈 = 入场价(考虑卖出滑点) + 止盈距离
                        actual_tp = exec_price * (1 + self.config.slippage_rate) + take_distance
                    else:
                        # 做空止损 = 入场价(考虑买回滑点) + 止损距离
                        actual_sl = exec_price * (1 + self.config.slippage_rate) + stop_distance
                        # 做空止盈 = 入场价(考虑买回滑点) - 止盈距离
                        actual_tp = exec_price * (1 - self.config.slippage_rate) - take_distance
                    
                    # 诊断：打印开仓详情
                    print(f"  开仓: {symbol} 方向:{sig['direction']}, 价格:{exec_price:.2f}, 止损:{actual_sl:.2f}, 止盈:{actual_tp:.2f}, 保证金:{margin_needed:.2f}")
                    
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
        percentile_window=40,
        long_entry_pct=0.25,
        short_entry_pct=0.75,
        atr_stop_mult=1.5,
        atr_take_mult=2.0,
        max_hold_days=7,
        trend_filter_enabled=True,
    )
    
    portfolio = PortfolioBacktest(config)
    
    # 测试品种组合：使用TA (PTA)，单个策略测试中表现良好
    test_symbols = ['TA', 'RM', 'MA']
    
    print(f"\n测试品种: {', '.join(test_symbols)}")
    print(f"时间: {config.start_date} ~ {config.end_date}")
    print(f"初始资金: {config.initial_capital:,.0f}元")
    
    result = portfolio.run(test_symbols, params)
    
    if 'error' in result:
        print(f"\n错误: {result['error']}")
    else:
        # 保存详细结果到文件
        import json
        result_copy = result.copy()
        # 移除DataFrame对象以避免JSON序列化错误
        result_copy.pop('trades_df', None)
        result_copy.pop('equity_df', None)
        result_copy.pop('signal_log', None)
        
        with open('回测结果详细.json', 'w', encoding='utf-8') as f:
            json.dump(result_copy, f, ensure_ascii=False, indent=2)
        
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
        
        print(f"\n详细结果已保存到: 回测结果详细.json")
    
    print("\n" + "=" * 80)
