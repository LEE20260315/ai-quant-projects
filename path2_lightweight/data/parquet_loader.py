#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径二：轻量级分位数短线系统
核心数据加载器 - 从本地Parquet文件读取期货连续合约数据
"""
import os
import time
import glob
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FUTURES_DATA_DIR


# ============================================================
# 低保证金品种清单（1万元可交易）
# ============================================================
# 格式: (品种代码, 合约乘数, 保证金率, 中文名称)
LOW_MARGIN_SYMBOLS = [
    ("RB", 10, 0.09, "螺纹钢"),
    ("MA", 10, 0.06, "甲醇"),
    ("FG", 20, 0.05, "玻璃"),
    ("SA", 20, 0.06, "纯碱"),
    ("M", 10, 0.08, "豆粕"),
    ("CS", 10, 0.08, "玉米淀粉"),
    ("FB", 10, 0.05, "短纤"),
    ("RM", 10, 0.08, "菜籽粕"),
    ("V", 5, 0.05, "PVC"),
    ("TA", 5, 0.06, "PTA"),
    ("L", 5, 0.05, "塑料"),
    ("PP", 5, 0.05, "聚丙烯"),
    ("EG", 10, 0.06, "乙二醇"),
    ("UR", 20, 0.07, "尿素"),
    ("SP", 10, 0.08, "纸浆"),
    ("HC", 10, 0.09, "热轧卷板"),
    ("I", 100, 0.15, "铁矿石"),
    ("SM", 5, 0.06, "硅锰"),
    ("SF", 5, 0.06, "硅铁"),
    ("AP", 10, 0.05, "苹果"),
    ("CJ", 5, 0.08, "红枣"),
]


@dataclass
class FuturesSpec:
    """期货品种规格"""
    symbol: str
    multiplier: int        # 合约乘数
    margin_ratio: float    # 保证金率
    name: str              # 中文名称
    
    def calc_margin(self, price: float) -> float:
        """计算单手保证金"""
        return price * self.multiplier * self.margin_ratio


class ParquetLoader:
    """
    本地Parquet数据加载器
    
    数据结构:
    - 文件路径: {FUTURES_CONTINUOUS_DIR}/{symbol}_main.parquet
    - 字段: date, open, high, low, close, volume, open_interest
    """
    
    def __init__(self, data_dir: str = None,
                 cache_ttl_seconds: int = 3600):
        if data_dir is None:
            data_dir = FUTURES_DATA_DIR
        self.data_dir = data_dir
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl = cache_ttl_seconds
    
    def get_spec(self, symbol: str) -> Optional[FuturesSpec]:
        """获取品种规格"""
        for spec_data in LOW_MARGIN_SYMBOLS:
            if spec_data[0] == symbol:
                return FuturesSpec(*spec_data)
        return None
    
    def load_symbol(self, symbol: str, 
                    start_date: str = None, 
                    end_date: str = None,
                    use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        加载单个品种的连续合约数据
        
        Args:
            symbol: 品种代码 (如 'RB', 'MA')
            start_date: 起始日期 (如 '2020-01-01')
            end_date: 结束日期 (如 '2025-12-31')
            use_cache: 是否使用内存缓存
        
        Returns:
            DataFrame with columns: date, open, high, low, close, volume, open_interest
            或 None 如果文件不存在
        """
        if use_cache and symbol in self._cache:
            cached_time = self._cache_time.get(symbol, 0)
            if (time.time() - cached_time) < self._cache_ttl:
                df = self._cache[symbol].copy()
            else:
                del self._cache[symbol]
                self._cache_time.pop(symbol, None)
                df = None
        else:
            df = None

        if df is None:
            filepath = os.path.join(self.data_dir, f"{symbol}_main.parquet")
            if not os.path.exists(filepath):
                return None
            
            df = pd.read_parquet(filepath)
            
            # 标准化列名（处理可能的列名差异）
            df = self._standardize_columns(df)
            
            # 确保日期格式
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
            
            if use_cache:
                self._cache[symbol] = df.copy()
                self._cache_time[symbol] = time.time()
        
        # 日期过滤
        if start_date:
            df = df[df['date'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['date'] <= pd.to_datetime(end_date)]
        
        return df.reset_index(drop=True)
    
    def load_multiple(self, symbols: List[str],
                      start_date: str = None,
                      end_date: str = None) -> Dict[str, pd.DataFrame]:
        """
        加载多个品种的数据
        
        Returns:
            {symbol: DataFrame} 字典
        """
        result = {}
        for symbol in symbols:
            df = self.load_symbol(symbol, start_date, end_date)
            if df is not None and len(df) > 0:
                result[symbol] = df
        return result
    
    def load_all_available(self, 
                           start_date: str = None,
                           end_date: str = None) -> Dict[str, pd.DataFrame]:
        """加载所有可用的低保证金品种"""
        symbols = [s[0] for s in LOW_MARGIN_SYMBOLS]
        return self.load_multiple(symbols, start_date, end_date)
    
    def check_data_availability(self, symbols: List[str] = None) -> pd.DataFrame:
        """
        检查数据可用性
        
        Returns:
            DataFrame: symbol, name, file_exists, row_count, date_range
        """
        if symbols is None:
            symbols = [s[0] for s in LOW_MARGIN_SYMBOLS]
        
        results = []
        for symbol in symbols:
            spec = self.get_spec(symbol)
            filepath = os.path.join(self.data_dir, f"{symbol}_main.parquet")
            exists = os.path.exists(filepath)
            
            if exists:
                df = pd.read_parquet(filepath)
                df = self._standardize_columns(df)
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    date_min = df['date'].min().strftime('%Y-%m-%d')
                    date_max = df['date'].max().strftime('%Y-%m-%d')
                    row_count = len(df)
                else:
                    date_min = date_max = "N/A"
                    row_count = len(df)
            else:
                date_min = date_max = "N/A"
                row_count = 0
            
            results.append({
                'symbol': symbol,
                'name': spec.name if spec else "未知",
                'multiplier': spec.multiplier if spec else 0,
                'margin_ratio': spec.margin_ratio if spec else 0,
                'file_exists': exists,
                'row_count': row_count,
                'date_min': date_min,
                'date_max': date_max,
            })
        
        return pd.DataFrame(results)
    
    def clear_cache(self):
        """清空内存缓存"""
        self._cache.clear()
    
    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名"""
        # 创建列名映射（处理常见的大小写差异）
        col_map = {}
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in ['date', 'trade_date', 'datetime']:
                col_map[col] = 'date'
            elif col_lower in ['open', 'open_price']:
                col_map[col] = 'open'
            elif col_lower in ['high', 'high_price']:
                col_map[col] = 'high'
            elif col_lower in ['low', 'low_price']:
                col_map[col] = 'low'
            elif col_lower in ['close', 'close_price', 'settle']:
                col_map[col] = 'close'
            elif col_lower in ['volume', 'vol']:
                col_map[col] = 'volume'
            elif col_lower in ['open_interest', 'oi', 'openinterest', 'hold']:
                col_map[col] = 'open_interest'
        
        if col_map:
            df = df.rename(columns=col_map)
        
        # 去重列（保留第一个）
        df = df.loc[:, ~df.columns.duplicated()]
        
        return df


# ============================================================
# 技术指标计算工具
# ============================================================

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """计算EMA"""
    return series.ewm(span=period, adjust=False).mean()


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    计算ATR (Average True Range)
    
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = MA(True Range, period)
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_percentile_rank(series: pd.Series, window: int = 40) -> pd.Series:
    values = series.values
    n = len(values)
    result = np.full(n, np.nan)
    for i in range(window - 1, n):
        window_vals = values[i - window + 1:i + 1]
        result[i] = np.sum(window_vals <= values[i]) / window
    return pd.Series(result, index=series.index)


def calc_ma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


calc_sma = calc_ma


def calc_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    ma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    return (series - ma) / std


def calc_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    ma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return upper, ma, lower


def calc_keltner_channels(df: pd.DataFrame, ema_period: int = 20,
                          atr_period: int = 10, multiplier: float = 1.5):
    mid = calc_ema(df['close'], ema_period)
    atr = calc_atr(df, atr_period)
    upper = mid + multiplier * atr
    lower = mid - multiplier * atr
    return upper, mid, lower


# ============================================================
# 快速测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("路径二：轻量级分位数短线系统 - 数据加载器测试")
    print("=" * 60)
    
    loader = ParquetLoader()
    
    # 检查数据可用性
    print("\n检查数据可用性...")
    availability = loader.check_data_availability()
    available = availability[availability['file_exists'] == True]
    
    print(f"\n低保证金品种: {len(LOW_MARGIN_SYMBOLS)}个")
    print(f"可用数据: {len(available)}个")
    print(f"缺失数据: {len(availability) - len(available)}个")
    
    print("\n可用品种详情:")
    for _, row in available.iterrows():
        print(f"  {row['symbol']:4s} ({row['name']:6s}) | "
              f"乘数:{row['multiplier']:4d} | 保证金:{row['margin_ratio']:.0%} | "
              f"{row['row_count']:5d}行 | {row['date_min']} ~ {row['date_max']}")
    
    # 加载单个品种测试
    print("\n" + "-" * 60)
    print("加载螺纹钢(RB)数据测试...")
    rb_data = loader.load_symbol("RB", start_date="2024-01-01", end_date="2025-12-31")
    if rb_data is not None:
        print(f"  数据行数: {len(rb_data)}")
        print(f"  列: {list(rb_data.columns)}")
        print(f"  最近5日收盘价:")
        print(rb_data[['date', 'close']].tail(5).to_string(index=False))
    else:
        print("  数据不可用")
    
    print("\n" + "=" * 60)
    print("数据加载器测试完成!")
