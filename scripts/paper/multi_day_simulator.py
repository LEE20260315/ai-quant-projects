#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
连续多日 Paper Trading 模拟器
==============================

按日期列表跑多日 paper trading，每日内：
  1. 拉价（AKShare）
  2. 出信号（占位随机）
  3. 风控闸门
  4. 下单（PENDING）
  5. 下一交易日日初撮合 + 结算

用于快速验证周报格式与多日 NAV 连续性。

运行：
  python -m scripts.paper.multi_day_simulator 2025-06-03 2025-06-04 2025-06-05
"""
import argparse
import logging
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# 路径
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "Pricing deviation detection system"))

from paper_trading import config as cfg
from paper_trading.sim_broker import SimBroker
from paper_trading.risk_gate import RiskGate, _attach_latest_nav_helper


# ==================== 拉价（指定日期）====================
def _fetch_prices_on_date(symbols: List[str], date_str: str) -> Dict[str, float]:
    """从 parquet 取指定日期收盘价"""
    prices: Dict[str, float] = {}
    cta_root = Path(os.environ.get("CTA_RESEARCH_ROOT", r"C:\Users\MR.Dong\OneDrive\My Project\cta_research"))
    pq_dir = cta_root / "futures" / "continuous"
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    import pandas as pd
    for sym in symbols:
        try:
            pq = pq_dir / f"{sym}_main.parquet"
            if not pq.exists():
                continue
            df = pd.read_parquet(pq)
            if df.empty:
                continue
            # 找日期列
            date_col = None
            for col in ("date", "datetime", "日期", "时间"):
                if col in df.columns:
                    date_col = col
                    break
            if date_col is None:
                continue
            df[date_col] = pd.to_datetime(df[date_col])
            # 找 date_str 当天或前一个交易日的收盘价
            mask = df[date_col] <= target_dt
            if not mask.any():
                continue
            row = df.loc[mask].iloc[-1]
            for col in ("close", "收盘", "收盘价"):
                if col in df.columns:
                    prices[sym] = float(row[col])
                    break
        except Exception as e:
            logging.getLogger("paper_trading.sim").debug(f"  {sym} 拉价失败: {e}")
    return prices


# ==================== 简化信号生成 ====================
def _gen_random_signals(prices: Dict[str, float], rng: random.Random) -> List[Dict]:
    """每个品种 30% 概率出 1 个信号"""
    sigs = []
    for sym, p in prices.items():
        if rng.random() < 0.3:
            sigs.append({
                "symbol": sym,
                "direction": rng.choice(["LONG", "SHORT"]),
                "qty": 1,
                "price": p,
            })
    return sigs


# ==================== 单日模拟 ====================
def simulate_one_day(broker: SimBroker, gate: RiskGate, date_str: str,
                     symbols: List[str], rng: random.Random) -> Dict:
    """模拟一日：拉价 → 信号 → 下单（次日撮合）→ 当日不下单则无结算"""
    logger = logging.getLogger("paper_trading.sim")
    logger.info(f"--- Day {date_str} ---")

    prices = _fetch_prices_on_date(symbols, date_str)
    if not prices:
        logger.warning(f"  无价格数据，跳过")
        return {"date": date_str, "prices": 0, "signals": 0, "submitted": 0, "nav": None}

    logger.info(f"  拉到 {len(prices)} 个品种价格")

    # 信号
    signals = _gen_random_signals(prices, rng)
    submitted = 0
    for sig in signals:
        ok, reason = gate.pre_trade_check(broker, sig["symbol"], sig["direction"], sig["qty"], sig["price"])
        if not ok:
            logger.info(f"  [GATE] {sig['symbol']} 拒: {reason}")
            continue
        oid, status = broker.submit_order(
            symbol=sig["symbol"],
            direction=sig["direction"],
            qty=sig["qty"],
            price=sig["price"],
            t_date=date_str,
        )
        if status == "PENDING":
            submitted += 1
    logger.info(f"  收到 {len(signals)} 信号，下单 {submitted} 单")

    return {"date": date_str, "prices": len(prices), "signals": len(signals), "submitted": submitted, "nav": None}


def settle_one_day(broker: SimBroker, gate: RiskGate, date_str: str,
                   symbols: List[str]) -> Dict:
    """撮合 + 结算（次日开盘价撮合）"""
    logger = logging.getLogger("paper_trading.sim")
    prices = _fetch_prices_on_date(symbols, date_str)
    if not prices:
        logger.warning(f"  撮合日 {date_str} 无价格")
        return {}
    nav = broker.settle(t_date=date_str, last_prices=prices)
    gate.state.layer2_active = nav["drawdown"] >= cfg.LAYER2_TRIGGER
    gate.state.portfolio_stopped = nav["drawdown"] >= cfg.PORTFOLIO_STOP_LOSS
    broker.update_nav_flags(date_str, gate.state.layer2_active, gate.state.portfolio_stopped)
    logger.info(f"  结算: 权益={nav['total_equity']:,.0f} 回撤={nav['drawdown']*100:.2f}% realized={nav['realized_pnl']:+,.0f}")
    return nav


# ==================== main ====================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dates", nargs="+", help="日期列表 YYYY-MM-DD（最后一日只撮合不新下单）")
    parser.add_argument("--db", default=os.path.join(cfg.ORDERS_DB_PATH),
                        help="指定 DB 路径（默认共享 orders.db；测试用临时 DB）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=cfg.LOG_FORMAT,
        datefmt=cfg.LOG_DATE_FORMAT,
    )
    logger = logging.getLogger("paper_trading.sim")

    # 准备 DB
    if args.db != cfg.ORDERS_DB_PATH and os.path.exists(args.db):
        os.remove(args.db)

    broker = SimBroker(db_path=args.db, initial_capital=cfg.INITIAL_CAPITAL)
    _attach_latest_nav_helper(broker)
    gate = RiskGate(initial_capital=cfg.INITIAL_CAPITAL)
    rng = random.Random(args.seed)
    symbols = list(cfg.CONTRACT_PARAMS.keys())

    logger.info(f"=" * 60)
    logger.info(f"多日模拟器")
    logger.info(f"  日期: {args.dates}")
    logger.info(f"  DB: {args.db}")
    logger.info(f"  种子: {args.seed}")
    logger.info(f"=" * 60)

    # 每天循环：撮合前一日 PENDING + 用当日价结算 + 下当日 PENDING
    prev_date = None
    for d in args.dates:
        if prev_date is not None:
            # 撮合前一日 PENDING + 结算前一日（用当前日期的价）
            logger.info(f"--- Settle {prev_date}（用 {d} 的价）---")
            settle_one_day(broker, gate, prev_date, symbols)
        # 当日：拉价 + 下单（PENDING）
        simulate_one_day(broker, gate, d, symbols, rng)
        prev_date = d

    # 最后一日：直接用最后一日的价结算
    if prev_date:
        logger.info(f"--- Settle {prev_date}（最后一日）---")
        settle_one_day(broker, gate, prev_date, symbols)

    # 读最终权益
    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    cur.execute("SELECT total_equity FROM nav ORDER BY t_date DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    final_eq = row[0] if row else cfg.INITIAL_CAPITAL
    logger.info(f"=" * 60)
    logger.info(f"模拟完成。最终权益: {final_eq:,.0f}")
    logger.info(f"=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
