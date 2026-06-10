#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
live_tracker_ctp.py — 接入 CTP 真下单的实盘跟踪器
========================================

设计：
  - 继承 LiveTracker, 复用信号/风控/仓位计算
  - override _execute_open / _execute_close, 改为调用 broker
  - 默认 dry-run (MockCtpBroker, 不联网), 加 --live 切真实 OpenCtpBroker
  - 所有真实订单写 ctp_order_log.json (可审计)
  - 3 品种交易所映射: TA→CZCE, RM→DCE, MA→CZCE

用法：
  # Dry-run (默认, 不接 CTP)
  python live_tracker_ctp.py daily

  # 真实 CTP (SimNow 前置, 需先设环境变量)
  $env:CTP_INVESTOR_ID="260042"; $env:CTP_PASSWORD="xibeilang@99"
  python live_tracker_ctp.py daily --live

  # 实时风控
  python live_tracker_ctp.py risk --interval 30

  # 紧急全平
  python live_tracker_ctp.py panic
"""
from __future__ import annotations
import os
import sys
import json
import argparse
from datetime import datetime

# 让 `data.parquet_loader` 相对导入能找到
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.chdir(_HERE)

# 跨路径共享的 CTP 层
from common.execution import build_broker, MockCtpBroker, infer_exchange_id
from common.execution.execution_engine import PendingSignal
from common.execution.push_notifier import SignalCard

# 路径二实盘跟踪器
from live_tracker import LiveTracker, PARAMS, SYMBOLS, INITIAL_CAPITAL, MAX_POSITIONS

# ============================================================
# 3 品种交易所映射
# ============================================================
SYMBOL_EXCHANGE = {
    "TA": "CZCE",  # PTA — 郑商所
    "RM": "DCE",   # 菜粕 — 大商所
    "MA": "CZCE",  # 甲醇 — 郑商所
}

# CTP 主力合约代码 (2026-06 当前, 7 月合约, CZCE/DCE 都用 3 位月份)
# SimNow 真实下单用具体月份, 主力连续合约不能直接下单
# 真实交易时要从 broker.query_instrument() 拿当前主力
SYMBOL_CTP_CODE = {
    "TA": "TA607",  # 2026-07 PTA — 郑商所
    "RM": "RM607",  # 2026-07 菜粕 — 大商所
    "MA": "MA607",  # 2026-07 甲醇 — 郑商所
}


class LiveTrackerCTP(LiveTracker):
    """接 CTP 真下单的 LiveTracker 升级版"""

    def __init__(self, broker=None, dry_run=True, order_log_path=None):
        super().__init__()
        self.dry_run = dry_run
        if broker is None:
            if dry_run:
                self.broker = MockCtpBroker()
                self.broker.connect()
                print("[BROKER] MockCtpBroker 已连接 (dry-run)")
            else:
                self.broker = self._build_real_broker()
        else:
            self.broker = broker
        self.order_log_path = order_log_path or os.path.join(_HERE, "tracking", "ctp_order_log.json")
        os.makedirs(os.path.dirname(self.order_log_path), exist_ok=True)
        self._order_log: list[dict] = self._load_order_log()

    def _build_real_broker(self):
        investor_id = os.environ.get("CTP_INVESTOR_ID", "")
        password = os.environ.get("CTP_PASSWORD", "")
        if not investor_id or not password:
            raise RuntimeError(
                "实盘模式需要环境变量 CTP_INVESTOR_ID 和 CTP_PASSWORD\n"
                "示例: $env:CTP_INVESTOR_ID='260042'; $env:CTP_PASSWORD='xibeilang@99'"
            )
        cfg = {
            "mode": "openctp",
            "front_addr": os.environ.get("CTP_FRONT_ADDR", "tcp://182.254.243.31:30001"),
            "broker_id": os.environ.get("CTP_BROKER_ID", "9999"),
            "app_id": "simnow_client_test",
            "auth_code": "0000000000000000",
            "investor_id": investor_id,
            "password": password,
            "flow_path": os.environ.get("CTP_FLOW_PATH", "./ctp_flow/"),
            "timeout": float(os.environ.get("CTP_TIMEOUT", "10")),
        }
        broker = build_broker(cfg)
        broker.connect()
        print(f"[BROKER] OpenCtpBroker 已连接: {cfg['front_addr']} 账号={cfg['investor_id']}")
        return broker

    def _load_order_log(self) -> list[dict]:
        if os.path.exists(self.order_log_path):
            try:
                with open(self.order_log_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return []

    def _save_order_log(self):
        with open(self.order_log_path, "w", encoding="utf-8") as f:
            json.dump(self._order_log, f, ensure_ascii=False, indent=2, default=str)

    def _record_order(self, action: str, symbol: str, **kwargs):
        """记录每次下单到 order_log"""
        entry = {
            "ts": datetime.now().isoformat(),
            "mode": "dry-run" if self.dry_run else "live",
            "action": action,        # open / close
            "symbol": symbol,
            **kwargs,
        }
        self._order_log.append(entry)
        self._save_order_log()
        return entry

    def _execute_open(self, symbol, direction, price, atr, fused_signal, entry_type="revert"):
        """覆盖父类: 真实下单到 broker"""
        spec = self.loader.get_spec(symbol)
        if spec is None:
            print(f"  [SKIP] {symbol}: 品种规格未找到")
            return None

        # ---- 仓位计算 (沿用父类逻辑) ----
        margin_needed = price * spec.multiplier * spec.margin_ratio
        if margin_needed > self.state["capital"] * 0.30:
            margin_needed = self.state["capital"] * 0.30
        total_margin = sum(p.get("margin_used", 0) for p in self.state["positions"].values())
        if total_margin + margin_needed > self.state["capital"] * 0.60:
            print(f"  [SKIP] {symbol}: 总仓位超限")
            return None
        size = max(1, int(margin_needed / (price * spec.multiplier * spec.margin_ratio)))
        actual_margin = price * spec.multiplier * size * spec.margin_ratio
        if actual_margin > self.state["capital"] * 0.30:
            size = max(1, int(self.state["capital"] * 0.30 / (price * spec.multiplier * spec.margin_ratio)))
            actual_margin = price * spec.multiplier * size * spec.margin_ratio

        # ---- ATR 止损止盈 (沿用父类) ----
        if entry_type == "trend" and PARAMS.trend_entry_enabled:
            sl_mult = PARAMS.trend_atr_stop_mult
            tp_mult = PARAMS.trend_atr_take_mult
            max_hold = PARAMS.trend_max_hold_days
        else:
            sl_mult = PARAMS.atr_stop_mult
            tp_mult = PARAMS.atr_take_mult
            max_hold = PARAMS.max_hold_days
        if fused_signal:
            sl_mult += fused_signal.sl_atr_adj
            tp_mult += fused_signal.tp_atr_adj
            max_hold += fused_signal.hold_days_adj
            sl_mult = max(0.5, sl_mult)
            tp_mult = max(0.5, tp_mult)
            max_hold = max(2, max_hold)

        if direction == 1:
            stop_loss = price - atr * sl_mult
            take_profit = price + atr * tp_mult
        else:
            stop_loss = price + atr * sl_mult
            take_profit = price - atr * tp_mult

        # ---- 调 broker 真下单 ----
        ctp_code = SYMBOL_CTP_CODE.get(symbol, f"{symbol}2609")
        exchange = SYMBOL_EXCHANGE.get(symbol, infer_exchange_id(symbol))
        dir_text = "buy" if direction == 1 else "sell"

        try:
            order_id = self.broker.send_order({
                "symbol": ctp_code,
                "direction": dir_text,
                "lots": size,
                "price": 0.0,  # 市价单
                "order_type": "market",
                "offset": "open",
                "exchange": exchange,
            })
            ok = True
        except Exception as e:
            order_id = "ERROR"
            ok = False
            print(f"  [BROKER ERROR] {symbol} {dir_text} {size}手: {e}")

        self._record_order(
            "open", symbol,
            ctp_code=ctp_code, exchange=exchange,
            direction=dir_text, size=size, price=price,
            stop_loss=round(stop_loss, 2), take_profit=round(take_profit, 2),
            max_hold_days=max_hold,
            broker_order_id=order_id, broker_ok=ok,
            entry_type=entry_type, fusion=fused_signal.enhancement_applied if fused_signal else "none",
        )

        if not ok:
            return None

        # ---- 写 state (模拟仓位记账) ----
        self.state["positions"][symbol] = {
            "direction": direction,
            "entry_price": round(price, 2),
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
            "size": size,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "max_hold_days": max_hold,
            "margin_used": round(actual_margin, 2),
            "ctp_code": ctp_code,
            "ctp_order_id": order_id,
            "fusion": fused_signal.enhancement_applied if fused_signal else "none",
            "dominant_strategy": fused_signal.dominant_strategy if fused_signal else "none",
        }
        dir_cn = "多" if direction == 1 else "空"
        mode_tag = "[DRY]" if self.dry_run else "[LIVE]"
        print(f"  {mode_tag} [EXEC OPEN] {symbol}({ctp_code}.{exchange}) {dir_cn}{size}手 @ {price:.0f} | "
              f"broker_order={order_id} | SL={stop_loss:.0f} TP={take_profit:.0f}")
        # 推送: CTP 真下单告警
        try:
            self.notifier.push(SignalCard(
                signal_type=(f"趋势顺势/{mode_tag}" if entry_type == "trend" else f"分位反转/{mode_tag}"),
                symbol=symbol, direction=dir_cn,
                suggested_lots=size,
                stop_loss=stop_loss, take_profit=take_profit,
                fusion=f"broker_order={order_id}, ok={ok}",
                trade_id=str(order_id),
            ))
        except Exception as e:
            print(f"  [PUSH WARN] {e}")
        return self.state["positions"][symbol]

    def _execute_close(self, symbol, exit_price, exit_reason):
        """覆盖父类: 真实平仓到 broker"""
        pos = self.state["positions"].get(symbol)
        if pos is None:
            return None
        spec = self.loader.get_spec(symbol)
        size = pos.get("size", 1)
        direction = pos["direction"]
        entry_price = pos["entry_price"]
        ctp_code = pos.get("ctp_code", SYMBOL_CTP_CODE.get(symbol, f"{symbol}2609"))
        exchange = SYMBOL_EXCHANGE.get(symbol, infer_exchange_id(symbol))

        # 盈亏计算
        # 兼容旧 state 文件里 entry_price 仍是 str 的情况
        entry_price = float(pos["entry_price"])
        ep = entry_price
        if direction == 1:
            gross_pnl = (exit_price - ep) * spec.multiplier * size
        else:
            gross_pnl = (ep - exit_price) * spec.multiplier * size
        # Bug 2 修复: 与回测 0.00015+0.0002 对齐
        cost = (ep + exit_price) * spec.multiplier * size * (0.00015 + 0.0002)
        net_pnl = gross_pnl - cost
        self.state["capital"] += net_pnl
        if self.state["capital"] > self.state["peak_capital"]:
            self.state["peak_capital"] = self.state["capital"]

        # ---- 调 broker 真平仓 ----
        # 平仓方向与开仓相反
        close_dir = "sell" if direction == 1 else "buy"
        try:
            order_id = self.broker.send_order({
                "symbol": ctp_code,
                "direction": close_dir,
                "lots": size,
                "price": 0.0,  # 市价平
                "order_type": "market",
                "offset": "close",
                "exchange": exchange,
            })
            ok = True
        except Exception as e:
            order_id = "ERROR"
            ok = False
            print(f"  [BROKER ERROR] 平仓 {symbol} {size}手: {e}")

        self._record_order(
            "close", symbol,
            ctp_code=ctp_code, exchange=exchange,
            direction=close_dir, size=size, price=exit_price,
            entry_price=entry_price, pnl=round(net_pnl, 2),
            exit_reason=exit_reason,
            broker_order_id=order_id, broker_ok=ok,
        )

        if not ok:
            return None

        # ---- 写 trade_log ----
        from datetime import datetime as _dt
        hold_days = (_dt.now() - _dt.strptime(pos["entry_date"], "%Y-%m-%d")).days
        trade_record = {
            "symbol": symbol,
            "ctp_code": ctp_code,
            "direction": "long" if direction == 1 else "short",
            "entry_date": pos["entry_date"],
            "exit_date": _dt.now().strftime("%Y-%m-%d"),
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "size": size,
            "pnl": round(net_pnl, 2),
            "hold_days": hold_days,
            "exit_reason": exit_reason,
            "capital_after": round(self.state["capital"], 2),
            "fusion": pos.get("fusion", "none"),
            "ctp_order_id": order_id,
        }
        self.state["trade_log"].append(trade_record)
        del self.state["positions"][symbol]

        dir_cn = "多" if direction == 1 else "空"
        mode_tag = "[DRY]" if self.dry_run else "[LIVE]"
        print(f"  {mode_tag} [EXEC CLOSE] {symbol} {dir_cn}平 {size}手 | "
              f"原因={exit_reason} | 入场={entry_price:.0f} 出场={exit_price:.0f} | "
              f"盈亏={net_pnl:+.0f}元 | broker_order={order_id}")
        # 推送: CTP 真平仓告警
        try:
            self.notifier.push(SignalCard(
                signal_type=f"平仓/{exit_reason}/{mode_tag}",
                symbol=symbol, direction=dir_cn,
                suggested_lots=size,
                stop_loss=exit_price, take_profit=exit_price,
                fusion=f"pnl={net_pnl:+.0f}元, broker_order={order_id}",
                trade_id=str(order_id),
            ))
        except Exception as e:
            print(f"  [PUSH WARN] {e}")
        return trade_record

    def panic_close_all(self):
        """紧急全平: 调 broker.close_all() + 清 state"""
        print("\n" + "=" * 60)
        print("⚠️  PANIC CLOSE ALL — 紧急全平")
        print("=" * 60)
        if not self.state["positions"]:
            print("  当前无持仓, 跳过")
            return
        # 先调 broker 真平
        try:
            closed = self.broker.close_all()
            print(f"  [BROKER] 已发强平: {closed}")
        except Exception as e:
            print(f"  [BROKER ERROR] {e}")
        # 再按当前价模拟平仓记账
        for sym in list(self.state["positions"].keys()):
            df = self._get_latest_data(sym)
            exit_price = df.iloc[-1]["close"] if df is not None and len(df) > 0 else self.state["positions"][sym]["entry_price"]
            self._execute_close(sym, exit_price, "panic")
        self._save_state()
        print("  紧急全平完成")


def main():
    parser = argparse.ArgumentParser(description="实盘跟踪 v2 (CTP 真下单)")
    parser.add_argument("mode", choices=["daily", "risk", "both", "panic"], default="daily", nargs="?")
    parser.add_argument("--live", action="store_true", help="接真实 OpenCtpBroker (默认 dry-run)")
    parser.add_argument("--interval", type=int, default=60, help="实时风控检查间隔(秒)")
    args = parser.parse_args()

    dry_run = not args.live
    print(f"\n=== Live Tracker v2 (CTP) | mode={args.mode} | {'DRY-RUN' if dry_run else '🟢 LIVE'} ===\n")

    tracker = LiveTrackerCTP(dry_run=dry_run)

    if args.mode == "panic":
        tracker.panic_close_all()
        return

    if args.mode in ("daily", "both"):
        tracker.run_daily()

    if args.mode in ("risk", "both"):
        tracker.run_realtime_risk(interval=args.interval)


if __name__ == "__main__":
    import io
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    main()
