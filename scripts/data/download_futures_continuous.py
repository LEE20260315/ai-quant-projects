#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量下载 20 个主流期货主力连续合约
====================================

数据源：AKShare `futures_main_sina`（新浪财经连续主力合约）
落地：<CTA_RESEARCH_ROOT>/futures/continuous/<SYMBOL>_main.parquet

特性：
- 20 个品种（黑色+有色+贵金属+农产品+化工+能源+金融）
- 限流 0.5s/请求，失败重试 3 次
- 增量更新（断点续传）：若 Parquet 已存在，仅补齐缺失日期
- 列名统一为 date/open/high/low/close/volume
- 写 download_log_<timestamp>.json 记录下载明细
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 路径：项目根目录 + 子项目根目录
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # scripts/ 的父目录就是项目根
_PRICING_ROOT = _PROJECT_ROOT / "Pricing deviation detection system"
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PRICING_ROOT))

# 复用 stress 套件的 config
from tests.stress import config as stress_config


# 20 个主流期货品种
SYMBOLS_20 = [
    # 黑色 + 有色 + 贵金属（6）
    ("RB",  "螺纹钢"),
    ("I",   "铁矿石"),
    ("CU",  "铜"),
    ("AU",  "黄金"),
    ("AG",  "白银"),
    ("NI",  "镍"),
    # 农产品（6）
    ("Y",   "豆油"),
    ("P",   "棕榈油"),
    ("M",   "豆粕"),
    ("C",   "玉米"),
    ("SR",  "白糖"),
    ("CF",  "棉花"),
    # 化工 + 能源（7）
    ("TA",  "PTA"),
    ("MA",  "甲醇"),
    ("FG",  "玻璃"),
    ("SA",  "纯碱"),
    ("RU",  "橡胶"),
    ("BU",  "沥青"),
    ("FU",  "燃料油"),
    # 金融（1）
    ("IF",  "沪深300股指"),
]


def _fetch_one(symbol: str, start: str, end: str, max_retry: int = 3) -> Optional[pd.DataFrame]:
    """从 AKShare 拉取一个品种的主力连续合约"""
    import akshare as ak

    ak_symbol = f"{symbol}0"  # 新浪源用 0 后缀表示连续主力
    last_err: Optional[Exception] = None

    for attempt in range(1, max_retry + 1):
        try:
            df = ak.futures_main_sina(symbol=ak_symbol, start_date=start, end_date=end)
            if df is None or df.empty:
                return None

            # 新浪列名 → 统一列名
            rename = {
                "日期": "date",
                "开盘价": "open",
                "最高价": "high",
                "最低价": "low",
                "收盘价": "close",
                "成交量": "volume",
            }
            df = df.rename(columns=rename)
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

            # 只保留我们关心的列
            keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
            df = df[keep].copy()

            # 统一类型
            for c in ["open", "high", "low", "close", "volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            df = df.dropna(subset=["date", "close"]).reset_index(drop=True)
            return df
        except Exception as e:
            last_err = e
            if attempt < max_retry:
                wait = 2 ** attempt
                print(f"    ⚠ {ak_symbol} 第 {attempt} 次失败（{type(e).__name__}: {e}），{wait}s 后重试")
                time.sleep(wait)
            else:
                print(f"    ✗ {ak_symbol} 失败 {max_retry} 次：{e}")
    return None


def _save_parquet(df: pd.DataFrame, path: str) -> None:
    """保存为 Parquet，自动建目录"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _load_existing(path: str) -> Optional[pd.DataFrame]:
    """读取已存在的 Parquet（用于增量）"""
    if not os.path.isfile(path):
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _merge_incremental(new_df: pd.DataFrame, existing_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """合并新旧数据，去重"""
    if existing_df is None or existing_df.empty:
        return new_df
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"], keep="last")
    combined = combined.sort_values("date").reset_index(drop=True)
    return combined


def _resolve_out_dir() -> str:
    """解析输出目录"""
    root = stress_config.get_cta_research_root()
    out = os.path.join(root, "futures", "continuous")
    Path(out).mkdir(parents=True, exist_ok=True)
    return out


def _log_path() -> str:
    """日志目录与文件"""
    log_dir = str(_THIS_DIR)
    ts = datetime.now().strftime(stress_config.TIMESTAMP_FORMAT)
    return os.path.join(log_dir, f"download_log_{ts}.json")


def run(symbols: List[str], start: str, end: str, sleep_s: float, log_path: str) -> Dict:
    """主入口"""
    out_dir = _resolve_out_dir()
    print("=" * 60)
    print("批量下载 20 个主流期货主力连续合约")
    print("=" * 60)
    print(f"数据源:     AKShare.futures_main_sina（新浪）")
    print(f"落地目录:   {out_dir}")
    print(f"时间窗口:   {start} ~ {end}")
    print(f"限流间隔:   {sleep_s}s/请求")
    print(f"品种清单:   {len(symbols)} 个")
    print("-" * 60)

    log: Dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "data_source": "akshare.futures_main_sina",
        "window": {"start": start, "end": end},
        "out_dir": out_dir,
        "results": [],
        "failed": [],
        "succeeded": 0,
        "skipped": 0,
    }

    for idx, sym in enumerate(symbols, 1):
        out_path = os.path.join(out_dir, f"{sym}_main.parquet")
        print(f"[{idx:>2}/{len(symbols)}] {sym:>4s} 拉取中 ...", end="", flush=True)

        t0 = time.time()
        try:
            df = _fetch_one(sym, start, end)
            if df is None or df.empty:
                print(f"  ✗ 返回空数据")
                log["failed"].append({"symbol": sym, "reason": "empty_data"})
                time.sleep(sleep_s)
                continue

            existing = _load_existing(out_path)
            if existing is not None:
                old_rows = len(existing)
                merged = _merge_incremental(df, existing)
                new_rows = len(merged) - old_rows
                mode = f"增量(+{new_rows})"
            else:
                merged = df
                mode = "全量"

            _save_parquet(merged, out_path)
            dt = time.time() - t0
            print(f"  ✓ {len(merged):>4} 行  {mode}  耗时 {dt:.1f}s")
            log["results"].append({
                "symbol": sym,
                "rows": int(len(merged)),
                "min_date": str(merged["date"].min()),
                "max_date": str(merged["date"].max()),
                "mode": mode,
                "duration_sec": round(dt, 1),
            })
            log["succeeded"] += 1
        except Exception as e:
            print(f"  ✗ 异常：{e}")
            log["failed"].append({"symbol": sym, "reason": str(e)})

        time.sleep(sleep_s)

    # 汇总
    log["total"] = len(symbols)
    log["success_rate"] = round(log["succeeded"] / max(1, len(symbols)) * 100, 1)

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"  ✓ 成功: {log['succeeded']:>2} / {log['total']}  ({log['success_rate']}%)")
    if log["failed"]:
        print(f"  ✗ 失败: {[x['symbol'] for x in log['failed']]}")
    print(f"  日志: {log_path}")
    print("=" * 60)
    return log


def main():
    parser = argparse.ArgumentParser(description="批量下载 20 个主流期货主力连续合约")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end",   default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="指定品种子集（默认全部 20 个）")
    parser.add_argument("--sleep", type=float, default=0.5, help="限流秒数")
    args = parser.parse_args()

    # 校验 CTA Research 根目录
    try:
        stress_config.ensure_cta_research_exists()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(2)

    symbols = args.symbols or [s for s, _ in SYMBOLS_20]
    # 大写
    symbols = [s.upper() for s in symbols]

    # 限流不能低于 0.3s（避免新浪限流）
    sleep_s = max(0.3, args.sleep)
    log_path = _log_path()
    run(symbols, args.start, args.end, sleep_s, log_path)


if __name__ == "__main__":
    main()
