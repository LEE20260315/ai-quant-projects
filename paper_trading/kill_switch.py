#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
紧急停止开关
================

人工一键停止 Paper Trading + 紧急平仓：
- 写 STOP_PAPER.flag 文件
- live_runner 每次轮询检查该文件
- 检测到时立刻停止接收新信号 + 紧急平仓所有持仓
- 写 EMERGENCY_STOP_<timestamp>.log
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List

from . import config as cfg


logger = logging.getLogger("paper_trading.kill_switch")


def is_stop_requested() -> bool:
    """检查是否触发了紧急停止"""
    return os.path.isfile(cfg.STOP_FLAG_PATH)


def trigger_stop() -> str:
    """主动触发紧急停止（写 STOP_PAPER.flag）"""
    flag = cfg.STOP_FLAG_PATH
    if not os.path.isfile(flag):
        with open(flag, "w") as f:
            f.write(f"STOP_REQUESTED_AT={datetime.now().isoformat(timespec='seconds')}\n")
        logger.warning(f"[KILL] 写停止标志 {flag}")
    return flag


def clear_stop() -> None:
    """清除停止标志（恢复运行）"""
    if os.path.isfile(cfg.STOP_FLAG_PATH):
        os.remove(cfg.STOP_FLAG_PATH)
        logger.info(f"[KILL] 清除停止标志 {cfg.STOP_FLAG_PATH}")


def emergency_flatten(broker, market_prices: dict) -> dict:
    """
    紧急平仓：所有持仓以市价平仓
    Returns: {ts, positions_flattened, total_qty, log_path}
    """
    ts = datetime.now()
    positions = broker.list_open_positions()
    flat_orders = []
    for p in positions:
        close_dir = "SHORT" if p["direction"] == "LONG" else "LONG"
        market_p = market_prices.get(p["symbol"], p["last_price"])
        order_id, status = broker.submit_order(
            symbol=p["symbol"],
            direction=close_dir,
            qty=p["qty"],
            price=market_p,
            t_date=ts.strftime("%Y-%m-%d"),
        )
        flat_orders.append({
            "symbol": p["symbol"],
            "qty": p["qty"],
            "close_direction": close_dir,
            "price": market_p,
            "order_id": order_id,
            "status": status,
        })

    log_path = os.path.join(
        cfg.EMERGENCY_DIR,
        f"EMERGENCY_STOP_{ts.strftime(cfg.TIMESTAMP_FORMAT if hasattr(cfg, 'TIMESTAMP_FORMAT') else '%Y%m%d_%H%M%S')}.log",
    )
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"紧急停止触发时间：{ts.isoformat(timespec='seconds')}\n")
        f.write(f"触发原因：STOP_PAPER.flag 文件存在\n")
        f.write(f"持仓数量：{len(positions)}\n")
        f.write(f"平仓订单：{len(flat_orders)}\n\n")
        for o in flat_orders:
            f.write(f"  {o['symbol']:>4s}  {o['close_direction']:>5s}  {o['qty']:>3d} @ {o['price']:>10.2f}  {o['order_id']:>12s}  {o['status']}\n")
    logger.warning(f"[KILL] 紧急平仓完成：{len(flat_orders)} 单，详见 {log_path}")
    return {
        "timestamp": ts.isoformat(timespec="seconds"),
        "positions_flattened": len(flat_orders),
        "total_qty": sum(o["qty"] for o in flat_orders),
        "log_path": log_path,
        "orders": flat_orders,
    }
