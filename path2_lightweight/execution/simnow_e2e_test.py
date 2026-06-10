#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Path 2 端到端联调脚本 (SimNow / Mock)
====================================

Step 5 实操步骤:

  1. 启动 Confirmation Bridge (后台)
       $ uvicorn execution.confirmation_bridge:app --host 0.0.0.0 --port 8000
     (或本机端口 8000 与公网 IP 端口映射)

  2. 跑本脚本:
       $ python execution/simnow_e2e_test.py

  3. 手机扫码 / 点击 [确认下单] 链接, 即可在 SimNow 看到下单回报
     (Mock 模式则只会在日志里看到 order_id)

本脚本覆盖:
  - 普通开仓 (1 手)
  - 加仓 (权益涨 1 万 → 2 手)
  - 一级风控: DD 20% 仓位减半
  - 二级风控: DD 27% 拒绝开新仓
  - 硬熔断: DD 40% 全平 + 锁定
"""
from __future__ import annotations

import os
import sys
import time
import json
import logging

# 把项目根加入 sys.path, 让 common.* 可被 import
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from common.execution import (
    ExecutionEngine, MockCtpBroker, MultiNotifier, RiskManager,
)
from common.execution.base_sizer import BaseSizer, SizerDecision
from path2_lightweight.execution.position_sizer import PositionSizer
from path2_lightweight.fusion.signal_fusion import FusedSignal

import pandas as pd


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("E2E")


def make_fused(symbol, direction, confidence=0.7, strength=0.7, sl_adj=0, tp_adj=0.3, hold_adj=0):
    return FusedSignal(
        symbol=symbol, date=pd.Timestamp.now(),
        direction=direction, strength=strength, confidence=confidence,
        path2_direction=direction, path1_consensus=direction, path1_agreement=0.7,
        strategy_weights={}, enhancement_applied=f"same_dir:tp+{tp_adj}",
        sl_atr_adj=sl_adj, tp_atr_adj=tp_adj, hold_days_adj=hold_adj,
    )


def show(label, result):
    logger.info("=== %s ===", label)
    logger.info("  result = %s", json.dumps(result, ensure_ascii=False))


def main():
    # ---- 1) 准备 Mock 环境 (实盘时换 CtpbeeBroker) ----
    broker = MockCtpBroker(default_price=5000.0)
    engine = ExecutionEngine(
        broker=broker,
        pc_base_url="http://127.0.0.1:8000",
        sizer=PositionSizer(),
        risk=RiskManager(),
        notifier=MultiNotifier(),  # 无 webhook → 干跑推送
    )
    # 初始账户: 1 万现金, 0 持仓
    account = {
        "capital": 10_000,
        "peak_capital": 10_000,
        "positions": {},
        "trade_log": [],
        "current_equity": 10_000,
    }
    engine.update_account(account)

    # ---- 2) 场景 1: 正常开仓 ----
    fused = make_fused("TA2506", direction=1, confidence=0.8, strength=0.75, tp_adj=0.30)
    tid = engine.queue_signal(
        symbol="TA2506", direction=1, fused=fused,
        signal_type="分位短线 v3", stop_loss=4820, take_profit=5180,
        account_state=account,
    )
    # 模拟移动端点确认链接
    res = engine.confirm_trade(tid, confirm_token="demo-token-1234")
    show("CASE 1: 正常开仓 1 万本金 → 2 手", res)
    assert res.get("ok") and res.get("lots") == 2, f"期望 2 手, 实际 {res}"

    # ---- 3) 场景 2: 盈利加仓 (equity 1.5 万) ----
    account["capital"] = 12_000   # 浮盈算入 current_equity
    account["current_equity"] = 15_000
    fused = make_fused("MA2506", direction=-1, confidence=0.7, strength=0.65, tp_adj=0.20)
    tid = engine.queue_signal(
        "MA2506", -1, fused, "分位短线 v3", stop_loss=2620, take_profit=2480,
        account_state=account,
    )
    res = engine.confirm_trade(tid, confirm_token="demo-token-1234")
    show("CASE 2: 盈利加仓 equity=15000", res)
    assert res.get("ok") and res.get("lots") == 3, f"期望 3 手 (raw=3+0), 实际 {res}"

    # ---- 4) 场景 3: 一级风控 (DD 22%) ----
    account["capital"] = 7_800
    account["peak_capital"] = 10_000
    account["current_equity"] = 7_800
    fused = make_fused("RM2506", direction=1, confidence=0.6, strength=0.6, tp_adj=0.10)
    tid = engine.queue_signal(
        "RM2506", 1, fused, "分位短线 v3", stop_loss=2400, take_profit=2600,
        account_state=account,
    )
    res = engine.confirm_trade(tid, confirm_token="demo-token-1234")
    show("CASE 3: DD=22% 一级风控 (1 手公式 -> 0.5x)", res)
    # 1 万时 RM raw 公式 2 手, 跌到 7800 还是 2 手, 一级风控 0.5x -> 1 手
    assert res.get("ok") and res.get("lots") == 1, f"期望 1 手, 实际 {res}"

    # ---- 5) 场景 4: 二级风控 (DD 30%) ----
    account["capital"] = 7_000
    account["peak_capital"] = 10_000
    account["current_equity"] = 7_000
    fused = make_fused("TA2506", direction=-1, confidence=0.7, strength=0.7)
    tid = engine.queue_signal(
        "TA2506", -1, fused, "分位短线 v3", stop_loss=5100, take_profit=4900,
        account_state=account,
    )
    res = engine.confirm_trade(tid, confirm_token="demo-token-1234")
    show("CASE 4: DD=30% 二级风控 → 拒绝开新仓", res)
    assert not res.get("ok") and res.get("reason") == "risk_block", f"应被风控拦截, 实际 {res}"

    # ---- 6) 场景 5: 硬熔断 (DD 42%) ----
    print()
    logger.info(">>> 场景 5: DD=42% 硬熔断 <<<")
    account["capital"] = 5_800
    account["peak_capital"] = 10_000
    account["current_equity"] = 5_800
    engine.update_account(account)
    logger.info("  触发前 broker 持仓: %s", broker.query_positions())
    # engine.update_account 时若触发硬熔断, _force_close_hook 已被自动调用
    logger.info("  触发后 broker 持仓: %s", broker.query_positions())
    logger.info("  RiskManager tripped: %s", engine.risk._tripped)
    # 再下一个单, 应当直接被锁定
    fused = make_fused("RM2506", direction=1)
    tid = engine.queue_signal("RM2506", 1, fused, "分位短线 v3", 2400, 2600, account)
    res = engine.confirm_trade(tid, confirm_token="demo-token-1234")
    show("CASE 5: 硬熔断后下新单", res)
    assert not res.get("ok") and res.get("reason") == "risk_block", f"硬熔断后必须拒绝, 实际 {res}"

    print()
    logger.info("=" * 60)
    logger.info("  全部 5 个场景通过 ✅")
    logger.info("=" * 60)
    logger.info("端到端联调完成. 接下来可以: ")
    logger.info("  1) 把 broker 换成 CtpbeeBroker (装好 ctpbee 后)")
    logger.info("  2) live_tracker.py 集成到 confirmation_bridge.queue_signal")
    logger.info("  3) 24h PC 上跑 uvicorn, 钉钉推送 webhooks 配置进 DINGTALK_WEBHOOK")


if __name__ == "__main__":
    main()
