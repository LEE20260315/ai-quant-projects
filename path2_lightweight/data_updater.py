#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

from config import FUTURES_DATA_DIR


SYMBOLS_MAP = {
    'TA': {'name': 'PTA', 'ak_code': 'TA0'},
    'RM': {'name': '菜粕', 'ak_code': 'RM0'},
    'MA': {'name': '甲醇', 'ak_code': 'MA0'},
}

PARQUET_DIR = FUTURES_DATA_DIR


def fetch_futures_daily(symbol_code, days=2000):
    if not AKSHARE_AVAILABLE:
        raise ImportError('akshare未安装')
    try:
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        df = ak.futures_main_sina(symbol=symbol_code,
                                  start_date=start_date,
                                  end_date=end_date)
        if df is None or len(df) == 0:
            return None
        col_map = {
            '日期': 'date', '开盘价': 'open', '最高价': 'high',
            '最低价': 'low', '收盘价': 'close', '成交量': 'volume',
            '持仓量': 'hold', '动态结算价': 'settle',
        }
        df = df.rename(columns=col_map)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        for c in ['open', 'high', 'low', 'close', 'volume', 'hold', 'settle']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except Exception as e:
        print(f'  获取{symbol_code}数据失败: {e}')
        return None


def update_parquet_data(symbols=None):
    print('=' * 60)
    print('日K数据自动更新')
    print(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)

    if not AKSHARE_AVAILABLE:
        print('[ERROR] akshare不可用，无法更新数据')
        return {}

    if symbols is None:
        symbols = list(SYMBOLS_MAP.keys())

    results = {}
    for sym in symbols:
        info = SYMBOLS_MAP.get(sym, {})
        ak_code = info.get('ak_code', f'{sym}0')
        parquet_file = os.path.join(PARQUET_DIR, f'{sym}_main.parquet')

        legacy_file = os.path.join(PARQUET_DIR, f'{sym}.parquet')
        if not os.path.exists(parquet_file) and os.path.exists(legacy_file):
            import shutil
            shutil.move(legacy_file, parquet_file)
            print(f'  [MIGRATE] {sym}.parquet -> {sym}_main.parquet')

        existing_df = None
        if os.path.exists(parquet_file):
            existing_df = pd.read_parquet(parquet_file)

        print(f'\n--- {sym} ({info.get("name", sym)}) ---')
        new_df = fetch_futures_daily(ak_code)

        if new_df is None or len(new_df) == 0:
            print(f'  [SKIP] 无新数据')
            continue

        new_df['symbol'] = sym
        # 统一 date 列为 datetime64 (避免 str/Timestamp 混存导致 sort_values 失败)
        new_df['date'] = pd.to_datetime(new_df['date'])

        if existing_df is not None and len(existing_df) > 0:
            existing_df['date'] = pd.to_datetime(existing_df['date'])
            last_existing = existing_df['date'].max()
            first_new = new_df['date'].min()
            if first_new <= last_existing:
                mask = new_df['date'] > last_existing
                only_new = new_df[mask].copy()
                if len(only_new) > 0:
                    combined = pd.concat([existing_df, only_new], ignore_index=True)
                    combined = combined.drop_duplicates(subset=['date'], keep='last')
                    combined = combined.sort_values('date').reset_index(drop=True)
                    combined.to_parquet(parquet_file, index=False)
                    print(f'  [UPDATE] 新增{len(only_new)}条 '
                          f'({only_new["date"].min().strftime("%m-%d")}~{only_new["date"].max().strftime("%m-%d")})')
                    results[sym] = {'status': 'updated', 'added': len(only_new),
                                    'total': len(combined)}
                else:
                    print(f'  [UP-TO-DATE] 数据已是最新({last_existing.strftime("%Y-%m-%d")})')
                    results[sym] = {'status': 'current', 'added': 0,
                                    'total': len(existing_df)}
            else:
                combined = pd.concat([existing_df, new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=['date'], keep='last')
                combined = combined.sort_values('date').reset_index(drop=True)
                combined.to_parquet(parquet_file, index=False)
                print(f'  [APPEND] 追加{len(new_df)}条 (总{len(combined)}条)')
                results[sym] = {'status': 'appended', 'added': len(new_df),
                                'total': len(combined)}
        else:
            new_df.to_parquet(parquet_file, index=False)
            print(f'  [NEW] 首次下载({len(new_df)}条)')
            results[sym] = {'status': 'new', 'added': len(new_df),
                            'total': len(new_df)}

        time.sleep(0.5)

    updated_count = sum(1 for v in results.values() if v.get('status') in ('updated', 'new'))
    total_added = sum(v.get('added', 0) for v in results.values())
    print(f'\n--- 更新汇总 ---')
    print(f'  品种: {len(results)}个 | 更新: {updated_count}个 | 新增数据: {total_added}条')
    return results


def get_realtime_price(symbol_code, exchange='CZCE'):
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = ak.futures_zh_spot(symbol=f'{symbol_code}{exchange}')
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            return {
                'symbol': symbol_code,
                'price': float(latest.get('最新价', 0)),
                'high': float(latest.get('最高价', 0)),
                'low': float(latest.get('最低价', 0)),
                'open': float(latest.get('开盘价', 0)),
                'volume': float(latest.get('成交量', 0)),
                'change_pct': float(latest.get('涨跌幅', 0)) / 100 if latest.get('涨跌幅') else 0,
                'timestamp': str(datetime.now()),
            }
    except Exception as e:
        pass
    return None


if __name__ == '__main__':
    update_parquet_data()
