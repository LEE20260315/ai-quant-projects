#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
移动端确认桥接器 (Path 2 / 10X Aggressive Growth)
=========================================

按规划要求:

  1. 在本地 24h PC 上跑一个 FastAPI 监听服务
  2. 接收手机端发来的 TradeID + ConfirmToken
  3. 携带正确 Token 才放行 (签名验证)
  4. 端点:
       GET  /execute?id=xxx&token=yyy   -> 真下单
       GET  /skip?id=xxx&token=yyy      -> 跳过
       GET  /status                     -> 服务状态 + 待处理列表
       GET  /hardbreak                  -> 手动触发硬熔断
       POST /queue                      -> 接收新信号 (供 strategy -> bridge 内部使用)

启动::

    uvicorn execution.confirmation_bridge:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import hmac
import hashlib
import logging
import os
import secrets
import sys
import time
from dataclasses import asdict
from typing import Optional

# 让脚本可以直接以模块形式运行
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

try:
    from fastapi import FastAPI, HTTPException, Query  # type: ignore
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse  # type: ignore
    from pydantic import BaseModel, Field  # type: ignore
    _FASTAPI_OK = True
except ImportError:
    _FASTAPI_OK = False
    # Stubs to make the module importable without fastapi
    FastAPI = None  # type: ignore
    HTTPException = None  # type: ignore
    Query = None  # type: ignore
    HTMLResponse = None  # type: ignore
    JSONResponse = None  # type: ignore
    PlainTextResponse = None  # type: ignore

    class BaseModel:  # type: ignore
        pass

    def Field(*args, **kwargs):  # type: ignore
        return None
import json

from .execution_engine import ExecutionEngine, GenericFusedSignal
from .ctp_broker import MockCtpBroker, build_broker
from .push_notifier import DingTalkNotifier, BarkNotifier, MultiNotifier
from .risk_manager import RiskManager
from .base_sizer import FixedSizer


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# 自定义 JSONResponse: 默认 ensure_ascii=False 以保留中文
class UTF8JSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


# ============================================================
# 配置
# ============================================================
APP_HOST = os.environ.get("BRIDGE_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("BRIDGE_PORT", "8000"))
# 签名密钥. 生产环境应放环境变量.
APP_SECRET = os.environ.get("BRIDGE_SECRET", "change-me-in-production")
PC_BASE_URL = os.environ.get("PC_BASE_URL", f"http://127.0.0.1:{APP_PORT}")
BROKER_MODE = os.environ.get("BROKER_MODE", "mock")
# 钉钉 / Bark
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
BARK_KEY = os.environ.get("BARK_KEY", "")


# ============================================================
# Token 工具
# ============================================================
def make_token(trade_id: str, secret: str = APP_SECRET) -> str:
    """HMAC 短签名 -> 给移动端用作 confirm_token"""
    msg = f"{trade_id}:{int(time.time()) // 600}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:24]


def verify_token(trade_id: str, token: str, secret: str = APP_SECRET) -> bool:
    """校验 token (允许 30 分钟漂移, 即 3 个 10 分钟窗口)"""
    now_window = int(time.time()) // 600
    for offset in (-1, 0, 1, 2, 3):
        msg = f"{trade_id}:{now_window + offset}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:24]
        if hmac.compare_digest(expected, token):
            return True
    return False


# ============================================================
# 全局执行引擎 (供 service 内部用, 也可外部 import)
# ============================================================
def build_default_engine() -> ExecutionEngine:
    """构造一个默认的 ExecutionEngine (mock / openctp 自动切换)."""
    cfg = {"mode": BROKER_MODE}
    if BROKER_MODE == "openctp":
        cfg.update({
            "front_addr":   os.environ.get("CTP_FRONT_ADDR", "tcp://180.168.146.187:10201"),
            "broker_id":    os.environ.get("CTP_BROKER_ID", "9999"),
            "app_id":       os.environ.get("CTP_APP_ID", "simnow_client_test"),
            "auth_code":    os.environ.get("CTP_AUTH_CODE", "0000000000000000"),
            "investor_id":  os.environ.get("CTP_INVESTOR_ID", ""),
            "password":     os.environ.get("CTP_PASSWORD", ""),
            "flow_path":    os.environ.get("CTP_FLOW_PATH", "./ctp_flow/"),
        })
    elif BROKER_MODE == "ctpbee":
        cfg.update({
            "front_addr":   os.environ.get("CTP_FRONT_ADDR", "tcp://180.168.146.187:10201"),
            "broker_id":    os.environ.get("CTP_BROKER_ID", "9999"),
            "app_id":       os.environ.get("CTP_APP_ID", "simnow_client_test"),
            "auth_code":    os.environ.get("CTP_AUTH_CODE", "0000000000000000"),
            "investor_id":  os.environ.get("CTP_INVESTOR_ID", ""),
            "password":     os.environ.get("CTP_PASSWORD", ""),
        })
    broker = build_broker(cfg)
    notifier = MultiNotifier(
        dingtalk=DingTalkNotifier(webhook=DINGTALK_WEBHOOK or None),
        bark=BarkNotifier(key=BARK_KEY or None),
    )
    engine = ExecutionEngine(
        broker=broker,
        pc_base_url=PC_BASE_URL,
        sizer=_build_sizer(),
        risk=RiskManager(),
        notifier=notifier,
    )
    return engine


def _build_sizer():
    """
    智能选择仓位器:
      - 如果 path2_lightweight.execution.position_sizer 可用, 用 10X 模型
      - 否则回退到 FixedSizer
    """
    try:
        import sys
        _p2 = os.path.join(os.path.dirname(__file__), "..", "..", "path2_lightweight", "execution")
        if _p2 not in sys.path and os.path.isdir(_p2):
            sys.path.insert(0, _p2)
        from position_sizer import PositionSizer
        logger.info("confirmation_bridge: 装载 Path2 PositionSizer (10X 模型)")
        return PositionSizer()
    except Exception as e:
        logger.info("confirmation_bridge: Path2 PositionSizer 不可用, 回退 FixedSizer: %s", e)
        return FixedSizer(default_lots=1)


# 全局单例 (uvicorn 启动时构建)
_engine: Optional[ExecutionEngine] = None


def get_engine() -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = build_default_engine()
    return _engine


# ============================================================
# FastAPI 应用
# ============================================================
if _FASTAPI_OK:
    app = FastAPI(
        title="Path2 Confirmation Bridge",
        version="1.0.0",
        description="手机端确认 / 跳过信号, 触发 CTP 下单",
    default_response_class=UTF8JSONResponse,
)


class QueueSignalRequest(BaseModel):
    symbol: str
    direction: int = Field(..., description="1=多, -1=空, 0=无信号")
    signal_type: str = "分位短线 v3"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    fused: dict = Field(default_factory=dict)
    account_state: dict = Field(default_factory=dict)


@app.get("/", response_class=HTMLResponse)
def index():
    pending = get_engine().list_pending()
    rows = "\n".join(
        f"<tr><td>{p.trade_id}</td><td>{p.symbol}</td><td>{'多' if p.direction==1 else '空'}</td>"
        f"<td>{p.signal_type}</td><td>{int(p.created_at)}</td></tr>"
        for p in pending
    ) or "<tr><td colspan=5>无待处理信号</td></tr>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Path2 Bridge</title>
<style>body{{font-family:sans-serif;max-width:880px;margin:30px auto;padding:0 16px;}}
table{{border-collapse:collapse;width:100%;}}th,td{{border:1px solid #ddd;padding:8px;text-align:left;}}
th{{background:#f3f3f3;}}code{{background:#f5f5f5;padding:1px 4px;}}</style></head>
<body>
<h2>Path 2 Confirmation Bridge</h2>
<p>状态: <b>运行中</b> | Broker: {BROKER_MODE} | PC_URL: {PC_BASE_URL}</p>
<h3>待处理信号 ({len(pending)})</h3>
<table><tr><th>TradeID</th><th>Symbol</th><th>Dir</th><th>Type</th><th>Created</th></tr>{rows}</table>
<h3>端点</h3>
<ul>
  <li><code>GET /status</code> — JSON 服务状态</li>
  <li><code>GET /execute?id=...&amp;token=...</code> — 确认下单</li>
  <li><code>GET /skip?id=...&amp;token=...</code> — 跳过信号</li>
  <li><code>POST /queue</code> — 推入新信号 (JSON body)</li>
  <li><code>GET /hardbreak</code> — 手动触发硬熔断</li>
</ul>
</body></html>"""


@app.get("/status")
def status():
    engine = get_engine()
    return {
        "ok": True,
        "engine": "running",
        "broker_mode": BROKER_MODE,
        "pc_base_url": PC_BASE_URL,
        "pending_count": len(engine.list_pending()),
        "pending": [
            {
                "trade_id": p.trade_id,
                "symbol": p.symbol,
                "direction": "long" if p.direction == 1 else "short",
                "signal_type": p.signal_type,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "created_at": int(p.created_at),
            }
            for p in engine.list_pending()
        ],
        "tripped": engine.risk._tripped,
    }


@app.get("/execute")
def execute(
    id: str = Query(..., description="trade_id"),
    token: str = Query(..., description="HMAC 短签名"),
):
    engine = get_engine()
    if not verify_token(id, token):
        raise HTTPException(status_code=401, detail="invalid token")
    result = engine.confirm_trade(id, token)
    if not result.get("ok") and result.get("reason") == "unknown_trade_id":
        raise HTTPException(status_code=404, detail=result)
    return JSONResponse(result)


@app.get("/skip")
def skip(
    id: str = Query(...),
    token: str = Query(...),
    reason: str = Query("user_skipped"),
):
    engine = get_engine()
    if not verify_token(id, token):
        raise HTTPException(status_code=401, detail="invalid token")
    result = engine.skip_trade(id, token, reason)
    return JSONResponse(result)


@app.post("/queue")
def queue_signal(req: QueueSignalRequest):
    """外部系统 (live_tracker) 推入新信号"""
    engine = get_engine()
    # 把 dict 反序列化成 GenericFusedSignal
    fused = GenericFusedSignal(
        symbol=req.symbol,
        strength=float(req.fused.get("strength", 0.5)),
        confidence=float(req.fused.get("confidence", 0.5)),
        path1_consensus=int(req.fused.get("path1_consensus", 0)),
        path1_agreement=float(req.fused.get("path1_agreement", 0.0)),
        enhancement_applied=req.fused.get("enhancement_applied", "none"),
    )
    trade_id = engine.queue_signal(
        symbol=req.symbol,
        direction=req.direction,
        fused=fused,
        signal_type=req.signal_type,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        account_state=req.account_state,
    )
    if not trade_id:
        return {"ok": False, "reason": "no_signal"}
    token = make_token(trade_id)
    base = PC_BASE_URL.rstrip("/")
    return {
        "ok": True,
        "trade_id": trade_id,
        "token": token,
        "execute_url": f"{base}/execute?id={trade_id}&token={token}",
        "skip_url":    f"{base}/skip?id={trade_id}&token={token}",
    }


@app.get("/hardbreak")
def hardbreak():
    engine = get_engine()
    closed = engine.risk.force_close_all()
    return {"ok": True, "tripped": engine.risk._tripped, "closed": closed}


# ============================================================
# 启动辅助
# ============================================================
def main() -> None:
    """直接以 python 启动此文件"""
    import uvicorn
    print(f"启动 Confirmation Bridge: {APP_HOST}:{APP_PORT}  broker={BROKER_MODE}")
    uvicorn.run("execution.confirmation_bridge:app",
                host=APP_HOST, port=APP_PORT, reload=False)


if __name__ == "__main__":
    main()
