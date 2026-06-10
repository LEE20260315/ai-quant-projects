#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
openctp 真实联调脚本 (SimNow)
============================

跑法 (PowerShell)::

    # 第一套环境 (交易时段)
    $env:CTP_FRONT_ADDR   = "tcp://182.254.243.31:30001"
    $env:CTP_BROKER_ID    = "9999"
    $env:CTP_APP_ID       = "simnow_client_test"
    $env:CTP_AUTH_CODE    = "0000000000000000"
    $env:CTP_INVESTOR_ID  = "你的SimNow账号"
    $env:CTP_PASSWORD     = "你的SimNow密码"
    python execution/openctp_smoke.py

无 SimNow 账号 (只想测链路):::

    python execution/openctp_smoke.py --dry

SimNow 注册要点 (2025/06/19 之后):
    1) 打开 https://www.simnow.com.cn/ 注册 (免费)
    2) 默认 AppID = "simnow_client_test", AuthCode = "0000000000000000" (16 个 0)
    3) **首次登录前必须先在 SimNow 首页 "重置密码"** (否则 4097: 客户端认证失败)
    4) 7x24 前置: 182.254.243.31:40001 (任何时间可连, 但需等到第三个交易日才能用)

前置地址 (看穿式 / 生产秘钥):
    第一套: 182.254.243.31:30001 / 30002 / 30003 (交易)
    7x24 : 182.254.243.31:40001
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# 把项目根加入 sys.path, 让 common.* 可被 import
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from common.execution.ctp_broker import OpenCtpBroker, build_broker


def need(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        print(f"[!] 环境变量 {name} 未设置 (或 --dry 时可省略)")
    return val


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="只做 import/构造, 不连 SimNow")
    p.add_argument("--symbol", default="TA2506")
    p.add_argument("--direction", choices=["long", "short"], default="long")
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--price", type=float, default=5000.0)
    p.add_argument("--query", action="store_true", help="只查持仓不下单")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("openctp-smoke")

    cfg = {
        "mode": "openctp",
        # SimNow 2025/06/19 之后的新看穿式前置 (生产秘钥)
        "front_addr":   need("CTP_FRONT_ADDR") or "tcp://182.254.243.31:30001",
        "broker_id":    need("CTP_BROKER_ID") or "9999",
        "app_id":       need("CTP_APP_ID") or "simnow_client_test",
        "auth_code":    need("CTP_AUTH_CODE") or "0000000000000000",
        "investor_id":  need("CTP_INVESTOR_ID") or "demo",
        "password":     need("CTP_PASSWORD") or "demo",
        "flow_path":    os.environ.get("CTP_FLOW_PATH", "./ctp_flow/"),
        "timeout":      float(os.environ.get("CTP_TIMEOUT", "10.0")),
    }
    log.info("CTP 配置: %s", {k: v for k, v in cfg.items() if k != "password"})

    if args.dry:
        log.info("[DRY] 仅 import / 构造, 不连前置")
        broker = build_broker(cfg)
        log.info("构造成功: %s", type(broker).__name__)
        return

    broker: OpenCtpBroker = build_broker(cfg)
    if not broker.connect():
        log.error("连接 SimNow 失败, 请检查: 1) 网络 2) AppID/AuthCode 3) 客户号/密码")
        sys.exit(1)

    if args.query:
        positions = broker.query_positions()
        log.info("持仓: %s", positions)
        return

    # 下一单
    order_id = broker.send_order({
        "symbol": args.symbol,
        "direction": args.direction,
        "lots": args.lots,
        "price": args.price,
        "order_type": "limit",
        "offset": "open",
    })
    log.info("下单成功 order_id=%s", order_id)
    log.info("等待 2 秒收回报...")
    import time
    time.sleep(2.0)
    log.info("委托状态: %s", broker._orders.get(order_id))
    log.info("当前持仓: %s", broker.query_positions())


if __name__ == "__main__":
    main()
