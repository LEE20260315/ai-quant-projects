#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
日终归档与周报
==============

  - 归档：复制 orders.db 到 archive/YYYY-MM-DD_orders.db
  - NAV 快照：读 nav 表写 nav_snapshot_YYYYMMDD.csv
  - 周报：统计本周 PnL/胜率/最大回撤，输出 weekly_report_YYYYWww.md

运行：
  python -m scripts.paper.daily_archive --date 2025-06-05
  python -m scripts.paper.daily_archive --week 2025-W23
"""
import argparse
import csv
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 路径
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "Pricing deviation detection system"))

from paper_trading import config as cfg


logger = logging.getLogger("scripts.paper.archive")


# ==================== 日终归档 ====================
def daily_archive(t_date: str, db_path: str) -> Dict:
    """归档一日数据：复制 DB + 写 NAV snapshot"""
    archive_dir = Path(cfg.ARCHIVE_DIR)
    archive_dir.mkdir(parents=True, exist_ok=True)

    out = {"t_date": t_date, "ok": False}

    # 1. 复制 DB
    db_archive = archive_dir / f"{t_date}_orders.db"
    if Path(db_path).exists():
        shutil.copy2(db_path, db_archive)
        out["db_archive"] = str(db_archive)
        logger.info(f"  归档 DB → {db_archive.name}")
    else:
        out["db_archive"] = None
        logger.warning(f"  DB 不存在: {db_path}")
        return out

    # 2. NAV snapshot CSV
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT t_date, cash, market_value, realized_pnl, unrealized_pnl, total_equity, drawdown, layer2_active, portfolio_stopped FROM nav ORDER BY t_date")
    rows = cur.fetchall()
    conn.close()

    csv_path = archive_dir / f"nav_snapshot_{t_date.replace('-', '')}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_date", "cash", "market_value", "realized_pnl", "unrealized_pnl", "total_equity", "drawdown", "layer2_active", "portfolio_stopped"])
        w.writerows(rows)
    out["csv_path"] = str(csv_path)
    out["nav_rows"] = len(rows)
    logger.info(f"  NAV snapshot → {csv_path.name} ({len(rows)} 行)")

    out["ok"] = True
    return out


# ==================== 周报 ====================
def _week_range(iso_week: str) -> Tuple[str, str]:
    """'2025-W23' → ('2025-06-02', '2025-06-08')"""
    year, w = iso_week.split("-W")
    year = int(year)
    w = int(w)
    # ISO 周一为周首
    fourth_jan = datetime(year, 1, 4)
    delta_to_monday = timedelta(days=fourth_jan.weekday())
    week_start = fourth_jan - delta_to_monday + timedelta(weeks=w - 1)
    week_end = week_start + timedelta(days=6)
    return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")


def weekly_report(iso_week: str, db_path: str) -> Dict:
    """生成本周 PnL/胜率/最大回撤 周报"""
    if not Path(db_path).exists():
        return {"ok": False, "error": f"DB 不存在: {db_path}"}

    start, end = _week_range(iso_week)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. 拉本周 nav
    cur.execute("SELECT t_date, realized_pnl, unrealized_pnl, total_equity, drawdown, layer2_active, portfolio_stopped FROM nav WHERE t_date BETWEEN ? AND ? ORDER BY t_date", (start, end))
    navs = cur.fetchall()
    # 2. 拉本周 fills（按 t_date 范围）
    cur.execute("SELECT fill_id, symbol, direction, qty, price, t_date FROM fills WHERE t_date BETWEEN ? AND ?", (start, end))
    fills = cur.fetchall()
    # 3. 拉本周 orders
    cur.execute("SELECT order_id, symbol, direction, qty, price, status, t_date FROM orders WHERE t_date BETWEEN ? AND ?", (start, end))
    orders = cur.fetchall()
    conn.close()

    # 统计
    total_realized = sum(n[1] for n in navs) if navs else 0
    avg_equity = (sum(n[3] for n in navs) / len(navs)) if navs else cfg.INITIAL_CAPITAL
    max_dd = max((n[4] for n in navs), default=0.0)
    final_equity = navs[-1][3] if navs else cfg.INITIAL_CAPITAL
    pnl_pct = (final_equity - cfg.INITIAL_CAPITAL) / cfg.INITIAL_CAPITAL if navs else 0

    # 胜率（用 fills 表统计：方向反转算 PnL，但简化用 nav realized 平均判断盈亏日）
    profit_days = sum(1 for n in navs if n[1] > 0)
    loss_days = sum(1 for n in navs if n[1] < 0)
    flat_days = len(navs) - profit_days - loss_days
    win_rate = profit_days / len(navs) if navs else 0

    # 闸门触发统计
    layer2_triggers = sum(1 for n in navs if n[5])
    portfolio_stops = sum(1 for n in navs if n[6])

    # 按品种统计成交
    by_symbol: Dict[str, Dict] = {}
    for f in fills:
        s = f[1]
        if s not in by_symbol:
            by_symbol[s] = {"trades": 0, "long": 0, "short": 0}
        by_symbol[s]["trades"] += 1
        if f[2] == "LONG":
            by_symbol[s]["long"] += 1
        else:
            by_symbol[s]["short"] += 1

    # 写周报 Markdown
    week_dir = Path(cfg.WEEKLY_REPORT_DIR)
    week_dir.mkdir(parents=True, exist_ok=True)
    md_path = week_dir / f"weekly_report_{iso_week}.md"

    lines = []
    lines.append(f"# Paper Trading 周报 - {iso_week}")
    lines.append("")
    lines.append(f"周期: {start} ~ {end}    报告生成: {datetime.now():%Y-%m-%d %H:%M}")
    lines.append("")
    lines.append(f"## 核心指标")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 初始资金 | {cfg.INITIAL_CAPITAL:,.0f} |")
    lines.append(f"| 周末权益 | {final_equity:,.0f} |")
    lines.append(f"| 周收益 | {total_realized:+,.0f} ({pnl_pct*100:+.2f}%) |")
    lines.append(f"| 最大回撤 | {max_dd*100:.2f}% |")
    lines.append(f"| 平均权益 | {avg_equity:,.0f} |")
    lines.append(f"| 交易日数 | {len(navs)} |")
    lines.append(f"| 盈利日 / 亏损日 / 持平 | {profit_days} / {loss_days} / {flat_days} |")
    lines.append(f"| 日胜率 | {win_rate*100:.1f}% |")
    lines.append(f"| Layer2 触发次数 | {layer2_triggers} |")
    lines.append(f"| 组合止损触发次数 | {portfolio_stops} |")
    lines.append(f"| 成交单数 | {len(fills)} |")
    lines.append(f"| 订单总数 | {len(orders)} |")
    lines.append("")

    lines.append(f"## 每日 NAV")
    lines.append("")
    lines.append("| 日期 | 权益 | 已实现 PnL | 未实现 PnL | 回撤 | Layer2 | 组合止损 |")
    lines.append("|------|------|-----------|-----------|------|--------|---------|")
    for n in navs:
        t_date, realized, unrealized, equity, dd, l2, ps = n
        lines.append(f"| {t_date} | {equity:,.0f} | {realized:+,.0f} | {unrealized:+,.0f} | {dd*100:.2f}% | {'是' if l2 else '否'} | {'是' if ps else '否'} |")
    lines.append("")

    if by_symbol:
        lines.append(f"## 品种成交分布")
        lines.append("")
        lines.append("| 品种 | 成交笔数 | 做多 | 做空 |")
        lines.append("|------|----------|------|------|")
        for s in sorted(by_symbol.keys()):
            d = by_symbol[s]
            lines.append(f"| {s} | {d['trades']} | {d['long']} | {d['short']} |")
        lines.append("")

    lines.append(f"## 风险提示")
    lines.append("")
    if max_dd >= cfg.PORTFOLIO_STOP_LOSS:
        lines.append(f"⚠️ **组合止损 12% 已被触发**，需复盘策略。")
    elif max_dd >= cfg.LAYER2_TRIGGER:
        lines.append(f"⚠️ 回撤触发 Layer2（{max_dd*100:.2f}% ≥ 10%），需关注敞口控制。")
    else:
        lines.append(f"✓ 本周回撤控制在 Layer2 以下（{max_dd*100:.2f}% < 10%），运行稳健。")
    lines.append("")

    md = "\n".join(lines)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    logger.info(f"  周报 → {md_path.name}")

    return {
        "ok": True,
        "week": iso_week,
        "start": start,
        "end": end,
        "final_equity": final_equity,
        "weekly_pnl": total_realized,
        "pnl_pct": pnl_pct,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "trading_days": len(navs),
        "trades": len(fills),
        "orders": len(orders),
        "md_path": str(md_path),
    }


# ==================== main ====================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="日终归档：YYYY-MM-DD")
    parser.add_argument("--week", help="周报：YYYY-Www（如 2025-W23）")
    parser.add_argument("--db", default=cfg.ORDERS_DB_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format=cfg.LOG_FORMAT, datefmt=cfg.LOG_DATE_FORMAT)

    if args.date:
        result = daily_archive(args.date, args.db)
        print(f"\n归档结果: {result}")
        return 0 if result.get("ok") else 1

    if args.week:
        result = weekly_report(args.week, args.db)
        if result.get("ok"):
            print(f"\n周报摘要:")
            print(f"  周期: {result['start']} ~ {result['end']}")
            print(f"  周收益: {result['weekly_pnl']:+,.0f} ({result['pnl_pct']*100:+.2f}%)")
            print(f"  最大回撤: {result['max_drawdown']*100:.2f}%")
            print(f"  胜率: {result['win_rate']*100:.1f}%")
            print(f"  详情: {result['md_path']}")
        else:
            print(f"周报生成失败: {result}")
        return 0 if result.get("ok") else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
