#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
live_tracker <-> confirmation_bridge 适配器
=========================================

作用: live_tracker 扫描出信号后, 调本模块的 publish() 推给 confirmation_bridge.
     bridge 收到后会入队 + 推钉钉/Bark + 等移动端点确认.

用法 (在 live_tracker._execute_open 处改为):

    from execution.bridge_publisher import publish
    if not publish(symbol, direction, fused, account_state, stop_loss, take_profit):
        # bridge 不可用, 退回本地直接执行
        self._execute_open(...)

环境变量:
    BRIDGE_URL  默认 http://127.0.0.1:8000
"""
from __future__ import annotations

import logging
import os
from typing import Optional

try:
    import requests  # type: ignore
    _REQUESTS_OK = True
except ImportError:
    requests = None  # type: ignore
    _REQUESTS_OK = False


logger = logging.getLogger(__name__)
BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8000")
TIMEOUT = float(os.environ.get("BRIDGE_TIMEOUT", "3.0"))


def is_alive() -> bool:
    """快速健康检查 — bridge 不可用时返回 False 而不是抛异常"""
    if not _REQUESTS_OK:
        return False
    try:
        r = requests.get(f"{BRIDGE_URL}/healthz", timeout=1.0)  # type: ignore
        return r.status_code == 200
    except Exception:
        return False


def publish(
    symbol: str,
    direction: int,
    fused,
    account_state: dict,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    signal_type: str = "分位短线 v3",
) -> Optional[dict]:
    """
    把信号推给 confirmation_bridge.

    Returns:
        None —— bridge 不可用
        dict —— bridge 返回的 {trade_id, token, execute_url, skip_url}
    """
    payload = {
        "symbol": symbol,
        "direction": direction,
        "signal_type": signal_type,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "fused": {
            "strength": getattr(fused, "strength", 0.5),
            "confidence": getattr(fused, "confidence", 0.5),
            "path1_consensus": getattr(fused, "path1_consensus", 0),
            "path1_agreement": getattr(fused, "path1_agreement", 0.0),
            "enhancement_applied": getattr(fused, "enhancement_applied", "none"),
        },
        "account_state": account_state,
    }
    try:
        if not _REQUESTS_OK:
            logger.debug("[bridge] requests 库未安装, 跳过推送")
            return None
        r = requests.post(  # type: ignore
            f"{BRIDGE_URL}/queue", json=payload, timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("ok"):
            logger.info(
                "[bridge] 已入队 %s %s trade_id=%s",
                symbol, "多" if direction == 1 else "空", data["trade_id"],
            )
            return data
        logger.warning("[bridge] 入队失败: %s", data)
        return None
    except Exception as e:
        logger.warning("[bridge] 推送失败 (bridge 未运行?): %s", e)
        return None


if __name__ == "__main__":
    print("BRIDGE_URL =", BRIDGE_URL)
    print("is_alive =", is_alive())
