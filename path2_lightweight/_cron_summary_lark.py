# -*- coding: utf-8 -*-
"""
cron 跑完 daily 后调用: 读日志 -> 调 lark-cli 发飞书 P2P
用法: python _cron_summary_lark.py [daily_log_path]
"""
import sys, os, json, subprocess
from pathlib import Path
from datetime import datetime

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))  # 父目录, 让 common/ 可导入

TRACKING = _HERE / "tracking"


def fetch_user_open_id() -> str:
    """从 +chat-list 拿当前 user 的 open_id"""
    try:
        r = subprocess.run(
            "npx lark-cli im +chat-list --as user",
            capture_output=True, text=True, timeout=20, shell=True,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            chats = data.get("data", {}).get("chats", []) or []
            for c in chats:
                owner = c.get("owner_id", "")
                if owner and owner.startswith("ou_"):
                    return owner
    except Exception as e:
        print(f"[ERR] 拿 open_id 失败: {e}")
    return ""


def send_lark(user_open_id: str, text: str) -> bool:
    try:
        r = subprocess.run(
            ["npx", "lark-cli", "im", "+messages-send",
             "--user-id", user_open_id,
             "--text", text[:1500]],  # 飞书单条限制
            capture_output=True, text=True, timeout=15, shell=True,
        )
        ok = r.returncode == 0 and '"ok": true' in r.stdout
        if not ok:
            print(f"[ERR] 飞书 send 失败: rc={r.returncode} | {r.stdout[:200]} | {r.stderr[:200]}")
        return ok
    except Exception as e:
        print(f"[ERR] 飞书 send 异常: {e}")
        return False


def build_summary() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"📊 盯盘日报 | {today} | paper mode"]

    # 1) 读 daily_<today>.json
    daily_file = TRACKING / f"daily_{today}.json"
    if daily_file.exists():
        try:
            d = json.loads(daily_file.read_text(encoding="utf-8"))
            acc = d.get("account", {})
            cap = acc.get("capital", 0)
            dd = acc.get("drawdown_pct", 0)
            n_pos = len(d.get("positions", {}))
            n_trades = d.get("trade_stats", {}).get("total_trades", 0)
            wr = d.get("trade_stats", {}).get("win_rate", 0)
            lines.append(
                f"💰 资金 {cap:,.0f} | 回撤 {dd:.1f}% | "
                f"持仓 {n_pos} | 累计 {n_trades} 笔 (胜率 {wr:.0%})"
            )
        except Exception as e:
            lines.append(f"[daily 解析失败: {e}]")
    else:
        lines.append(f"⚠️ daily_{today}.json 不存在, run_daily 可能没跑成功")

    # 2) 读 tracker_state.json
    state_file = TRACKING / "tracker_state.json"
    if state_file.exists():
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
            if s.get("locked"):
                lines.append("⛔ 系统已锁定 (硬熔断)")
            pending = s.get("pending_orders", [])
            if pending:
                lines.append(f"📋 待成交限价单: {len(pending)} 笔")
                for o in pending:
                    d_str = "多" if o.get("direction") == 1 else "空"
                    try:
                        sp = float(o.get("signal_price", 0))
                        lp = float(o.get("limit_price", 0))
                    except (TypeError, ValueError):
                        sp = lp = 0
                    lines.append(
                        f"   - {o.get('symbol')} {d_str} | "
                        f"信号价 {sp:.0f} | "
                        f"限价 {lp:.0f} | "
                        f"挂 {o.get('next_open')}"
                    )
            else:
                lines.append("📋 无待成交限价单")
        except Exception as e:
            lines.append(f"[state 解析失败: {e}]")

    lines.append("\n[详情见邮件 + logs/dryrun_<日期>.log]")
    return "\n".join(lines)


def main():
    print("[cron_summary_lark] 启动")
    open_id = fetch_user_open_id()
    if not open_id:
        print("[FATAL] 拿不到 user open_id, 跳过飞书推送 (邮件兜底)")
        return 1
    print(f"[cron_summary_lark] open_id: {open_id[:20]}...")
    text = build_summary()
    print(f"[cron_summary_lark] 消息预览:\n{text}\n")
    ok = send_lark(open_id, text)
    print(f"[cron_summary_lark] 飞书发送: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
