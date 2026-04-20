#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路径一：AI增强多策略系统
数据加载器 - 复用path2的Parquet数据源，提供统一的数据接口

与path2共享:
- 相同的Parquet文件路径: D:\My project\cta_research\futures\continuous\*.parquet
- 相同的品种规格定义
- 相同的列名标准化逻辑
"""
import os
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass


# ============================================================
# 数据源配置 - 与path2完全一致
# ============================================================
CTA_RESEARCH_ROOT = r"D:\My project\cta_research"
FUTURES_CONTINUOUS_DIR = os.path.join(CTA_RESEARCH_ROOT, "futures", "continuous")


# ============================================================
# 低保证金品种清单（1万元可交易） - 与path2完全一致
# ============================================================
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

# path1重点品种分组
SYMBOL_GROUPS = {
    "TA": ["TA"],           # PTA
    "RM": ["RM"],           # 菜籽粕
    "MA": ["MA"],           # 甲醇
    "ALL_LOW_MARGIN": [s[0] for s in LOW_MARGIN_SYMBOLS],
}


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
    本地Parquet数据加载器 - 与path2兼容

    数据结构:
    - 文件路径: {FUTURES_CONTINUOUS_DIR}/{symbol}_main.parquet
    - 字段: date, open, high, low, close, volume, open_interest
    """

    def __init__(self, data_dir: str = FUTURES_CONTINUOUS_DIR):
        self.data_dir = data_dir
        self._cache: Dict[str, pd.DataFrame] = {}

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
            df = self._cache[symbol].copy()
        else:
            filepath = os.path.join(self.data_dir, f"{symbol}_main.parquet")
            if not os.path.exists(filepath):
                return None

            df = pd.read_parquet(filepath)
            df = self._standardize_columns(df)

            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)

            if use_cache:
                self._cache[symbol] = df.copy()

        if start_date:
            df = df[df['date'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['date'] <= pd.to_datetime(end_date)]

        return df.reset_index(drop=True)

    def load_multiple(self, symbols: List[str],
                      start_date: str = None,
                      end_date: str = None) -> Dict[str, pd.DataFrame]:
        """加载多个品种的数据"""
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
        """检查数据可用性"""
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

        df = df.loc[:, ~df.columns.duplicated()]
        return df


# ============================================================
# 技术指标计算工具 - 与path2共享
# ============================================================

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """计算EMA"""
    return series.ewm(span=period, adjust=False).mean()


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    """计算简单移动平均"""
    return series.rolling(window=period).mean()


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算ATR (Average True Range)"""
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """计算RSI"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_bollinger_bands(series: pd.Series, period: int = 20,
                         num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算布林带

    Returns:
        (upper, middle, lower)
    """
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def calc_keltner_channels(df: pd.DataFrame, ema_period: int = 20,
                          atr_period: int = 10,
                          atr_mult: float = 1.5) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算肯特纳通道

    Returns:
        (upper, middle, lower)
    """
    middle = calc_ema(df['close'], ema_period)
    atr = calc_atr(df, atr_period)
    upper = middle + atr_mult * atr
    lower = middle - atr_mult * atr
    return upper, middle, lower


def calc_percentile_rank(series: pd.Series, window: int = 40) -> pd.Series:
    """计算滚动分位数排名"""
    return series.rolling(window=window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1],
        raw=False
    )


def calc_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """计算滚动Z-Score"""
    mean = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    return (series - mean) / std


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26,
              signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算MACD

    Returns:
        (macd_line, signal_line, histogram)
    """
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ============================================================
# 快速测试
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("路径一：AI增强多策略系统 - 数据加载器测试")
    print("=" * 60)

    loader = ParquetLoader()

    # 检查数据可用性
    print("\n检查数据可用性...")
    availability = loader.check_data_availability()
    available = availability[availability['file_exists'] == True]

    print(f"\n低保证金品种: {len(LOW_MARGIN_SYMBOLS)}个")
    print(f"可用数据: {len(available)}个")

    # 加载TA数据测试
    print("\n加载TA(PTA)数据测试...")
    ta_data = loader.load_symbol("TA", start_date="2020-01-01", end_date="2025-12-31")
    if ta_data is not None:
        print(f"  数据行数: {len(ta_data)}")
        print(f"  列: {list(ta_data.columns)}")

        # 测试技术指标
        ta_data['atr'] = calc_atr(ta_data, 14)
        ta_data['rsi'] = calc_rsi(ta_data['close'], 14)
        ta_data['zscore'] = calc_zscore(ta_data['close'], 20)
        bb_upper, bb_mid, bb_lower = calc_bollinger_bands(ta_data['close'], 20, 2.0)

        print(f"  ATR最新值: {ta_data['atr'].iloc[-1]:.2f}")
        print(f"  RSI最新值: {ta_data['rsi'].iloc[-1]:.2f}")
        print(f"  Z-Score最新值: {ta_data['zscore'].iloc[-1]:.2f}")
        print(f"  布林带上轨: {bb_upper.iloc[-1]:.2f}")

    print("\n" + "=" * 60)
    print("数据加载器测试完成!")
