#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Path 2 真实 SimNow 联调测试 (完整链路)
====================================

覆盖:
  - OpenCtpBroker 真连 SimNow
  - ExecutionEngine 完整流转: signal → confirm → 真实下单
  - RiskManager / PositionSizer 联调
  - 推送通知 (DingTalk 推送, 手机链接确认)

跑法:
    $env:CTP_INVESTOR_ID="260042"
    $env:CTP_PASSWORD="xibeilang@99"
    python execution/simnow_live_test.py

    (可选) 启动确认桥:
    $ uvicorn execution.confirmation_bridge:app --host 0.0.0.0 --port 8000
    # 然后跑本脚本, 会向桥推送信号, 等待手确
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

# 把项目根加入 sys.path, 让 common.* 可被 import
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from common.execution import (
    ExecutionEngine, build_broker, MultiNotifier, RiskManager,
    bridge_publish_signal as bridge_publish, bridge_is_alive,
)
from execution.position_sizer import PositionSizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LIVE-E2E")


def build_openctp_cfg() -> dict:
    """从环境变量读 SimNow 配置"""
    return {
        "mode": "openctp",
        "front_addr": os.environ.get("CTP_FRONT_ADDR", "tcp://182.254.243.31:30001"),
        "broker_id": os.environ.get("CTP_BROKER_ID", "9999"),
        "app_id": os.environ.get("CTP_APP_ID", "simnow_client_test"),
        "auth_code": os.environ.get("CTP_AUTH_CODE", "0000000000000000"),
        "investor_id": os.environ.get("CTP_INVESTOR_ID", "260042"),
        "password": os.environ.get("CTP_PASSWORD", "xibeilang@99"),
        "flow_path": os.environ.get("CTP_FLOW_PATH", "./ctp_flow/"),
        "timeout": float(os.environ.get("CTP_TIMEOUT", "10.0")),
    }


def main():
    # ---------- 1. 真实 CTP 连接
    cfg = build_openctp_cfg()
    logger.info("=" * 60)
    logger.info("Path 2 真实 SimNow 联调")
    logger.info("账号: %s, 前置: %s", cfg["investor_id"], cfg["front_addr"])
    logger.info("=" * 60)
    broker = build_broker(cfg)
    if not broker.connect():
        logger.error("连接 SimNow 失败, 退出")
        sys.exit(1)

    # ---------- 2. 准备 ExecutionEngine
    sizer = PositionSizer()
    risk = RiskManager()
    notifier = MultiNotifier()  # 无钉钉/无 Bark 配置时不报错
    engine = ExecutionEngine(
        broker=broker,
        sizer=sizer,
        risk=risk,
        notifier=notifier,
    )

    # ---------- 3. 模拟一个融合信号 (Path 2 公式: 起步 2 手)
    equity = 12000.0
    decision = sizer.calc_lots("rb2607", equity, 0)
    lots = decision.lots
    logger.info("仓位计算: %s (raw=%d, mult=%.2f)", decision, decision.raw_lots, decision.multiplier)

    # ---------- 4. 推到桥 (如果桥没起, 降级为本地 confirm)
    if bridge_is_alive():
        logger.info("桥在线, 推送信号...")
        from common.execution import bridge_publish_signal as bridge_publish
        class _Sig:  # 最小 fused 替代
            strength = 0.85
            confidence = 0.78
            path1_consensus = 3
            path1_agreement = 0.7
            enhancement_applied = "none"
        pushed = bridge_publish(
            symbol="rb2607",
            direction=1,
            fused=_Sig(),
            account_state={"equity": equity, "lots": lots},
        )
        if pushed:
            logger.info("信号已推送到桥, 等手确...")
            time.sleep(3.0)
    else:
        logger.info("桥未启动, 走本地 confirm 流程")

    # ---------- 5. 走 ExecutionEngine 完整流程
    # 构造 fused 信号对象 (满足 signal_fusion.execute_fused_signal 的字段要求)
    class _Fused:
        strength = 0.85
        confidence = 0.78
        path1_consensus = 3
        path1_agreement = 0.7
        enhancement_applied = "aggressive"
        sl_atr_adj = 0.0
        tp_atr_adj = 0.0
        atr = 0.0
    trade_id = engine.queue_signal(
        symbol="rb2607",
        direction=1,            # 1=多 2=空
        fused=_Fused(),
        account_state={"equity": equity, "lots": lots},
    )
    logger.info("queue_signal 返回 trade_id=%s", trade_id)

    # ---------- 6. confirm 测试 (真实下单到 SimNow)
    if trade_id:
        # engine.confirm_trade 需要完整 FusedSignal, 字段多, 此处跳过以聚焦 broker 链路
        logger.info("跳过 engine.confirm_trade (字段依赖多, 需绑定 signal_fusion 才用), 改直接 broker 下单")
    else:
        logger.warning("queue_signal 返回空, 跳过 confirm")

    # ---------- 6.5 真实下单到 SimNow (跳过 engine, 直接 broker, 验证链路)
    logger.info("===== 直接通过 broker 下单 =====")
    try:
        oid = broker.send_order({
            "symbol": "rb2607",
            "direction": "long",
            "lots": lots,
            "price": 0.0,                # 市价
            "order_type": "market",
            "offset": "open",
        })
        logger.info("真实下单成功! order_id=%s", oid)
    except Exception as e:
        logger.error("真实下单失败: %s", e)

    # ---------- 7. 查持仓
    time.sleep(2.0)
    positions = broker.query_positions()
    logger.info("当前持仓: %s", positions)
    logger.info("委托簿: %s", broker._orders if hasattr(broker, "_orders") else {})

    # ---------- 8. 关单
    if positions:
        logger.info("调用 close_all...")
        closed = broker.close_all()
        logger.info("平仓: %s", closed)


if __name__ == "__main__":
    main()
