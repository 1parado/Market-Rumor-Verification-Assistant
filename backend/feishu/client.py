"""飞书开放平台数据面：tenant_access_token + 发消息/回复（手写 httpx）。

移植自 E:/FreeAgent/frontend-agent/internal/im/feishu.go。
- tenant_access_token 缓存：expire - 5 分钟提前过期，避免边界失败。
- 发消息：POST /open-apis/im/v1/messages?receive_id_type=chat_id
- 回复：POST /open-apis/im/v1/messages/{message_id}/reply，失败由调用方降级为普通发送。

lark-oapi 仅用于 bridge 的 WebSocket 长连接接收，数据面手写以保持与参考项目一致、独立可测。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

import httpx

from .oauth import open_base

_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_MSG_PATH = "/open-apis/im/v1/messages"


@dataclass
class _TokenCache:
    token: str = ""
    expire_at: float = 0.0


class FeishuSender:
    """飞书发送端：tenant_access_token 缓存 + 发文本/回复。"""

    def __init__(self, channel: str, app_id: str, app_secret: str):
        self.channel = channel
        self.app_id = app_id
        self.app_secret = app_secret
        self.base = open_base(channel)
        self._token = _TokenCache()
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=httpx.Timeout(15.0))

    def _tenant_token(self) -> str:
        """获取 tenant_access_token，缓存至 expire-300s。"""
        with self._lock:
            if self._token.token and time.time() < self._token.expire_at:
                return self._token.token
        r = self._client.post(
            self.base + _TOKEN_PATH,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        d = r.json()
        token = d.get("tenant_access_token", "")
        if not token:
            raise RuntimeError(f"获取 tenant_access_token 失败：{d.get('msg') or d}")
        ttl = int(d.get("expire") or 7200)
        with self._lock:
            self._token.token = token
            self._token.expire_at = time.time() + ttl - 300  # 提前 5 分钟过期
        return token

    def verify(self) -> None:
        """验证凭据：取一次 token，失败抛异常。"""
        self._tenant_token()

    def send_text(self, chat_id: str, text: str) -> dict:
        """按 chat_id 发文本消息。"""
        token = self._tenant_token()
        r = self._client.post(
            self.base + _MSG_PATH,
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"发送消息失败：{d.get('msg') or d}")
        return d

    def reply(self, message_id: str, text: str) -> dict:
        """回复指定消息。返回响应 dict（含 code），调用方据此判断是否降级为 send_text。"""
        token = self._tenant_token()
        r = self._client.post(
            f"{self.base}{_MSG_PATH}/{message_id}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={"msg_type": "text", "content": json.dumps({"text": text})},
        )
        return r.json()

    def reply_or_send(self, message_id: str, chat_id: str, text: str) -> dict:
        """先回复原消息，失败（code!=0）则降级为按 chat_id 普通发送。"""
        d = self.reply(message_id, text)
        if d.get("code") == 0:
            return d
        return self.send_text(chat_id, text)

    def close(self) -> None:
        self._client.close()
