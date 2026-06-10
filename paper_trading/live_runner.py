#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
日内自动运行器
================

交易时段内（9:00-11:30 + 13:00-15:00）每 5 分钟：
  1. 拉 AKShare 最新价
  2. 跑扫描器拿信号
  3. 风控闸门检查
  4. 调 sim_broker 下单
  5. 写 runner_<date>.log

干跑模式 --dry-run：不调 sim_broker，只记录信号
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 路径
_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent))             # 项目根
sys.path.insert(0, str(_THIS_DIR.parent / "Pricing deviation detection system"))  # 子项目

from . import config as cfg
from . import risk_gate, kill_switch
from .risk_gate import RiskGate, _attach_latest_nav_helper
from .sim_broker import SimBroker
from .kill_switch import is_stop_requested, emergency_flatten


# ==================== 日志 ====================
def _setup_logging(date_str: str):
    log_file = os.path.join(cfg.LOG_DIR, f"runner_{date_str}.log")
    logging.basicConfig(
        level=logging.INFO,
        format=cfg.LOG_FORMAT,
        datefmt=cfg.LOG_DATE_FORMAT,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("paper_trading.live_runner")


# ==================== 拉取最新价 ====================
def _fetch_latest_prices(symbols: List[str]) -> Dict[str, float]:
    """从 AKShare 拉取每个品种的最新价（主力连续合约）"""
    import akshare as ak
    prices: Dict[str, float] = {}
    for sym in symbols:
        try:
            ak_sym = f"{sym}0"
            df = ak.futures_main_sina(symbol=ak_sym)
            if df is not None and not df.empty and "收盘价" in df.columns:
                prices[sym] = float(df["收盘价"].iloc[-1])
        except Exception as e:
            logging.getLogger("paper_trading.live_runner").debug(f"  拉 {sym} 失败：{e}")
    return prices


# ==================== 信号生成（占位）====================
def _generate_signals(prices: Dict[str, float]) -> List[Dict]:
    """
    占位信号：每次轮询随机给 1-2 个做多信号
    实际应替换为 scan_real_signal(prices) -> List[Signal]
    """
    import random
    rng = random.Random()
    syms = list(prices.keys())
    if not syms:
        return []
    n = rng.randint(0, 2)
    sigs = []
    for _ in range(n):
        sym = rng.choice(syms)
        sigs.append({
            "symbol": sym,
            "direction": rng.choice(["LONG", "SHORT"]),
            "qty": 1,
            "price": prices[sym],
        })
    return sigs


# ==================== 主循环 ====================
def _main_loop(dry_run: bool, date_str: str, logger) -> None:
    """单日主循环"""
    broker = SimBroker()
    _attach_latest_nav_helper(broker)
    gate = RiskGate(initial_capital=cfg.INITIAL_CAPITAL)
    symbols = list(cfg.CONTRACT_PARAMS.keys())

    logger.info(f"=" * 60)
    logger.info(f"开始日 {date_str} {'(DRY RUN)' if dry_run else '(LIVE)'}")
    logger.info(f"  监控品种: {len(symbols)} 个")
    logger.info(f"  轮询间隔: {cfg.POLL_INTERVAL_SEC}s")
    logger.info(f"  初始资金: {cfg.INITIAL_CAPITAL:,.0f}")
    logger.info(f"=" * 60)

    poll_count = 0
    last_prices: Dict[str, float] = {}
    while True:
        now = datetime.now()
        if not cfg.in_trading_session(now.hour, now.minute) and not dry_run:
            # 非交易时段，做日终（dry_run 模式无视时段）
            logger.info(f"[{now:%H:%M}] 非交易时段，结算日终")
            break

        # 紧急停止检查
        if is_stop_requested():
            logger.warning("[KILL] 检测到 STOP_PAPER.flag，紧急平仓...")
            report = emergency_flatten(broker, last_prices)
            logger.warning(f"  平仓 {report['positions_flattened']} 单，详情：{report['log_path']}")
            return

        # 拉数据
        poll_count += 1
        logger.info(f"[{now:%H:%M}] 轮询 #{poll_count}")
        try:
            last_prices = _fetch_latest_prices(symbols)
            if last_prices:
                logger.info(f"  拉到 {len(last_prices)} 个品种最新价")
            else:
                logger.warning(f"  拉价失败（可能 AKShare 限流），下轮再试")
                if dry_run:
                    # 干跑模式拿不到价就退出
                    logger.error(f"  DRY-RUN 终止：无法获取任何品种最新价")
                    return
                time.sleep(cfg.POLL_INTERVAL_SEC)
                continue
        except Exception as e:
            logger.error(f"  拉价异常：{e}")
            if dry_run:
                return
            time.sleep(cfg.POLL_INTERVAL_SEC)
            continue

        # 单笔止损扫描
        try:
            to_close = gate.check_single_stop(broker)
            for c in to_close:
                logger.warning(f"  [SINGLE-STOP] {c['symbol']} {c['reason']}，自动平仓")
                if not dry_run:
                    broker.submit_order(
                        symbol=c["symbol"],
                        direction=c["close_direction"],
                        qty=c["qty"],
                        price=last_prices.get(c["symbol"], 0),
                        t_date=date_str,
                    )
        except Exception as e:
            logger.error(f"  单笔止损扫描异常：{e}")

        # 出信号
        signals = _generate_signals(last_prices)
        logger.info(f"  收到 {len(signals)} 个信号")
        for sig in signals:
            ok, reason = gate.pre_trade_check(broker, sig["symbol"], sig["direction"], sig["qty"], sig["price"])
            if not ok:
                logger.info(f"  [GATE] {sig['symbol']} {sig['direction']} 拒单：{reason}")
                continue
            if dry_run:
                logger.info(f"  [DRY] WOULD SUBMIT {sig}")
            else:
                oid, status = broker.submit_order(
                    symbol=sig["symbol"],
                    direction=sig["direction"],
                    qty=sig["qty"],
                    price=sig["price"],
                    t_date=date_str,
                    risk_gate=gate,
                )
                logger.info(f"  [ORDER] {oid} {sig['symbol']} {sig['direction']} {status}")

        # dry_run 模式：跑一轮就退出
        if dry_run:
            logger.info(f"[DRY] 单轮完成，退出")
            break

        time.sleep(cfg.POLL_INTERVAL_SEC)

    # 日终结算
    if not dry_run and last_prices:
        nav = broker.settle(t_date=date_str, last_prices=last_prices)
        gate.state.layer2_active = nav["drawdown"] >= cfg.LAYER2_TRIGGER
        gate.state.portfolio_stopped = nav["drawdown"] >= cfg.PORTFOLIO_STOP_LOSS
        broker.update_nav_flags(date_str, gate.state.layer2_active, gate.state.portfolio_stopped)
        logger.info(f"[SETTLE] 权益={nav['total_equity']:,.0f} 回撤={nav['drawdown']*100:.2f}%")


# ==================== CLI ====================
def main():
    parser = argparse.ArgumentParser(description="Paper Trading 日内自动运行器")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="干跑：只记录信号，不下单")
    args = parser.parse_args()

    logger = _setup_logging(args.date)
    _main_loop(args.dry_run, args.date, logger)


if __name__ == "__main__":
    main()
