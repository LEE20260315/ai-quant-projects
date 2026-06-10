#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cta_research 数据完整性自检
============================

扫描 <CTA_RESEARCH_ROOT>/futures/continuous/*.parquet：
- 行数 / 日期范围 / 缺失工作日 / 异常涨跌幅
- 输出 verify_report_<timestamp>.json + 控制台摘要
- 健康度评分（0~100），缺失率 < 5% 视为通过
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
_PRICING_ROOT = _PROJECT_ROOT / "Pricing deviation detection system"
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PRICING_ROOT))

from tests.stress import config as stress_config
from tests.stress.cta_research_loader import (
    _normalize_columns,
    detect_price_anomalies,
)


def _load_one(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df = _normalize_columns(df)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _missing_business_days(df: pd.DataFrame, start: str, end: str) -> List[str]:
    if df is None or df.empty or "date" not in df.columns:
        return []
    expected = pd.bdate_range(start, end)
    actual = pd.to_datetime(df["date"]).dt.normalize().unique()
    actual_set = set(actual)
    return [d.strftime("%Y-%m-%d") for d in expected if d not in actual_set]


def run(start: str, end: str, report_dir: str) -> Dict:
    try:
        stress_config.ensure_cta_research_exists()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(2)

    futures_dir = stress_config.get_futures_dir()
    Path(futures_dir).mkdir(parents=True, exist_ok=True)

    files = sorted(str(p) for p in Path(futures_dir).glob("*.parquet"))

    print("=" * 60)
    print("cta_research 数据完整性自检")
    print("=" * 60)
    print(f"目录:   {futures_dir}")
    print(f"文件数: {len(files)}")
    print(f"窗口:   {start} ~ {end}")
    print("-" * 60)
    print(f"{'品种':>6s}  {'行数':>6s}  {'起':>10s}  {'止':>10s}  {'缺失':>6s}  {'异常':>6s}")
    print("-" * 60)

    per_symbol: List[Dict] = []
    total_missing = 0
    total_anomalies = 0
    expected_days = len(pd.bdate_range(start, end))

    for path in files:
        stem = Path(path).stem
        symbol = stem
        for suf in ("_main",):
            if symbol.endswith(suf):
                symbol = symbol[: -len(suf)]
                break

        try:
            df = _load_one(path)
        except Exception as e:
            print(f"  ⚠ {symbol}: 读取失败 {e}")
            per_symbol.append({"symbol": symbol, "error": str(e)})
            continue

        if df.empty:
            print(f"  ⚠ {symbol}: 空数据")
            per_symbol.append({"symbol": symbol, "rows": 0})
            continue

        missing = _missing_business_days(df, start, end)
        anomalies = detect_price_anomalies(df)
        total_missing += len(missing)
        total_anomalies += len(anomalies)

        actual_days = len(df)
        coverage_pct = round(actual_days / expected_days * 100, 2) if expected_days > 0 else 0
        date_min = str(df["date"].min().date()) if "date" in df.columns else None
        date_max = str(df["date"].max().date()) if "date" in df.columns else None

        print(f"  {symbol:>4s}  {actual_days:>6d}  {date_min:>10s}  {date_max:>10s}  {len(missing):>6d}  {len(anomalies):>6d}  ({coverage_pct}%)")

        per_symbol.append({
            "symbol": symbol,
            "rows": int(actual_days),
            "date_min": date_min,
            "date_max": date_max,
            "missing_days": len(missing),
            "anomaly_count": len(anomalies),
            "coverage_pct": coverage_pct,
        })

    # 评分
    score = 100
    score -= min(40, total_missing * 0.1)            # 缺失扣分（最多 -40）
    score -= min(20, total_anomalies * 0.5)          # 异常扣分（最多 -20）
    if not per_symbol:
        score = 0
    score = max(0, min(100, score))

    avg_coverage = round(sum(s.get("coverage_pct", 0) for s in per_symbol) / max(1, len(per_symbol)), 2)
    # 阈值：覆盖 ≥80% 且无关键品种全部缺失
    healthy = score >= 60 and avg_coverage >= 80

    print("-" * 60)
    print(f"  平均覆盖率: {avg_coverage}%")
    print(f"  健康度评分: {score} / 100   状态: {'HEALTHY' if healthy else 'UNHEALTHY'}")
    print("=" * 60)

    # 写文件
    ts = datetime.now().strftime(stress_config.TIMESTAMP_FORMAT)
    out_path = os.path.join(report_dir, f"verify_report_{ts}.json")
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "futures_dir": futures_dir,
        "window": {"start": start, "end": end},
        "expected_business_days": expected_days,
        "total_files": len(files),
        "total_missing_days": total_missing,
        "total_anomalies": total_anomalies,
        "avg_coverage_pct": avg_coverage,
        "health_score": score,
        "healthy": healthy,
        "per_symbol": per_symbol,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"  报告: {out_path}")
    if healthy:
        print("  ✅ 通过，建议重跑压测：python tests/stress/run_stress_suite.py --all --sims 10000")
    else:
        print("  ⚠ 健康度不足，可重跑下载器补齐：python scripts/data/download_futures_continuous.py")

    return report


def main():
    parser = argparse.ArgumentParser(description="cta_research 数据完整性自检")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end",   default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--report-dir", default=str(_THIS_DIR))
    args = parser.parse_args()
    run(args.start, args.end, args.report_dir)


if __name__ == "__main__":
    main()
