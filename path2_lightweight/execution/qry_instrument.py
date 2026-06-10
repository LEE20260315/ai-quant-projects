#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
查询 SimNow 当前可交易的合约列表
"""
from __future__ import annotations

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

from common.execution.ctp_broker import OpenCtpBroker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("qry-instrument")

INVESTOR_ID = os.environ.get("CTP_INVESTOR_ID", "260042")
PASSWORD = os.environ.get("CTP_PASSWORD", "xibeilang@99")
FRONT = os.environ.get("CTP_FRONT_ADDR", "tcp://182.254.243.31:30001")

# 连接 (用 7x24 拿全合约)
broker = OpenCtpBroker(
    front_addr=FRONT,
    broker_id="9999",
    app_id="simnow_client_test",
    auth_code="0000000000000000",
    investor_id=INVESTOR_ID,
    password=PASSWORD,
    flow_path="./ctp_flow/",
    timeout=15.0,
)
if not broker.connect():
    log.error("连接失败")
    sys.exit(1)

# 查询合约
from openctp_ctp.thosttraderapi import CThostFtdcQryInstrumentField

# 螺纹钢 (RB / rb) 全部合约
req = CThostFtdcQryInstrumentField()
req.InstrumentID = ""  # 空 = 查全部
req.ExchangeID = ""
log.info("开始查询全量合约, 等 5 秒...")
broker._api.ReqQryInstrument(req, 0)
import time
time.sleep(5.0)

# 输出: 取前 30 个 rb* 合约
all_insts = broker._instruments if hasattr(broker, "_instruments") else {}
log.info("缓存的合约数: %d", len(all_insts))

# 临时方案: 直接重新查带 InstrumentID
for sym in ["rb2509", "rb2510", "rb2512", "rb2601", "rb2602", "rb2605", "TA509", "TA512", "TA601", "TA605"]:
    req2 = CThostFtdcQryInstrumentField()
    req2.InstrumentID = sym
    req2.ExchangeID = ""
    broker._api.ReqQryInstrument(req2, 0)
    time.sleep(0.3)

time.sleep(2.0)

# 输出: 取前 30 个 rb* / TA* 合约
insts = getattr(broker, "_instruments", {})
log.info("总合约数: %d", len(insts))

# 过滤 rb (螺纹钢) 和 TA (PTA) 合约
rb_codes = sorted([s for s in insts if s.upper().startswith(("RB", "RB2"))])
ta_codes = sorted([s for s in insts if s.upper().startswith(("TA", "PTA"))])
log.info("RB (螺纹钢) 合约: %s", rb_codes[:30])
log.info("TA (PTA) 合约: %s", ta_codes[:30])

# 也输出几个有成交活跃度的
for sym in (rb_codes + ta_codes)[:10]:
    info = insts.get(sym, {})
    log.info("  %s -> %s", sym, info)

log.info("done")
