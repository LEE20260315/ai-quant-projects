#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
推送通道 (Path 2 / 10X Aggressive Growth)
=====================================

支持:
  - 钉钉群机器人 (自定义 webhook)
  - Bark (iOS 推送)

消息体格式 (来自规划):
    [信号类型] + [品种/方向] + [建议手数] + [止损位]

附加按钮 (移动端可点击的链接):
    [确认下单] -> http://PC_IP:8000/execute?id=xxx&token=yyy
    [跳过信号] -> http://PC_IP:8000/skip?id=xxx&token=yyy
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlencode

try:
    import requests  # type: ignore
    _REQUESTS_OK = True
except ImportError:
    requests = None  # type: ignore
    _REQUESTS_OK = False


logger = logging.getLogger(__name__)


@dataclass
class SignalCard:
    """推送卡片数据"""
    signal_type: str          # e.g. "分位反转 / 趋势顺势"
    symbol: str               # 品种
    direction: str            # "多" / "空"
    suggested_lots: int       # 建议手数
    stop_loss: float          # 止损价
    take_profit: float = 0.0  # 止盈价
    confidence: float = 0.0
    fusion: str = ""
    pc_base_url: str = "http://127.0.0.1:8000"
    trade_id: str = ""
    confirm_token: str = ""

    def to_text(self) -> str:
        # 文字版本 (Bark / 短消息)
        text = (
            f"[{self.signal_type}] {self.symbol} {self.direction} "
            f"{self.suggested_lots}手\n"
            f"止损: {self.stop_loss:.0f}"
        )
        if self.take_profit > 0:
            text += f"  止盈: {self.take_profit:.0f}"
        if self.fusion:
            text += f"\n融合: {self.fusion}"
        text += f"\nID: {self.trade_id}"
        return text

    def to_action_links(self) -> dict:
        """生成 [确认下单] / [跳过信号] 链接"""
        if not (self.trade_id and self.confirm_token):
            return {}
        base = self.pc_base_url.rstrip("/")
        q = urlencode({"id": self.trade_id, "token": self.confirm_token})
        return {
            "execute_url": f"{base}/execute?{q}",
            "skip_url":    f"{base}/skip?{q}",
        }

    def to_dingtalk_markdown(self) -> dict:
        """钉钉 markdown 卡片"""
        actions = self.to_action_links()
        body = (
            f"### {self.signal_type} | {self.symbol} {self.direction}\n"
            f"- 建议手数: **{self.suggested_lots}**\n"
            f"- 止损: {self.stop_loss:.0f}\n"
        )
        if self.take_profit > 0:
            body += f"- 止盈: {self.take_profit:.0f}\n"
        if self.confidence > 0:
            body += f"- 置信度: {self.confidence:.0%}\n"
        if self.fusion:
            body += f"- 融合: {self.fusion}\n"
        body += f"- TradeID: `{self.trade_id}`\n"
        if actions:
            body += (
                f"\n[确认下单]({actions['execute_url']})  "
                f"[跳过信号]({actions['skip_url']})\n"
            )
        return {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{self.symbol} {self.direction} | {self.suggested_lots}手",
                "text": body,
            },
        }


# ============================================================
# 钉钉推送
# ============================================================
class DingTalkNotifier:
    """
    钉钉群自定义机器人.
    通过环境变量 DINGTALK_WEBHOOK / DINGTALK_SECRET 注入.
    """

    def __init__(self, webhook: Optional[str] = None, secret: Optional[str] = None,
                 timeout: float = 5.0, at_mobiles: Optional[List[str]] = None):
        self.webhook = webhook or os.environ.get("DINGTALK_WEBHOOK", "")
        self.secret = secret or os.environ.get("DINGTALK_SECRET", "")
        self.timeout = timeout
        self.at_mobiles = at_mobiles or []
        if not self.webhook:
            logger.warning("DingTalkNotifier: 未配置 webhook, 调用 send 将只记录日志.")

    def send(self, card: SignalCard) -> bool:
        payload = card.to_dingtalk_markdown()
        if self.at_mobiles:
            payload["markdown"]["text"] += "\n" + " ".join(f"@{m}" for m in self.at_mobiles)
            payload["at"] = {"atMobiles": self.at_mobiles, "isAtAll": False}
        if not self.webhook:
            logger.info("[DINGTALK-DRYRUN] %s", json.dumps(payload, ensure_ascii=False))
            return True
        try:
            r = requests.post(self.webhook, json=payload, timeout=self.timeout)
            ok = (r.status_code == 200 and r.json().get("errcode", 0) == 0)
            if not ok:
                logger.warning("DingTalk 推送失败: %s %s", r.status_code, r.text[:200])
            return ok
        except Exception as e:
            logger.warning("DingTalk 推送异常: %s", e)
            return False


# ============================================================
# Bark 推送 (iOS)
# ============================================================
class BarkNotifier:
    """
    Bark iOS 推送.
    通过环境变量 BARK_KEY / BARK_SERVER 注入 (BARK_SERVER 默认 https://api.day.app).
    """

    def __init__(self, key: Optional[str] = None, server: Optional[str] = None,
                 timeout: float = 5.0):
        self.key = key or os.environ.get("BARK_KEY", "")
        self.server = (server or os.environ.get("BARK_SERVER") or "https://api.day.app").rstrip("/")
        self.timeout = timeout
        if not self.key:
            logger.warning("BarkNotifier: 未配置 BARK_KEY, 调用 send 将只记录日志.")

    def send(self, card: SignalCard, group: str = "quant") -> bool:
        actions = card.to_action_links()
        url = f"{self.server}/{self.key}/{group}/"
        body = {
            "title": f"{card.symbol} {card.direction} | {card.suggested_lots}手",
            "body": card.to_text(),
            "group": group,
            "level": "timeSensitive",
            "icon": "https://cdn-icons-png.flaticon.com/512/3132/3132693.png",
        }
        if actions:
            # Bark 支持 click 链接, 我们用 category 字段把 execute/skip 都列出
            body["url"] = actions.get("execute_url", "")
        if not self.key:
            logger.info("[BARK-DRYRUN] %s", json.dumps(body, ensure_ascii=False))
            return True
        try:
            r = requests.post(url, json=body, timeout=self.timeout)
            ok = r.status_code == 200
            if not ok:
                logger.warning("Bark 推送失败: %s %s", r.status_code, r.text[:200])
            return ok
        except Exception as e:
            logger.warning("Bark 推送异常: %s", e)
            return False


# ============================================================
# 飞书 (webhook 群机器人模式, 不需要 lark-cli, 5 分钟配好)
# ============================================================
class LarkWebhookNotifier:
    """
    飞书群机器人 webhook 推送 (类似钉钉, 但消息格式用 interactive 卡片)
    配置: 飞书群 -> 设置 -> 群机器人 -> 添加机器人 -> 自定义机器人
    拿到 webhook URL (https://open.feishu.cn/open-apis/bot/v2/hook/<token>) 设到 LARK_WEBHOOK env
    """
    def __init__(self, webhook: Optional[str] = None, timeout: float = 5.0):
        self.webhook = (webhook or os.environ.get("LARK_WEBHOOK", "")).strip()
        self.timeout = timeout

    def send(self, card: SignalCard) -> bool:
        if not self.webhook:
            logger.info("[LARK-DRYRUN] webhook 未配置, skip. card: %s", card.to_text()[:200])
            return False
        body = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain", "content": f"📈 {card.signal_type} | {card.symbol} {card.direction}"},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "fields": [
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**品种**: {card.symbol}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**方向**: {card.direction}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**手数**: {card.suggested_lots}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**止损**: {card.stop_loss:.0f}"}},
                            {"is_short": False, "text": {"tag": "lark_md", "content": f"**止盈**: {card.take_profit:.0f} | **融合**: {card.fusion}"}},
                        ],
                    },
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain", "content": f"trade_id={card.trade_id} | pc_url={card.pc_base_url or '-'}"},
                        ],
                    },
                ],
            },
        }
        try:
            r = requests.post(self.webhook, json=body, timeout=self.timeout)
            ok = r.status_code == 200 and r.json().get("StatusCode", r.json().get("code", 0)) in (0, 200)
            if not ok:
                logger.warning("Lark 推送失败: %s %s", r.status_code, r.text[:200])
            return ok
        except Exception as e:
            logger.warning("Lark 推送异常: %s", e)
            return False


# ============================================================
# 飞书 (lark-cli 模式, 0 配置: 走 user 身份发到自己的 P2P, 已实测通过)
# ============================================================
class LarkCliNotifier:
    """
    飞书推送 (lark-cli user 身份模式)
    0 配置: 直接调 npx lark-cli 发到当前 user 自己的 P2P
    前提: lark-cli 已 auth login (我们已实测配过)
    """
    def __init__(self, user_open_id: Optional[str] = None, timeout: float = 10.0):
        # 0 配: 直接从 .env 拿, 缺时用动态探测, 再不行从 chat-list 拿
        self.user_open_id = (user_open_id or os.environ.get("LARK_USER_OPEN_ID", "")).strip()
        self.timeout = timeout
        if not self.user_open_id:
            self.user_open_id = self._fetch_self_open_id() or ""

    def _fetch_self_open_id(self) -> Optional[str]:
        # 优先: 从 +chat-list 拿 user 自己创建的 chat 的 owner_id (即 user 自己的 open_id)
        try:
            r = subprocess.run(
                "npx lark-cli im +chat-list --as user",
                capture_output=True, text=True, timeout=15, shell=True,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                chats = data.get("data", {}).get("chats", []) or []
                for c in chats:
                    owner = c.get("owner_id", "")
                    if owner and owner.startswith("ou_"):
                        return owner
        except Exception as e:
            logger.debug("LarkCli 拉 chat-list 失败: %s", e)
        return None

    def send(self, card: SignalCard) -> bool:
        if not self.user_open_id:
            logger.info("[LARKCLI-DRYRUN] user_open_id 拿不到, skip. card: %s", card.to_text()[:200])
            return False
        text = card.to_text()[:1500]
        try:
            r = subprocess.run(
                ["npx", "lark-cli", "im", "+messages-send",
                 "--user-id", self.user_open_id,
                 "--text", text],
                capture_output=True, text=True, timeout=self.timeout, shell=True,
            )
            ok = r.returncode == 0 and '"ok": true' in r.stdout
            if not ok:
                logger.warning("LarkCli 推送失败: %s | %s", r.stdout[:200], r.stderr[:200])
            return ok
        except Exception as e:
            logger.warning("LarkCli 推送异常: %s", e)
            return False


# ============================================================
# 联合推送
# ============================================================
class MultiNotifier:
    def __init__(self, dingtalk: Optional[DingTalkNotifier] = None,
                 bark: Optional[BarkNotifier] = None,
                 lark: Optional[LarkWebhookNotifier] = None,
                 lark_cli: Optional[LarkCliNotifier] = None):
        self.dingtalk = dingtalk or DingTalkNotifier()
        self.bark = bark or BarkNotifier()
        self.lark = lark or LarkWebhookNotifier()
        self.lark_cli = lark_cli or LarkCliNotifier()

    def push(self, card: SignalCard) -> dict:
        return {
            "dingtalk": self.dingtalk.send(card),
            "bark":     self.bark.send(card),
            "lark":     self.lark.send(card),
            "lark_cli": self.lark_cli.send(card),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    card = SignalCard(
        signal_type="分位反转",
        symbol="TA2506",
        direction="多",
        suggested_lots=2,
        stop_loss=4820,
        take_profit=5180,
        confidence=0.78,
        fusion="same_dir:tp+0.30atr",
        pc_base_url="http://192.168.1.10:8000",
        trade_id="T-20260608-001",
        confirm_token="abc123",
    )
    print("TEXT版:")
    print(card.to_text())
    print("\nDINGTALK 版:")
    print(json.dumps(card.to_dingtalk_markdown(), ensure_ascii=False, indent=2))
    print("\n动作链接:")
    print(json.dumps(card.to_action_links(), ensure_ascii=False, indent=2))
    # 干跑推送
    MultiNotifier().push(card)
