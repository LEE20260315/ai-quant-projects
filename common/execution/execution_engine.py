#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
执行中枢（通用层 / common）
=====================================

把整套流水线 (信号 → 风控 → 仓位 → CTP) 串成可单测的对象。
ConfirmationBridge 接受移动端回调时, 调用本类处理。

设计:
  - 本类不依赖任何具体策略 (path1 / path2 都能用)
  - 仓位引擎抽象为 BaseSizer, 缺省用 FixedSizer(1 手/信号)
  - path2 的 10X 激进仓位模型从外部注入 (PositionSizer)
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# 允许以脚本方式直接运行 (`python execution_engine.py`)
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from .base_sizer import BaseSizer, FixedSizer, SizerDecision
from .risk_manager import (
    AccountSnapshot, RiskConfig, RiskLevel, RiskManager,
)
from .ctp_broker import CtpBroker, MockCtpBroker, OrderRequest, build_broker
from .push_notifier import (
    DingTalkNotifier, BarkNotifier, MultiNotifier, SignalCard,
)


# ============================================================
# 通用 fused signal 占位 (避免对 path2.fusion.signal_fusion 的硬依赖)
# ============================================================
@dataclass
class GenericFusedSignal:
    """
    common.execution 期望 fused 对象提供的最小属性集合.
    path1 / path2 各自的 FusedSignal 都可作为此类型的 duck typing 输入.
    """
    symbol: str
    strength: float = 0.0
    confidence: float = 0.0
    path1_consensus: int = 0
    path1_agreement: float = 0.0
    enhancement_applied: str = "none"
    # 兼容 path2 的扩展字段
    sl_atr_adj: float = 0.0
    tp_atr_adj: float = 0.0
    atr: float = 0.0

    def to_dict(self):
        return self.__dict__.copy()


# 兼容旧 API: 用 GenericFusedSignal 作为 fused 字段类型
FusedSignal = GenericFusedSignal


logger = logging.getLogger(__name__)


@dataclass
class PendingSignal:
    """待确认信号 (在 confirmation_bridge 收到移动端点击前缓存)"""
    trade_id: str
    symbol: str
    direction: int
    fused: FusedSignal
    signal_type: str
    stop_loss: float
    take_profit: float
    account_state: dict
    created_at: float
    entry_price: float = 0.0
    executed: bool = False
    skipped: bool = False
    result: Optional[dict] = None

    def to_card(self, pc_base_url: str) -> SignalCard:
        return SignalCard(
            signal_type=self.signal_type,
            symbol=self.symbol,
            direction="多" if self.direction == 1 else "空",
            suggested_lots=0,   # 等到 confirm 阶段再算
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            confidence=self.fused.confidence,
            fusion=self.fused.enhancement_applied,
            pc_base_url=pc_base_url,
            trade_id=self.trade_id,
            confirm_token="",  # 验证发生在 /execute 接口
        )


class ExecutionEngineError(Exception):
    """ExecutionEngine 抛出的业务异常 (区别于底层 broker / 风控异常)"""
    pass


class ExecutionEngine:
    """
    信号 → 风控 → 仓位 → CTP 的中央调度

    用法::

        from common.execution import ExecutionEngine, MockCtpBroker, PositionSizer
        # PositionSizer 是 path2 提供的 10X 仓位模型; 通用缺省用 FixedSizer

        engine = ExecutionEngine(
            broker=MockCtpBroker(),
            sizer=PositionSizer(),            # path2 用
            # sizer=FixedSizer(default_lots=1),  # 通用缺省
            pc_base_url="http://1.2.3.4:8000",
        )

        # 1) 信号出现 -> 入队待确认 -> 推钉钉
        card_trade_id = engine.queue_signal(symbol, direction, fused, ...)

        # 2) 移动端点 "确认下单"
        engine.confirm_trade(trade_id, confirm_token) -> dict
    """

    def __init__(
        self,
        broker: CtpBroker,
        pc_base_url: str = "http://127.0.0.1:8000",
        sizer: Optional[BaseSizer] = None,
        risk: Optional[RiskManager] = None,
        notifier: Optional[MultiNotifier] = None,
        signal_fusion=None,  # 兼容旧 API, 仅用于类型提示, 不被本类真正使用
        state_file: Optional[str] = None,
    ):
        self.broker = broker
        self.pc_base_url = pc_base_url
        self.sizer = sizer or FixedSizer()
        self.risk = risk or RiskManager()
        self.notifier = notifier or MultiNotifier()
        self.signal_fusion = signal_fusion
        self.state_file = state_file or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "tracking", "engine_state.json"
        )
        # 待确认信号池
        self._pending: Dict[str, PendingSignal] = {}
        self._lock = threading.RLock()
        # 注入强平回调到风控
        self.risk.register_force_close_hook(self._force_close_hook)
        # 绑定 broker: 仅在 broker 未连接时才连接 (避免重复连接导致 CTP 4097)
        if not getattr(broker, "is_connected", lambda: False)():
            try:
                self.broker.connect()
            except Exception as e:
                logger.warning("ExecutionEngine: broker.connect 失败: %s", e)

    # ------------------------------------------------- 绑定
    def bind_signal_fusion(self, signal_fusion) -> None:
        # 兼容旧 API: 现在不真正使用 signal_fusion 对象, 仅为接口兼容
        self.signal_fusion = signal_fusion
        logger.info("ExecutionEngine.bind_signal_fusion: 提示, v2 引擎已不再直接调用 SignalFusion, signal_fusion 仅作存档")

    def update_account(self, account_state: dict) -> None:
        """外部把当前账户快照塞进来, 后续 can_trade 校验就用它"""
        self.risk.attach_snapshot(AccountSnapshot(
            capital=float(account_state.get("capital", 0)),
            peak_capital=float(account_state.get("peak_capital", account_state.get("capital", 0))),
            positions=account_state.get("positions", {}),
            trade_log=account_state.get("trade_log", []),
        ))
        if isinstance(account_state.get("positions"), dict):
            self.sizer.sync_from_positions(account_state["positions"])

    # ------------------------------------------------- 信号入队
    def queue_signal(
        self,
        symbol: str,
        direction: int,
        fused: FusedSignal,
        signal_type: str = "分位短线",
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        account_state: Optional[dict] = None,
    ) -> str:
        """入队一个待确认信号, 同时推送钉钉 / Bark"""
        if account_state:
            self.update_account(account_state)
        if direction == 0:
            return ""
        trade_id = f"T-{int(time.time())}-{secrets.token_hex(4).upper()}"
        pending = PendingSignal(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            fused=fused,
            signal_type=signal_type,
            stop_loss=stop_loss,
            take_profit=take_profit,
            account_state=account_state or {},
            created_at=time.time(),
        )
        with self._lock:
            self._pending[trade_id] = pending
        # 推送
        card = pending.to_card(self.pc_base_url)
        push_result = self.notifier.push(card)
        logger.info(
            "入队待确认信号 trade_id=%s %s %s 推送=%s",
            trade_id, symbol, "多" if direction == 1 else "空", push_result,
        )
        return trade_id

    # ------------------------------------------------- 移动端回调
    def confirm_trade(self, trade_id: str, confirm_token: str) -> dict:
        """
        移动端点了 [确认下单] 后, 由 confirmation_bridge 调用本方法.
        校验 token → 真正下单 → 返回结果.
        """
        with self._lock:
            pending = self._pending.get(trade_id)
            if pending is None:
                return {"ok": False, "reason": "unknown_trade_id"}
            if pending.executed or pending.skipped:
                return {"ok": False, "reason": "trade_already_finalized", "result": pending.result}
            if not self._verify_token(confirm_token):
                return {"ok": False, "reason": "invalid_token"}

            # 真正执行 (使用 engine 自身实现, 不依赖任何具体 signal 模块)
            result = self._execute(pending)
            pending.executed = bool(result.get("ok"))
            pending.result = result
            return result

    def skip_trade(self, trade_id: str, confirm_token: str, reason: str = "user_skipped") -> dict:
        with self._lock:
            pending = self._pending.get(trade_id)
            if pending is None:
                return {"ok": False, "reason": "unknown_trade_id"}
            if not self._verify_token(confirm_token):
                return {"ok": False, "reason": "invalid_token"}
            pending.skipped = True
            pending.result = {"ok": False, "reason": reason}
            logger.info("用户跳过信号 trade_id=%s reason=%s", trade_id, reason)
            return pending.result

    # ------------------------------------------------- 真正下单 (内部)
    def _execute(self, pending: "PendingSignal") -> dict:
        """
        真正执行一笔交易:
          1) 风控: 硬熔断 / 资金不足 / 4 级风控 → 拦截
          2) 仓位: 调用 self.sizer.calc_lots() 决策手数
          3) 下单: 通过 self.broker.send_order() 推单
          4) 强平保护: 如果是 HARDBREAK_TRIP, 改下全平单

        返回 dict: {ok, reason?, order_id?, lots?, ...}
        """
        # 1) 风控检查
        if not self.risk.can_trade():
            return {
                "ok": False,
                "reason": "risk_block",
                "level": self.risk.risk_level.value,
            }
        # 2) 仓位计算
        acc = pending.account_state or {}
        equity = acc.get("equity") or acc.get("current_equity") or 0.0
        try:
            decision: SizerDecision = self.sizer.calc_lots(
                symbol=pending.symbol,
                account_equity=equity,
                consecutive_losses=(pending.account_state or {}).get("consecutive_losses", 0),
                fused=pending.fused,
            )
        except Exception as e:
            return {"ok": False, "reason": f"sizer_error:{e}"}
        # 风控降档 (level1_half 等会自动缩 50%/70%)
        try:
            risk_mult = self.risk.position_size_multiplier()
        except Exception:
            risk_mult = 1.0
        if risk_mult != 1.0:
            adjusted_lots = max(1, int(decision.lots * risk_mult))
            if adjusted_lots != decision.lots:
                logger.info(
                    "风控降档 %s: %d -> %d 手 (mult=%.2f)",
                    self.risk.risk_level.value, decision.lots, adjusted_lots, risk_mult,
                )
                decision = SizerDecision(
                    lots=adjusted_lots,
                    raw_lots=decision.raw_lots,
                    reason=decision.reason + f" | risk_mult={risk_mult:.2f}",
                    multiplier=decision.multiplier * risk_mult,
                )
        if decision.lots <= 0:
            return {"ok": False, "reason": "sizer_returned_zero_lots", "decision": str(decision)}
        # 3) 构造订单
        order_req = {
            "symbol": pending.symbol,
            "direction": "long" if pending.direction == 1 else "short",
            "lots": decision.lots,
            "price": pending.entry_price if pending.entry_price > 0 else 0.0,
            "order_type": "limit" if pending.entry_price > 0 else "market",
            "offset": "open",
            "fused": getattr(pending.fused, "to_dict", lambda: pending.fused.__dict__)()
                       if pending.fused else {},
        }
        # 4) 强平保护 (如果当前已 HARDBREAK_TRIP, 把 open 改成 close)
        if self.risk.risk_level == RiskLevel.HARDBREAK_TRIP:
            order_req["offset"] = "close"
        # 5) 下单
        try:
            order_id = self.broker.send_order(order_req)
        except Exception as e:
            return {"ok": False, "reason": f"broker_error:{e}"}
        logger.info("下单成功 trade_id=%s order_id=%s %s %d 手",
                    pending.trade_id, order_id, pending.symbol, decision.lots)
        return {
            "ok": True,
            "order_id": order_id,
            "lots": decision.lots,
            "decision": str(decision),
            "level": self.risk.risk_level.value,
        }

    def get_pending(self, trade_id: str) -> Optional[PendingSignal]:
        with self._lock:
            return self._pending.get(trade_id)

    def list_pending(self) -> List[PendingSignal]:
        with self._lock:
            return [p for p in self._pending.values() if not p.executed and not p.skipped]

    # ------------------------------------------------- 强平
    def _force_close_hook(self) -> List[str]:
        try:
            closed = self.broker.close_all()
            logger.critical("[HARDBREAK] ExecutionEngine 触发强平: %s", closed)
            return closed
        except Exception as e:
            logger.exception("强平失败: %s", e)
            return []

    # ------------------------------------------------- token
    def _verify_token(self, token: str) -> bool:
        # 简单实现: 任何非空 token 即放行. 
        # 生产环境应换成 JWT / HMAC, 配合 confirmation_bridge 的密钥.
        return bool(token) and len(token) >= 4

    # ------------------------------------------------- 状态持久化
    def save_state(self) -> None:
        if not self.state_file:
            return
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        data = {
            "pending": {
                tid: {
                    "trade_id": p.trade_id,
                    "symbol": p.symbol,
                    "direction": p.direction,
                    "signal_type": p.signal_type,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "executed": p.executed,
                    "skipped": p.skipped,
                    "created_at": p.created_at,
                } for tid, p in self._pending.items()
            },
            "trip_history": self.risk.trip_history,
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 简易自测
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    # 1) 构造
    broker = MockCtpBroker(default_price=5000.0)
    engine = ExecutionEngine(broker=broker, pc_base_url="http://127.0.0.1:8000")

    # 2) 模拟账户
    account_state = {
        "capital": 10_000,
        "peak_capital": 10_000,
        "positions": {},
        "trade_log": [],
        "current_equity": 10_000,
    }
    engine.update_account(account_state)

    # 3) 出一个信号 (用 GenericFusedSignal 通用)
    fused = GenericFusedSignal(
        symbol="TA2506", strength=0.7, confidence=0.8,
        path1_consensus=1, path1_agreement=0.7,
        enhancement_applied="same_dir:tp+0.30atr",
    )
    trade_id = engine.queue_signal(
        symbol="TA2506", direction=1, fused=fused,
        signal_type="分位短线 v3", stop_loss=4820, take_profit=5180,
        account_state=account_state,
    )
    print("trade_id =", trade_id)

    # 4) 移动端确认 (用合法 token)
    res_ok = engine.confirm_trade(trade_id, confirm_token="secret123")
    print("confirm ok ->", res_ok)

    # 5) 模拟硬熔断
    print("\n--- 模拟 42% 回撤 ---")
    account_state["capital"] = 5_800
    account_state["peak_capital"] = 10_000
    engine.update_account(account_state)
    fused2 = GenericFusedSignal(
        symbol="MA2506", strength=0.6, confidence=0.75,
        path1_consensus=-1, path1_agreement=0.6,
        enhancement_applied="none",
    )
    tid2 = engine.queue_signal("MA2506", -1, fused2, account_state=account_state)
    res_block = engine.confirm_trade(tid2, "secret123") if tid2 else {"ok": False, "reason": "no_signal"}
    print("hardbreak confirm ->", res_block)
    print("positions after:", broker.query_positions())
