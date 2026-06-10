#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 3 品种信号 (TA + RM + MA) — 不写 state, 不发邮件, 不联网拉数据"""
import sys
import os
from datetime import datetime, timedelta

import os
# 让 `data.parquet_loader` 相对导入能找到
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(r"c:\Users\MR.Dong\OneDrive\My Project\ai-quant-projects-merged\path2_lightweight")
sys.path.insert(0, r".")

from live_tracker import LiveTracker, PARAMS as P
from data.parquet_loader import calc_percentile_rank, calc_ema, calc_atr, calc_sma

tracker = LiveTracker()
print("=" * 60)
print("3 品种信号验证 (TA + RM + MA) — 不联网, 跑本地 parquet")
print("=" * 60)
print(f"PARAMS: window={P.percentile_window}, long<{P.long_entry_pct}, short>{P.short_entry_pct}")
print(f"trend: long>{P.trend_pct_rank_high}, short<{P.trend_pct_rank_low}")
print(f"当前 state: v={tracker.state.get('version')} capital={tracker.state.get('capital')} positions={len(tracker.state['positions'])}")
print()

end_date = "20260608"
start_date = (datetime(2026, 6, 8) - timedelta(days=120)).strftime("%Y-%m-%d")

for sym in ["TA", "RM", "MA"]:
    try:
        df = tracker.loader.load_symbol(sym, start_date, end_date)
        if df is None or len(df) < 60:
            print(f"  {sym}: 数据不足 ({len(df) if df is not None else 0} 行)")
            continue
        df["pct_rank"] = calc_percentile_rank(df["close"], P.percentile_window)
        df["ema50"] = calc_ema(df["close"], 50)
        df["ema20"] = calc_ema(df["close"], 20)
        df["atr"] = calc_atr(df, 14)
        df["atr_ma"] = calc_sma(df["atr"], 20)
        last = df.iloc[-1]
        up50 = "上" if last["close"] > last["ema50"] else "下"
        up_ema20_50 = "上" if last["ema20"] > last["ema50"] else "下"
        print(f"  {sym}:")
        print(f"    日期={last['date']}, 收盘={last['close']}, ATR={last['atr']:.0f}")
        print(f"    PctRank={last['pct_rank']:.2f} | close vs ema50: {up50} | ema20 vs ema50: {up_ema20_50}")
        sig_long = (last["pct_rank"] < P.long_entry_pct) and (last["close"] > last["ema50"])
        sig_short = (last["pct_rank"] > P.short_entry_pct) and (last["close"] < last["ema50"])
        sig_trend_long = (last["pct_rank"] > P.trend_pct_rank_high) and (last["close"] > last["ema50"]) and (last["ema20"] > last["ema50"]) and (last["atr"] > last["atr_ma"])
        sig_trend_short = (last["pct_rank"] < P.trend_pct_rank_low) and (last["close"] < last["ema50"]) and (last["ema20"] < last["ema50"]) and (last["atr"] > last["atr_ma"])
        print(f"    信号: revert_long={sig_long}, revert_short={sig_short}, trend_long={sig_trend_long}, trend_short={sig_trend_short}")
    except Exception as e:
        print(f"  {sym}: 异常 {type(e).__name__}: {e}")
    print()
