#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Execution subpackage for Path 2 / 10X Aggressive Growth.

Modules:
    position_sizer   - 权益阶梯加仓
    risk_manager     - 风控与硬熔断
    ctp_broker       - CTP 接口 (Mock + ctpbee)
    push_notifier    - 钉钉 / Bark 推送
    execution_engine - 信号→风控→仓位→CTP 中枢
    confirmation_bridge - FastAPI 移动端确认接口
"""
