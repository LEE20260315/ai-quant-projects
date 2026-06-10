#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""补 RM（菜粕）到 cta_research 的下载脚本"""
import os
import sys
import pandas as pd

try:
    import akshare as ak
except ImportError:
    print("ERROR: akshare 未安装")
    sys.exit(1)

OUT = r"C:\Users\MR.Dong\OneDrive\My Project\cta_research\futures\continuous\RM_main.parquet"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

print("=" * 60)
print("下载 RM（菜粕）主力连续合约")
print("=" * 60)

try:
    df = ak.futures_main_sina(symbol="RM0", start_date="20150101", end_date="20260609")
except Exception as e:
    print(f"AKShare 调用失败: {e}")
    print("尝试备用: futures_zh_daily_sina")
    try:
        df = ak.futures_zh_daily_sina(symbol="RM0")
        if df is not None and len(df) > 0:
            df = df.rename(columns={"date": "date"})
    except Exception as e2:
        print(f"备用也失败: {e2}")
        sys.exit(1)

if df is None or len(df) == 0:
    print("ERROR: 拉取 RM 数据为空")
    sys.exit(1)

print(f"原始行数: {len(df)}")
print(f"原始列名: {df.columns.tolist()}")

col_map = {
    "日期": "date", "开盘价": "open", "最高价": "high",
    "最低价": "low", "收盘价": "close", "成交量": "volume",
    "持仓量": "hold", "动态结算价": "settle",
}
df = df.rename(columns=col_map)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)
for c in ["open", "high", "low", "close", "volume", "hold", "settle"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
df["symbol"] = "RM"

df.to_parquet(OUT, index=False)
print(f"✅ 已保存: {OUT}")
print(f"   行数: {len(df)}")
print(f"   范围: {df['date'].min()} ~ {df['date'].max()}")
print(f"   缺失: open={df['open'].isna().sum()}, close={df['close'].isna().sum()}")
