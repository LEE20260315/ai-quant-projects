#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模拟券商（不接真实 CTP/EMT）
==============================

接口：
  - submit_order(symbol, direction, qty, price, t_date) -> (order_id, fill_status)
  - settle(t_date) -> dict（已实现 + 未实现 PnL）
  - get_position(symbol) -> dict
  - list_open_positions() -> list

持久化：paper_trading/orders.db（SQLite）
表：
  - orders(订单表)
  - fills(成交表)
  - positions(持仓表)
  - nav(日终净值)
"""
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config as cfg


logger = logging.getLogger("paper_trading.sim_broker")


# ==================== 初始化表 ====================
def _init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id      TEXT PRIMARY KEY,
        symbol        TEXT NOT NULL,
        direction     TEXT NOT NULL,  -- LONG / SHORT
        qty           INTEGER NOT NULL,
        price         REAL NOT NULL,
        t_date        TEXT NOT NULL,  -- 信号日期 (YYYY-MM-DD)
        status        TEXT NOT NULL,  -- PENDING / FILLED / REJECTED
        filled_qty    INTEGER DEFAULT 0,
        avg_fill_price REAL DEFAULT 0,
        created_at    TEXT NOT NULL,
        rejected_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS fills (
        fill_id       TEXT PRIMARY KEY,
        order_id      TEXT NOT NULL,
        symbol        TEXT NOT NULL,
        direction     TEXT NOT NULL,
        qty           INTEGER NOT NULL,
        price         REAL NOT NULL,
        t_date        TEXT NOT NULL,
        created_at    TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS positions (
        symbol        TEXT PRIMARY KEY,
        direction     TEXT NOT NULL,  -- LONG / SHORT
        qty           INTEGER NOT NULL,
        entry_price   REAL NOT NULL,
        entry_date    TEXT NOT NULL,
        last_price    REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS nav (
        t_date        TEXT PRIMARY KEY,
        cash          REAL NOT NULL,
        market_value  REAL NOT NULL,
        realized_pnl  REAL NOT NULL,
        unrealized_pnl REAL NOT NULL,
        total_equity  REAL NOT NULL,
        drawdown      REAL NOT NULL,
        layer2_active INTEGER NOT NULL DEFAULT 0,
        portfolio_stopped INTEGER NOT NULL DEFAULT 0
    );
    """)
    conn.commit()
    conn.close()


class SimBroker:
    """模拟券商"""

    def __init__(self, db_path: str = cfg.ORDERS_DB_PATH, initial_capital: float = cfg.INITIAL_CAPITAL):
        self.db_path = db_path
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.peak_equity = initial_capital
        _init_db(db_path)

    # ------------------- 下单 -------------------
    def submit_order(
        self,
        symbol: str,
        direction: str,
        qty: int,
        price: float,
        t_date: str,
        risk_gate: Optional[object] = None,
    ) -> Tuple[str, str]:
        """
        提交订单

        Returns:
            (order_id, status)  status ∈ {PENDING, FILLED, REJECTED}
        """
        assert direction in ("LONG", "SHORT")
        assert qty > 0
        assert price > 0

        symbol = symbol.upper()

        # 风控检查（可选）
        if risk_gate is not None:
            ok, reason = risk_gate.pre_trade_check(self, symbol, direction, qty, price)
            if not ok:
                return self._record_rejected(symbol, direction, qty, price, t_date, reason)

        order_id = str(uuid.uuid4())[:12]
        created_at = datetime.now().isoformat(timespec="seconds")
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO orders
               (order_id, symbol, direction, qty, price, t_date, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
            (order_id, symbol, direction, qty, price, t_date, created_at),
        )
        conn.commit()
        conn.close()
        logger.info(f"[ORDER] {order_id} {symbol} {direction} qty={qty} price={price} t_date={t_date} PENDING")

        # T+1 撮合占位：信号当日记 PENDING，settle 时才撮合
        return order_id, "PENDING"

    def _record_rejected(self, symbol, direction, qty, price, t_date, reason):
        order_id = str(uuid.uuid4())[:12]
        created_at = datetime.now().isoformat(timespec="seconds")
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO orders
               (order_id, symbol, direction, qty, price, t_date, status, created_at, rejected_reason)
               VALUES (?, ?, ?, ?, ?, ?, 'REJECTED', ?, ?)""",
            (order_id, symbol, direction, qty, price, t_date, created_at, reason),
        )
        conn.commit()
        conn.close()
        logger.warning(f"[REJECTED] {order_id} {symbol} {direction} qty={qty} reason={reason}")
        return order_id, "REJECTED"

    # ------------------- 撮合（settle 时调用）-------------------
    def _match_pending(self, last_prices: Dict[str, float], t_date: str) -> Tuple[int, float]:
        """撮合所有 PENDING 订单；按 last_prices 撮合（T+1 撮合占位）
        Returns: (filled_count, realized_delta)
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT order_id, symbol, direction, qty, price FROM orders WHERE status='PENDING' AND t_date <= ?", (t_date,))
        pending = cur.fetchall()
        filled_count = 0
        realized_total = 0.0

        for order_id, symbol, direction, qty, price in pending:
            market_price = last_prices.get(symbol, price)
            # 滑点：买入 + 滑点，卖出 - 滑点
            slip_ticks = cfg.SLIPPAGE_TICKS * cfg.get_contract_param(symbol)["tick"]
            fill_price = market_price + slip_ticks if direction == "LONG" else market_price - slip_ticks

            fill_id = str(uuid.uuid4())[:12]
            cur.execute(
                """INSERT INTO fills
                   (fill_id, order_id, symbol, direction, qty, price, t_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (fill_id, order_id, symbol, direction, qty, fill_price, t_date, datetime.now().isoformat(timespec="seconds")),
            )
            cur.execute(
                "UPDATE orders SET status='FILLED', filled_qty=?, avg_fill_price=? WHERE order_id=?",
                (qty, fill_price, order_id),
            )
            realized_delta, _ = self._apply_position(symbol, direction, qty, fill_price, t_date, cur)
            realized_total += realized_delta
            filled_count += 1
            logger.info(f"[FILL] {order_id} -> {fill_id} {symbol} {direction} {qty}@{fill_price} realized_delta={realized_delta:+.0f}")

        conn.commit()
        conn.close()
        return filled_count, realized_total

    def _apply_position(self, symbol, direction, qty, fill_price, t_date, cur):
        """更新持仓表（开仓/加仓/反手/平仓），返回 (realized_delta, action)"""
        cur.execute("SELECT direction, qty, entry_price FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()

        if row is None:
            # 新开仓
            cur.execute(
                """INSERT INTO positions (symbol, direction, qty, entry_price, entry_date, last_price)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (symbol, direction, qty, fill_price, t_date, fill_price),
            )
            return (0.0, "OPEN")

        prev_dir, prev_qty, prev_price = row
        if prev_dir == direction:
            # 同向加仓：均价加权
            new_qty = prev_qty + qty
            new_price = (prev_qty * prev_price + qty * fill_price) / new_qty
            cur.execute(
                "UPDATE positions SET qty=?, entry_price=?, last_price=? WHERE symbol=?",
                (new_qty, new_price, fill_price, symbol),
            )
            return (0.0, "ADD")

        # 反向：先算减仓部分的已实现 PnL
        params = cfg.get_contract_param(symbol)
        close_qty = min(qty, prev_qty)
        diff = (fill_price - prev_price) * close_qty * params["multiplier"]
        if prev_dir == "LONG":
            realized_delta = diff
        else:
            realized_delta = -diff

        if qty < prev_qty:
            # 部分平仓
            cur.execute(
                "UPDATE positions SET qty=?, last_price=? WHERE symbol=?",
                (prev_qty - qty, fill_price, symbol),
            )
            return (realized_delta, "PARTIAL_CLOSE")
        elif qty == prev_qty:
            # 全平
            cur.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            return (realized_delta, "CLOSE")
        else:
            # 反手：先全平旧仓，再开新仓
            cur.execute(
                """UPDATE positions SET direction=?, qty=?, entry_price=?, last_price=? WHERE symbol=?""",
                (direction, qty - prev_qty, fill_price, fill_price, symbol),
            )
            return (realized_delta, "REVERSE")

    # ------------------- 撤单 -------------------
    def cancel_pending(self, symbol: Optional[str] = None) -> int:
        """撤销 PENDING 订单（指定品种或全部）"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if symbol:
            cur.execute("UPDATE orders SET status='CANCELLED' WHERE status='PENDING' AND symbol=?", (symbol,))
        else:
            cur.execute("UPDATE orders SET status='CANCELLED' WHERE status='PENDING'")
        n = cur.rowcount
        conn.commit()
        conn.close()
        return n

    # ------------------- 持仓 -------------------
    def list_open_positions(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT symbol, direction, qty, entry_price, entry_date, last_price FROM positions")
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "symbol": r[0],
                "direction": r[1],
                "qty": r[2],
                "entry_price": r[3],
                "entry_date": r[4],
                "last_price": r[5],
            }
            for r in rows
        ]

    def get_position(self, symbol: str) -> Optional[Dict]:
        for p in self.list_open_positions():
            if p["symbol"] == symbol.upper():
                return p
        return None

    # ------------------- 日终结算 -------------------
    def settle(
        self,
        t_date: str,
        last_prices: Dict[str, float],
    ) -> Dict:
        """
        日终结算：
          1. 撮合 PENDING 订单（T+1）
          2. 更新 last_price
          3. 计算已实现 PnL（按 FIFO）
          4. 计算未实现 PnL
          5. 写 nav
        """
        filled, realized = self._match_pending(last_prices, t_date)
        # 已实现 PnL 累加到 cash（实现盈利入账，实现亏损扣减）
        self.cash += realized
        # 更新 last_price
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        for sym, lp in last_prices.items():
            cur.execute("UPDATE positions SET last_price=? WHERE symbol=?", (lp, sym))
        conn.commit()
        conn.close()

        positions = self.list_open_positions()
        unrealized = 0.0
        for p in positions:
            params = cfg.get_contract_param(p["symbol"])
            diff = (p["last_price"] - p["entry_price"]) * p["qty"] * params["multiplier"]
            if p["direction"] == "SHORT":
                diff = -diff
            unrealized += diff

        market_value = unrealized
        total_equity = self.cash + market_value
        if total_equity > self.peak_equity:
            self.peak_equity = total_equity
        drawdown = (self.peak_equity - total_equity) / self.peak_equity if self.peak_equity > 0 else 0.0

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO nav
               (t_date, cash, market_value, realized_pnl, unrealized_pnl, total_equity, drawdown, layer2_active, portfolio_stopped)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t_date, self.cash, market_value, realized, unrealized, total_equity, drawdown, 0, 0),
        )
        conn.commit()
        conn.close()

        nav = {
            "t_date": t_date,
            "filled_today": filled,
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_equity": round(total_equity, 2),
            "drawdown": round(drawdown, 4),
        }
        logger.info(f"[SETTLE] {t_date} 权益={total_equity:,.0f} 回撤={drawdown*100:.2f}% 撮合={filled} 笔")
        return nav

    def update_nav_flags(self, t_date: str, layer2_active: bool, portfolio_stopped: bool):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "UPDATE nav SET layer2_active=?, portfolio_stopped=? WHERE t_date=?",
            (int(layer2_active), int(portfolio_stopped), t_date),
        )
        conn.commit()
        conn.close()


# ==================== CLI ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=cfg.LOG_FORMAT, datefmt=cfg.LOG_DATE_FORMAT)
    broker = SimBroker()
    print(f"数据库: {broker.db_path}")
    print(f"初始资金: {broker.cash:,.0f}")
    print("接口：submit_order / settle / list_open_positions")
