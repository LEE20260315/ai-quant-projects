#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CTP 抽象层（Path 2 / 10X Aggressive Growth）
=====================================

设计目标：
  1. 抽象统一接口 (CtpBroker) —— ExecutionEngine 不感知底层是 SimNow 还是实盘
  2. 提供 MockCtpBroker：本地内存模拟, 联调期间完全可用
  3. 提供 OpenCtpBroker：基于 openctp-ctp (预编译 wheel, 无需 MSVC) 真实 CTP 接口
  4. 提供 CtpbeeBroker：封装 ctpbee (需要 MSVC 编译) —— 已弃用, 保留仅为参考
  5. openctp-ctp 缺装时, OpenCtpBroker 给出明确指引而不是崩溃

CTP 通用配置（来自计划要求）：
    FrontAddr, BrokerID, AppID, AuthCode
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# ============================================================
# 标准 OrderRequest / OrderResult
# ============================================================
@dataclass
class OrderRequest:
    symbol: str
    direction: str         # "long" / "short"
    lots: int
    price: float = 0.0     # 0 = 市价
    order_type: str = "limit"  # "limit" / "market"
    offset: str = "open"   # "open" / "close"
    exchange: str = ""     # 自动从 symbol 推断, 不必填
    fused: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderResult:
    ok: bool
    order_id: str
    symbol: str
    direction: str
    lots: int
    message: str = ""
    accepted_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 抽象基类
# ============================================================
class CtpBroker(ABC):
    @abstractmethod
    def connect(self) -> bool: ...
    @abstractmethod
    def send_order(self, order: dict) -> str: ...
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    def query_positions(self) -> Dict[str, dict]: ...
    @abstractmethod
    def close_all(self) -> List[str]: ...

    def is_connected(self) -> bool:
        return False


# ============================================================
# Mock 实现 —— 用于 SimNow 联调 / 单元测试
# ============================================================
class MockCtpBroker(CtpBroker):
    """
    内存版 CTP 模拟器.
    行为尽量贴近真实柜台:
      - 下单即成交 (市价) 或挂在买/卖价 (限价)
      - 维护持仓字典
      - 支持全平
    """

    def __init__(self, taker_slippage: float = 0.0, default_price: float = 5000.0):
        self.taker_slippage = taker_slippage
        self.default_price = default_price
        self._orders: Dict[str, OrderResult] = {}
        self._positions: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._order_log: List[dict] = []
        self._connected = False
        logger.info("MockCtpBroker 已初始化 (taker_slippage=%.4f)", taker_slippage)

    # ------- 公共接口
    def connect(self) -> bool:
        self._connected = True
        logger.info("MockCtpBroker.connect(): 模拟连接成功")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def send_order(self, order: dict) -> str:
        if isinstance(order, dict) and "symbol" in order and "direction" in order:
            req = OrderRequest(
                symbol=order["symbol"],
                direction=order["direction"],
                lots=int(order.get("lots", 0)),
                price=float(order.get("price", 0.0)),
                order_type=order.get("order_type", "market"),
                offset=order.get("offset", "open"),
                exchange=order.get("exchange", ""),
                fused=order.get("fused", {}),
            )
        else:
            req = order  # 已是 OrderRequest

        with self._lock:
            order_id = "MOCK-" + uuid.uuid4().hex[:10].upper()
            price = req.price if req.price > 0 else self.default_price * (1 + self.taker_slippage)
            res = OrderResult(
                ok=True,
                order_id=order_id,
                symbol=req.symbol,
                direction=req.direction,
                lots=req.lots,
                message=f"accepted@{price:.2f}",
                accepted_at=datetime.now().isoformat(),
            )
            self._orders[order_id] = res
            self._update_position(req, price)
            self._order_log.append({"order": req.to_dict(), "result": res.to_dict()})
            logger.info(
                "Mock 下单 %s %s %d 手 @ %.2f -> order_id=%s",
                req.symbol, req.direction, req.lots, price, order_id,
            )
            return order_id

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            res = self._orders.get(order_id)
            if res is None:
                return False
            res.ok = False
            res.message = "cancelled"
            return True

    def query_positions(self) -> Dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._positions.items()}

    def close_all(self) -> List[str]:
        with self._lock:
            closed = list(self._positions.keys())
            for sym in closed:
                logger.info("Mock 强平: %s 当前持仓=%s", sym, self._positions[sym])
            self._positions.clear()
            return closed

    # ------- 内部
    def _update_position(self, req: OrderRequest, fill_price: float) -> None:
        sym = req.symbol
        if sym not in self._positions:
            self._positions[sym] = {
                "direction": req.direction,
                "size": 0,
                "avg_price": 0.0,
            }
        pos = self._positions[sym]
        if req.offset == "close":
            # 平仓：手数扣减
            pos["size"] = max(0, pos["size"] - req.lots)
            if pos["size"] == 0:
                self._positions.pop(sym, None)
            return
        if pos["size"] == 0 or pos["direction"] == req.direction:
            # 加仓 / 同向开仓
            new_size = pos["size"] + req.lots
            if pos["size"] == 0:
                pos["direction"] = req.direction
                pos["avg_price"] = fill_price
            else:
                # 加权平均
                pos["avg_price"] = (
                    pos["avg_price"] * pos["size"] + fill_price * req.lots
                ) / new_size
            pos["size"] = new_size
        else:
            # 反向：先平后开
            if req.lots >= pos["size"]:
                remain = req.lots - pos["size"]
                self._positions.pop(sym, None)
                if remain > 0:
                    self._positions[sym] = {
                        "direction": req.direction,
                        "size": remain,
                        "avg_price": fill_price,
                    }
            else:
                pos["size"] -= req.lots

    # ------- 调试
    def dump_order_log(self) -> List[dict]:
        return list(self._order_log)


# ============================================================
# openctp-ctp 封装 —— 真实 CTP 接口 (推荐, 无 MSVC 编译)
# ============================================================
try:
    from openctp_ctp.thosttraderapi import (
        CThostFtdcTraderApi,
        CThostFtdcTraderSpi,
        CThostFtdcReqAuthenticateField,
        CThostFtdcReqUserLoginField,
        CThostFtdcInputOrderField,
        CThostFtdcQryInvestorPositionField,
    )
    _OPENCTP_OK = True
    _OPENCTP_IMPORT_ERR: Optional[Exception] = None
    _OPENCTP_TRADER_SPI = CThostFtdcTraderSpi
except Exception as e:  # noqa: BLE001
    _OPENCTP_OK = False
    _OPENCTP_IMPORT_ERR = e
    _OPENCTP_TRADER_SPI = object  # dummy base for class definition when openctp-ctp 不可用


# CTP 字段常量 (取自 thosttraderapi.py)
DIRECTION_BUY = "0"
DIRECTION_SELL = "1"
OFFSET_OPEN = "0"
OFFSET_CLOSE = "1"
OFFSET_CLOSE_TODAY = "3"
HEDGE_SPEC = "1"
PRICE_LIMIT = "1"
PRICE_MARKET_SHFE = "2"   # 上期/能源 — 市价
PRICE_MARKET_DCE = "1"    # 大商所 — 限价即时全部成交否则撤销 (类似市价)
TIME_COND_GFD = "1"        # 当日有效
VOL_COND_ANY = "1"
CONTINGENT_IMMEDIATELY = "1"

# SimNow 6 所交易所代码 (CTP 协议)
EXCHANGE_SHFE = "SHFE"    # 上期所
EXCHANGE_DCE = "DCE"      # 大商所
EXCHANGE_CZCE = "CZCE"    # 郑商所
EXCHANGE_CFFEX = "CFFEX"  # 中金所
EXCHANGE_INE = "INE"      # 上期能源
EXCHANGE_GFEX = "GFEX"    # 广期所

# 品种 → 交易所映射
_SYMBOL_TO_EXCHANGE: dict = {
    # 上期所 (SHFE)
    "AU": EXCHANGE_SHFE, "AG": EXCHANGE_SHFE, "CU": EXCHANGE_SHFE, "AL": EXCHANGE_SHFE,
    "ZN": EXCHANGE_SHFE, "PB": EXCHANGE_SHFE, "NI": EXCHANGE_SHFE, "SN": EXCHANGE_SHFE,
    "RU": EXCHANGE_SHFE, "FU": EXCHANGE_SHFE, "RB": EXCHANGE_SHFE, "HC": EXCHANGE_SHFE,
    "BU": EXCHANGE_SHFE, "SP": EXCHANGE_SHFE, "WR": EXCHANGE_SHFE, "SS": EXCHANGE_SHFE,
    "NR": EXCHANGE_SHFE, "BR": EXCHANGE_SHFE, "AO": EXCHANGE_SHFE, "AD": EXCHANGE_SHFE,
    # 上期能源 (INE)
    "SC": EXCHANGE_INE, "LU": EXCHANGE_INE, "BC": EXCHANGE_INE, "EC": EXCHANGE_INE,
    # 大商所 (DCE)
    "A": EXCHANGE_DCE, "B": EXCHANGE_DCE, "M": EXCHANGE_DCE, "Y": EXCHANGE_DCE, "P": EXCHANGE_DCE,
    "C": EXCHANGE_DCE, "CS": EXCHANGE_DCE, "L": EXCHANGE_DCE, "V": EXCHANGE_DCE, "PP": EXCHANGE_DCE,
    "J": EXCHANGE_DCE, "JM": EXCHANGE_DCE, "I": EXCHANGE_DCE, "EG": EXCHANGE_DCE, "EB": EXCHANGE_DCE,
    "PG": EXCHANGE_DCE, "LH": EXCHANGE_DCE, "RR": EXCHANGE_DCE, "JD": EXCHANGE_DCE, "FB": EXCHANGE_DCE,
    "BB": EXCHANGE_DCE, "RS": EXCHANGE_DCE,
    # 郑商所 (CZCE) — 注意: 3 位字母代码
    "TA": EXCHANGE_CZCE, "MA": EXCHANGE_CZCE, "OI": EXCHANGE_CZCE, "RM": EXCHANGE_CZCE, "SR": EXCHANGE_CZCE,
    "CF": EXCHANGE_CZCE, "CY": EXCHANGE_CZCE, "AP": EXCHANGE_CZCE, "PTA": EXCHANGE_CZCE,
    "FG": EXCHANGE_CZCE, "SA": EXCHANGE_CZCE, "UR": EXCHANGE_CZCE, "SM": EXCHANGE_CZCE, "SF": EXCHANGE_CZCE,
    "ZC": EXCHANGE_CZCE, "WH": EXCHANGE_CZCE, "PM": EXCHANGE_CZCE, "RI": EXCHANGE_CZCE, "LR": EXCHANGE_CZCE,
    "JR": EXCHANGE_CZCE, "PX": EXCHANGE_CZCE, "PR": EXCHANGE_CZCE, "PL": EXCHANGE_CZCE,
    "SH": EXCHANGE_CZCE, "PF": EXCHANGE_CZCE, "PK": EXCHANGE_CZCE, "CJ": EXCHANGE_CZCE,
    # 中金所 (CFFEX)
    "IF": EXCHANGE_CFFEX, "IH": EXCHANGE_CFFEX, "IC": EXCHANGE_CFFEX, "IM": EXCHANGE_CFFEX,
    "T": EXCHANGE_CFFEX, "TF": EXCHANGE_CFFEX, "TS": EXCHANGE_CFFEX, "TL": EXCHANGE_CFFEX,
    # 广期所 (GFEX)
    "SI": EXCHANGE_GFEX, "LC": EXCHANGE_GFEX, "PS": EXCHANGE_GFEX, "PT": EXCHANGE_GFEX, "PD": EXCHANGE_GFEX,
}


def infer_exchange_id(symbol: str) -> str:
    """
    从合约代码推断交易所 ID (CTP 协议要求)
    :param symbol: 合约代码, 如 "TA2506" / "rb2506" / "i2506"
    :return: SHFE/DCE/CZCE/CFFEX/INE/GFEX
    """
    if not symbol:
        return EXCHANGE_SHFE
    sym = symbol.upper()
    # 优先匹配 2 字符前缀
    for k in (sym[:2], sym[:1]):
        if k in _SYMBOL_TO_EXCHANGE:
            return _SYMBOL_TO_EXCHANGE[k]
    return EXCHANGE_SHFE



class _OpenCtpSpi(_OPENCTP_TRADER_SPI):
    """openctp CTP SPI (回调处理器) —— 把柜台回报同步到 OpenCtpBroker 状态."""

    def __init__(self, broker: "OpenCtpBroker"):
        super().__init__()
        self._broker = broker

    # ---------- 连接/认证/登录
    def OnFrontConnected(self):
        self._broker._on_front_connected()

    def OnFrontDisconnected(self, nReason: int):
        self._broker._on_front_disconnected(nReason)

    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID: int, bIsLast: bool):
        self._broker._on_rsp_authenticate(pRspAuthenticateField, pRspInfo, nRequestID, bIsLast)

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool):
        self._broker._on_rsp_user_login(pRspUserLogin, pRspInfo, nRequestID, bIsLast)

    # ---------- 委托回报
    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID: int, bIsLast: bool):
        self._broker._on_rsp_order_insert(pInputOrder, pRspInfo, nRequestID, bIsLast)

    def OnRtnOrder(self, pOrder):
        self._broker._on_rtn_order(pOrder)

    def OnRtnTrade(self, pTrade):
        self._broker._on_rtn_trade(pTrade)

    def OnErrRtnOrderInsert(self, pInputOrder, pRspInfo):
        self._broker._on_err_rtn_order_insert(pInputOrder, pRspInfo)

    # ---------- 持仓查询
    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID: int, bIsLast: bool):
        self._broker._on_rsp_qry_position(pInvestorPosition, pRspInfo, nRequestID, bIsLast)

    # ---------- 结算单确认
    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID: int, bIsLast: bool):
        self._broker._on_rsp_settlement_confirm(pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast)

    # ---------- 合约查询
    def OnRspQryInstrument(self, pInstrument, pRspInfo, nRequestID: int, bIsLast: bool):
        self._broker._on_rsp_qry_instrument(pInstrument, pRspInfo, nRequestID, bIsLast)


class OpenCtpBroker(CtpBroker):
    """
        openctp-ctp 真实 CTP 柜台 (推荐)

        用法::

        ctp = OpenCtpBroker(
        front_addr="tcp://182.254.243.31:30001",   # SimNow 新版看穿式前置
        broker_id="9999",
        app_id="simnow_client_test",                 # SimNow 默认
        auth_code="0000000000000000",                # 16 个 0, SimNow 默认
        investor_id="<your_id>",
        password="<your_pwd>",
        )
        ctp.connect()
        ctp.send_order({...})

        适用:
        - SimNow 模拟盘 (7x24: tcp://182.254.243.31:40001)
        - 东航/东海/中信期货等实盘柜台 (需替换 front_addr / broker_id)

        常见 4097 错误排查:
        - 原因 1: 客户号/密码未在 SimNow 首页 "重置" 过 → 立即去 https://www.simnow.com.cn/ 重置
        - 原因 2: API 协议版本与新前置不匹配 → `pip install -U openctp-ctp`
        - 原因 3: 网络/防火墙被屏蔽 → 换 7x24 前置 (40001) 试

        与 ctpbee 的区别:
        - 无需 MSVC 编译 (openctp-ctp 是预编译 wheel)
        - API 更接近 CTP 原生 (不包装 OrderRequest/Position 等高层类)
        - 需要自己维护 order_ref (柜台按 order_ref 识别报单)
    """

    def __init__(
        self,
        front_addr: str,
        broker_id: str,
        app_id: str,
        auth_code: str,
        investor_id: str,
        password: str,
        flow_path: str = "./ctp_flow/",
        timeout: float = 10.0,
    ):
        if not _OPENCTP_OK:
            raise RuntimeError(
                f"openctp-ctp 未安装或 import 失败: {_OPENCTP_IMPORT_ERR}. "
                "请执行 `pip install openctp-ctp`. "
                "或暂时改用 MockCtpBroker 联调."
            )
        self.front_addr = front_addr
        self.broker_id = broker_id
        self.app_id = app_id
        self.auth_code = auth_code
        self.investor_id = investor_id
        self.password = password
        self.flow_path = flow_path
        self.timeout = timeout

        # 状态
        self._api: Optional[CThostFtdcTraderApi] = None
        self._spi: Optional[_OpenCtpSpi] = None
        self._front_connected = threading.Event()
        self._auth_done = threading.Event()
        self._login_done = threading.Event()
        self._settle_confirmed = threading.Event()
        self._settle_failed: Optional[str] = None
        self._auth_failed: Optional[str] = None
        self._login_failed: Optional[str] = None
        self._front_id = 0
        self._session_id = 0
        self._order_ref_lock = threading.Lock()
        self._order_ref = 1
        # 委托与持仓簿
        self._orders: Dict[str, dict] = {}
        self._positions: Dict[str, dict] = {}
        self._order_results: Dict[str, dict] = {}
        self._position_results: Dict[str, dict] = {}
        self._instruments: Dict[str, dict] = {}
        self._lock = threading.RLock()

        # ============================================================ 公共 API
    def is_connected(self) -> bool:
        return self._front_connected.is_set() and self._login_done.is_set()

    def connect(self) -> bool:
        try:
            os.makedirs(self.flow_path, exist_ok=True)
            # 1) 创建 API (CTP 协议要求 flow_path 不能空)
            # 注意: openctp-ctp 的 swig 绑定要求传 str, 不是 bytes
            self._api = CThostFtdcTraderApi.CreateFtdcTraderApi(str(self.flow_path))
            # 2) 注册 SPI
            self._spi = _OpenCtpSpi(self)
            self._api.RegisterSpi(self._spi)
            # 3) 订阅私有/公共流
            self._api.SubscribePrivateTopic(0)
            self._api.SubscribePublicTopic(0)
            # 3.5) CTP 6.7+ 要求登记客户端系统信息
            try:
                from openctp_ctp.thosttraderapi import CThostFtdcUserSystemInfoField  # type: ignore
                sysinfo = CThostFtdcUserSystemInfoField()
                sysinfo.BrokerID = self.broker_id
                sysinfo.UserID = self.investor_id
                sysinfo.ClientSystemInfo = "Path2Quant|Windows|10|x64"
                sysinfo.ClientPublicIP = "127.0.0.1"
                sysinfo.ClientIPPort = 0
                sysinfo.ClientLoginTime = datetime.now().strftime("%Y%m%d%H%M%S")
                self._api.RegisterUserSystemInfo(sysinfo)
            except Exception as e:
                logger.debug("RegisterUserSystemInfo 可选步骤失败 (忽略): %s", e)
            # 4) 注册前置地址
            self._api.RegisterFront(str(self.front_addr))
            # 5) 启动
            self._api.Init()
            # 6) 等 OnFrontConnected
            if not self._front_connected.wait(timeout=self.timeout):
                logger.error("OpenCtpBroker: 前置连接超时 (%.1fs) %s", self.timeout, self.front_addr)
                return False
            # 7) 认证
            if not self._do_authenticate():
                return False
            # 8) 登录
            if not self._do_login():
                return False
            logger.info("OpenCtpBroker 已连接 %s broker=%s investor=%s", self.front_addr, self.broker_id, self.investor_id)
            return True
        except Exception as e:
            logger.exception("OpenCtpBroker.connect 失败: %s", e)
            return False

    def send_order(self, order: dict) -> str:
        if self._api is None or not self._login_done.is_set():
            raise RuntimeError("OpenCtpBroker 未登录, 请先 connect().")
        # 1) 组装 CThostFtdcInputOrderField
        req = CThostFtdcInputOrderField()
        req.BrokerID = self.broker_id
        req.InvestorID = self.investor_id
        req.InstrumentID = order["symbol"]
        # 交易所代码 (CTP 协议必填, 148 错误就是缺这个)
        req.ExchangeID = order.get("exchange") or infer_exchange_id(order["symbol"])
        with self._order_ref_lock:
            order_ref = str(self._order_ref).rjust(12, "0")
            self._order_ref += 1
        req.OrderRef = order_ref
        direction = str(order.get("direction", "long")).lower()
        req.Direction = DIRECTION_BUY if direction in ("long", "buy", "0") else DIRECTION_SELL
        offset = str(order.get("offset", "open")).lower()
        if offset == "close":
            req.CombOffsetFlag = OFFSET_CLOSE
        elif offset == "closetoday":
            req.CombOffsetFlag = OFFSET_CLOSE_TODAY
        else:
            req.CombOffsetFlag = OFFSET_OPEN
        req.CombHedgeFlag = HEDGE_SPEC
        # 价格类型: 市价 / 限价
        is_market = order.get("order_type", "limit") == "market" or float(order.get("price", 0.0)) <= 0
        if is_market:
            exg = req.ExchangeID
            if exg in (EXCHANGE_SHFE, EXCHANGE_INE):
                req.OrderPriceType = PRICE_MARKET_SHFE
            elif exg == EXCHANGE_DCE:
                req.OrderPriceType = PRICE_MARKET_DCE
            else:
                req.OrderPriceType = PRICE_MARKET_SHFE
        else:
            req.OrderPriceType = PRICE_LIMIT
        req.TimeCondition = TIME_COND_GFD
        req.VolumeCondition = VOL_COND_ANY
        req.ContingentCondition = CONTINGENT_IMMEDIATELY
        req.LimitPrice = float(order.get("price", 0.0))
        req.VolumeTotalOriginal = int(order.get("lots", 0))
        req.MinVolume = 1
        req.ForceCloseReason = "0"
        req.IsAutoSuspend = 0
        req.UserForceClose = 0
        # 2) 提交
        ret = self._api.ReqOrderInsert(req, 0)
        if ret != 0:
            raise RuntimeError(f"ReqOrderInsert 失败 ret={ret}")
        oid = f"CTP-{order_ref}"
        with self._lock:
            self._orders[oid] = {
                "order_ref": order_ref,
                "symbol": order["symbol"],
                "direction": "long" if req.Direction == DIRECTION_BUY else "short",
                "offset": offset,
                "lots": int(order.get("lots", 0)),
                "price": float(order.get("price", 0.0)),
                "status": "submitted",
                "ts": datetime.now().isoformat(),
            }
        logger.info("OpenCtp 下单 %s %s %d 手 @ %.2f ref=%s", order["symbol"], direction, int(order.get("lots", 0)), float(order.get("price", 0.0)), order_ref)
        return oid

    def cancel_order(self, order_id: str) -> bool:
        logger.warning("OpenCtpBroker.cancel_order 暂未实现, 撤单请用 ReqOrderAction")
        return False

    def query_positions(self) -> Dict[str, dict]:
        if self._api is None or not self._login_done.is_set():
            return {}
        req = CThostFtdcQryInvestorPositionField()
        req.BrokerID = self.broker_id
        req.InvestorID = self.investor_id
        self._position_results.clear()
        ret = self._api.ReqQryInvestorPosition(req, 0)
        if ret != 0:
            logger.warning("ReqQryInvestorPosition 失败 ret=%d", ret)
            return {}
        # 简单等回调: SimNow 一般秒回
        time.sleep(0.5)
        with self._lock:
            return {k: dict(v) for k, v in self._positions.items()}

    def close_all(self) -> List[str]:
        positions = self.query_positions()
        closed: List[str] = []
        for sym, pos in positions.items():
            size = int(pos.get("size", 0))
            if size <= 0:
                continue
            try:
                self.send_order({
                    "symbol": sym,
                    "direction": "short" if pos.get("direction") == "long" else "long",
                    "lots": size,
                    "price": 0.0,
                    "order_type": "market",
                    "offset": "close",
                })
                closed.append(sym)
            except Exception as e:
                logger.warning("OpenCtpBroker.close_all %s 失败: %s", sym, e)
        return closed

        # ============================================================ 内部
    def _do_authenticate(self) -> bool:
        if not self.app_id or not self.auth_code:
            logger.info("OpenCtpBroker: AppID/AuthCode 未配置, 跳过认证步骤")
            self._auth_done.set()
            return True
        req = CThostFtdcReqAuthenticateField()
        req.BrokerID = self.broker_id
        req.UserID = self.investor_id
        req.AppID = self.app_id
        req.AuthCode = self.auth_code
        req.UserProductInfo = "Path2Quant"
        ret = self._api.ReqAuthenticate(req, 0)  # type: ignore[union-attr]
        if ret != 0:
            logger.error("OpenCtpBroker: ReqAuthenticate 失败 ret=%d", ret)
            return False
        if not self._auth_done.wait(timeout=self.timeout):
            logger.error("OpenCtpBroker: 认证超时")
            return False
        if self._auth_failed:
            logger.error("OpenCtpBroker: 认证失败 %s", self._auth_failed)
            if "4097" in str(self._auth_failed):
                logger.error(
                    "  ↳ 可能原因 1: SimNow 新账号首次登录前必须先去首页重置密码\n"
                    "  ↳ 可能原因 2: AppID/AuthCode 不对, 默认值 simnow_client_test / 0000000000000000\n"
                    "  ↳ 可能原因 3: openctp-ctp 协议版本与新前置不匹配, 试 `pip install -U openctp-ctp`"
                )
            return False
        return True

    def _do_login(self) -> bool:
        req = CThostFtdcReqUserLoginField()
        req.BrokerID = self.broker_id
        req.UserID = self.investor_id
        req.Password = self.password
        req.UserProductInfo = "Path2Quant"
        ret = self._api.ReqUserLogin(req, 0)  # type: ignore[union-attr]
        if ret != 0:
            logger.error("OpenCtpBroker: ReqUserLogin 失败 ret=%d", ret)
            return False
        if not self._login_done.wait(timeout=self.timeout):
            logger.error("OpenCtpBroker: 登录超时 (网络问题或前置不可达)")
            return False
        if self._login_failed:
            logger.error("OpenCtpBroker: 登录失败 %s", self._login_failed)
            if "4097" in str(self._login_failed):
                logger.error(
                    "  ↳ 客户号或密码错误, 或账号未在 SimNow 首页激活 (新账号需重置密码)"
                )
            elif "3" in str(self._login_failed).split(":")[0]:
                logger.error("  ↳ 重复登录: 已有会话, 请等待 1 分钟或换 7x24 前置")
            return False
        # 登录成功后, 立刻确认上一日结算单 (新账号必做, 否则下单报 42)
        return self._do_confirm_settlement()

    def _do_confirm_settlement(self) -> bool:
        """确认上一交易日结算单 (SimNow 新账号必须, 否则下单报 42 结算结果未确认)"""
        try:
            from openctp_ctp.thosttraderapi import CThostFtdcSettlementInfoConfirmField
        except ImportError:
            logger.debug("未找到 CThostFtdcSettlementInfoConfirmField, 跳过")
            return True
        req = CThostFtdcSettlementInfoConfirmField()
        req.BrokerID = self.broker_id
        req.InvestorID = self.investor_id
        from datetime import datetime, timedelta
        now = datetime.now()
        if now.weekday() == 4 and now.hour >= 16:
            trade_day = (now + timedelta(days=3)).strftime("%Y%m%d")
        elif now.weekday() == 5:
            trade_day = (now + timedelta(days=2)).strftime("%Y%m%d")
        elif now.weekday() == 6 and now.hour < 16:
            trade_day = (now + timedelta(days=1)).strftime("%Y%m%d")
        else:
            trade_day = now.strftime("%Y%m%d")
        req.ConfirmDate = trade_day
        req.ConfirmTime = now.strftime("%H:%M:%S")
        ret = self._api.ReqSettlementInfoConfirm(req, 0)  # type: ignore[union-attr]
        if ret != 0:
            logger.warning("OpenCtpBroker: ReqSettlementInfoConfirm 失败 ret=%d (继续)", ret)
            return True
        self._settle_confirmed.wait(timeout=self.timeout)
        if self._settle_failed:
            logger.warning("OpenCtpBroker: 结算单确认失败 %s (继续)", self._settle_failed)
        logger.info("OpenCtpBroker: 结算单已确认 (date=%s)", trade_day)
        return True

        # ============================================================ SPI 回调
    def _on_front_connected(self):
        logger.info("OpenCtpBroker: 前置已连接 %s", self.front_addr)
        self._front_connected.set()

    def _on_front_disconnected(self, reason: int):
        logger.warning("OpenCtpBroker: 前置断开 reason=%d", reason)
        self._front_connected.clear()
        self._auth_done.clear()
        self._login_done.clear()

    def _on_rsp_authenticate(self, pRspAuthenticateField, pRspInfo, nRequestID: int, bIsLast: bool):
        if pRspInfo and getattr(pRspInfo, "ErrorID", 0) != 0:
            self._auth_failed = f"{pRspInfo.ErrorID}: {pRspInfo.ErrorMsg}"
        else:
            self._auth_failed = None
        self._auth_done.set()

    def _on_rsp_user_login(self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool):
        if pRspInfo and getattr(pRspInfo, "ErrorID", 0) != 0:
            self._login_failed = f"{pRspInfo.ErrorID}: {pRspInfo.ErrorMsg}"
        else:
            self._login_failed = None
            if pRspUserLogin is not None:
                self._front_id = int(getattr(pRspUserLogin, "FrontID", 0))
                self._session_id = int(getattr(pRspUserLogin, "SessionID", 0))
                logger.info("OpenCtpBroker: 登录成功 FrontID=%d SessionID=%d", self._front_id, self._session_id)
        self._login_done.set()

    def _on_rsp_settlement_confirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID: int, bIsLast: bool):
        if pRspInfo and getattr(pRspInfo, "ErrorID", 0) != 0:
            self._settle_failed = f"{pRspInfo.ErrorID}: {pRspInfo.ErrorMsg}"
        else:
            self._settle_failed = None
        self._settle_confirmed.set()

    def _on_rsp_order_insert(self, pInputOrder, pRspInfo, nRequestID: int, bIsLast: bool):
        oid = f"CTP-{pInputOrder.OrderRef}"
        msg = f"{pRspInfo.ErrorID}: {pRspInfo.ErrorMsg}" if pRspInfo and getattr(pRspInfo, "ErrorID", 0) != 0 else "ok"
        with self._lock:
            if oid in self._orders:
                self._orders[oid]["status"] = "rejected" if "ok" not in msg else "accepted"
                self._orders[oid]["msg"] = msg
        if "ok" not in msg:
            logger.warning("OpenCtpBroker: 委托拒绝 %s %s", oid, msg)

    def _on_rtn_order(self, pOrder):
        oid = f"CTP-{pOrder.OrderRef}"
        status_map = {
            "0": "all_traded",
            "1": "partial_traded",
            "3": "submitted",
            "5": "cancelled",
        }
        with self._lock:
            if oid in self._orders:
                self._orders[oid]["status"] = status_map.get(pOrder.OrderStatus, "unknown")
                self._orders[oid]["exchange_id"] = pOrder.ExchangeID
                self._orders[oid]["volume_traded"] = int(getattr(pOrder, "VolumeTraded", 0))

    def _on_rtn_trade(self, pTrade):
        sym = pTrade.InstrumentID
        direction = "long" if pTrade.Direction == DIRECTION_BUY else "short"
        offset = "open" if pTrade.OffsetFlag == OFFSET_OPEN else "close"
        size = int(pTrade.Volume)
        with self._lock:
            if sym not in self._positions:
                self._positions[sym] = {"direction": direction, "size": 0, "avg_price": 0.0}
            pos = self._positions[sym]
            if offset == "open":
                new_size = pos["size"] + size
                pos["avg_price"] = (pos["avg_price"] * pos["size"] + float(pTrade.Price) * size) / new_size if new_size > 0 else 0.0
                pos["size"] = new_size
                pos["direction"] = direction
            else:
                pos["size"] = max(0, pos["size"] - size)
                if pos["size"] == 0:
                    self._positions.pop(sym, None)
        logger.info("OpenCtpBroker: 成交 %s %s %d @ %.2f", sym, direction, size, float(pTrade.Price))

    def _on_err_rtn_order_insert(self, pInputOrder, pRspInfo):
        oid = f"CTP-{pInputOrder.OrderRef}"
        msg = f"{pRspInfo.ErrorID}: {pRspInfo.ErrorMsg}" if pRspInfo else "unknown"
        logger.warning("OpenCtpBroker: 错误报单回报 %s %s", oid, msg)
        with self._lock:
            if oid in self._orders:
                self._orders[oid]["status"] = "rejected"
                self._orders[oid]["msg"] = msg

    def _on_rsp_qry_position(self, pInvestorPosition, pRspInfo, nRequestID: int, bIsLast: bool):
        if pRspInfo and getattr(pRspInfo, "ErrorID", 0) != 0:
            logger.warning("OpenCtpBroker: 持仓查询失败 %s", pRspInfo.ErrorMsg)
            return
        if pInvestorPosition is None:
            return
        sym = pInvestorPosition.InstrumentID
        posi_dir = pInvestorPosition.PosiDirection  # '2'=多 '3'=空
        size = int(pInvestorPosition.Position)
        if size == 0:
            return
        direction = "long" if posi_dir == "2" else "short"
        with self._lock:
            if sym not in self._positions:
                self._positions[sym] = {"direction": direction, "size": 0, "avg_price": 0.0}
            self._positions[sym]["direction"] = direction
            self._positions[sym]["size"] = size
            self._positions[sym]["avg_price"] = float(getattr(pInvestorPosition, "OpenCost", 0.0) or 0.0) / max(size, 1)

    def _on_rsp_qry_instrument(self, pInstrument, pRspInfo, nRequestID: int, bIsLast: bool):
        if pRspInfo and getattr(pRspInfo, "ErrorID", 0) != 0:
            logger.warning("OpenCtpBroker: 合约查询失败 %s", pRspInfo.ErrorMsg)
            return
        if pInstrument is None:
            return
        sym = pInstrument.InstrumentID
        exg = pInstrument.ExchangeID
        with self._lock:
            self._instruments[sym] = {
                "exchange_id": exg,
                "product_id": getattr(pInstrument, "ProductID", ""),
                "long_margin_ratio": float(getattr(pInstrument, "LongMarginRatio", 0.0) or 0.0),
                "short_margin_ratio": float(getattr(pInstrument, "ShortMarginRatio", 0.0) or 0.0),
            }
        if bIsLast:
            logger.info("OpenCtpBroker: 合约列表已收齐, 共 %d 条", len(self._instruments))


        # ============================================================
# ============================================================
# ctpbee 封装 —— 仅在 ctpbee 可用时真正启用 (旧, 已被 openctp-ctp 替代)
# ============================================================
try:
    from ctpbee import CtpBee, OrderRequest as CtpbeeOrderRequest  # type: ignore
    _CTPBEE_OK = True
except Exception as e:  # noqa: BLE001
    _CTPBEE_OK = False
    _CTPBEE_IMPORT_ERR = e


if _CTPBEE_OK:
    class CtpbeeBroker(CtpBroker):
        """ctpbee 封装层 (旧, 已被 openctp-ctp 替代)"""
        def __init__(self, front_addr, broker_id, app_id, auth_code, investor_id, password, md_address=None):
            if not _CTPBEE_OK:
                raise RuntimeError("ctpbee 未安装或 import 失败")
            # 实际实现需要 ctpbee 库, 这里是占位
            raise NotImplementedError("CtpbeeBroker 完整实现需要 ctpbee 库, 推荐使用 OpenCtpBroker (openctp-ctp)")
else:
    class CtpbeeBroker(CtpBroker):
        """ctpbee 不可用时的占位类"""
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "ctpbee 未安装或 import 失败: %s. "
                "请先安装 Microsoft C++ Build Tools, 再执行 `pip install ctpbee`. "
                "或使用 OpenCtpBroker (openctp-ctp, 预编译 wheel 无需 MSVC)." % _CTPBEE_IMPORT_ERR
            )



def build_broker(cfg: dict) -> CtpBroker:
    """
    根据配置 dict 构造 broker.

    cfg 示例 (mock)::

        {"mode": "mock"}

    cfg 示例 (openctp / SimNow 新版)::

        {
            "mode": "openctp",
            "front_addr": "tcp://182.254.243.31:30001",   # 新看穿式前置
            "broker_id": "9999",
            "app_id": "simnow_client_test",               # SimNow 默认
            "auth_code": "0000000000000000",              # 16 个 0
            "investor_id": "...",
            "password": "...",                             # 必须是 SimNow 重置后的新密码
        }
    """
    mode = (cfg.get("mode") or "mock").lower()
    if mode == "mock":
        return MockCtpBroker(
            taker_slippage=float(cfg.get("taker_slippage", 0.0)),
            default_price=float(cfg.get("default_price", 5000.0)),
        )
    if mode == "openctp":
        return OpenCtpBroker(
            front_addr=cfg["front_addr"],
            broker_id=cfg["broker_id"],
            app_id=cfg["app_id"],
            auth_code=cfg["auth_code"],
            investor_id=cfg["investor_id"],
            password=cfg["password"],
            flow_path=cfg.get("flow_path", "./ctp_flow/"),
            timeout=float(cfg.get("timeout", 10.0)),
        )
    if mode == "ctpbee":
        return CtpbeeBroker(
            front_addr=cfg["front_addr"],
            broker_id=cfg["broker_id"],
            app_id=cfg["app_id"],
            auth_code=cfg["auth_code"],
            investor_id=cfg["investor_id"],
            password=cfg["password"],
            md_address=cfg.get("md_address"),
        )
    raise ValueError(f"Unknown broker mode: {mode}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    b = MockCtpBroker()
    b.connect()
    oid1 = b.send_order({"symbol": "TA2506", "direction": "long", "lots": 2})
    oid2 = b.send_order({"symbol": "MA2506", "direction": "short", "lots": 1})
    print("positions:", b.query_positions())
    b.close_all()
    print("after close:", b.query_positions())
    print("order log:", json.dumps(b.dump_order_log(), ensure_ascii=False, indent=2))
