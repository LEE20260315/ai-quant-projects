#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查 SimNow 上 RM/MA 当前可交易的合约代码 (从已缓存的 17740 条中过滤)"""
import sys, os, json
sys.path.insert(0, r"c:\Users\MR.Dong\OneDrive\My Project\ai-quant-projects-merged")
sys.path.insert(0, r"c:\Users\MR.Dong\OneDrive\My Project\ai-quant-projects-merged\path2_lightweight")

from common.execution.ctp_broker import OpenCtpBroker

broker = OpenCtpBroker(
    front_addr=os.environ.get("CTP_FRONT_ADDR", "tcp://182.254.243.31:40001"),
    broker_id="9999", app_id="simnow_client_test", auth_code="0000000000000000",
    investor_id=os.environ.get("CTP_INVESTOR_ID", "260042"),
    password=os.environ.get("CTP_PASSWORD", "xibeilang@99"),
    flow_path="./ctp_flow_qry_rm_ma/", timeout=15.0,
)
if not broker.connect():
    print("连接失败"); sys.exit(1)

from openctp_ctp.thosttraderapi import CThostFtdcQryInstrumentField
import time

req = CThostFtdcQryInstrumentField()
req.InstrumentID = ""
req.ExchangeID = ""
broker._api.ReqQryInstrument(req, 0)
time.sleep(5.0)

insts = getattr(broker, "_instruments", {})
print(f"缓存合约总数: {len(insts)}")

# 过滤 RM, MA, TA, m (DCE 豆粕), TA
result = {}
for prefix in ["RM", "MA", "TA", "m", "RM2", "MA2", "TA2"]:
    codes = sorted([s for s in insts if s.upper().startswith(prefix.upper())])
    codes = [c for c in codes if not c[-1].isalpha() or c[-1] in "0123456789"]  # 过滤期权
    codes = [c for c in codes if c[:2].upper() == prefix.upper() and c[2:].replace("P", "").replace("C", "").isdigit() or prefix == "m"]
    # 简化: 只取头 20 个
    result[prefix] = codes[:25]

print("RM (DCE 菜粕) 合约:", result["RM"])
print("MA (CZCE 甲醇) 合约:", result["MA"])
print("TA (CZCE PTA) 合约:", result["TA"])
print("m  (DCE 豆粕) 合约:", result["m"])
