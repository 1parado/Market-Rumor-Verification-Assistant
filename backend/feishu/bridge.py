"""飞书桥接器：进程级单例，管理实例的长连接接收 + 消息分发 + 核查回复。

移植自 E:/FreeAgent/frontend-agent/internal/im/runtime.go 的 Start/Stop/Deliver/dispatch/handleMessage。
- 每个启用实例起一个 daemon 线程跑 lark.ws.Client.start()（阻塞，SDK 自动重连）。
- 事件回调把消息入 queue.Queue，单 worker 线程串行消费跑核查并回复
  （避免并发跑核查，对齐参考项目的 inbox + 单 dispatcher 模式）。
- 停用/删除：设 active=False，事件回调跳过；ws.Client 无 stop()，连接不立即断开
  （SDK 限制，下次进程启动不再加载该实例）。
"""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from .client import FeishuSender
from .handler import handle_im_message
import storage
from schemas import LLMConfig


@dataclass
class IncomingMessage:
    instance_id: int
    channel: str
    user_id: str = ""
    chat_id: str = ""
    chat_type: str = "p2p"
    message_id: str = ""
    text: str = ""
    mentioned: bool = False


@dataclass
class _Runtime:
    sender: FeishuSender
    thread: threading.Thread | None
    active: bool = True


class FeishuBridge:
    """进程级飞书桥接器单例。"""

    def __init__(self) -> None:
        self._instances: dict[int, _Runtime] = {}
        self._inbox: queue.Queue[IncomingMessage | None] = queue.Queue(maxsize=64)
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    # ---- 生命周期 ----

    def load_and_start_all(self) -> None:
        """startup 调用：从 DB 加载所有 enabled 实例并建立长连接。"""
        for inst in storage.list_feishu_instances():
            if inst["enabled"] and inst["app_id"] and inst["app_secret"]:
                self._start_one(inst)
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._dispatch, daemon=True, name="feishu-worker")
            self._worker.start()

    def _start_one(self, inst: dict) -> None:
        """为单个实例建 sender + ws.Client + daemon 线程。"""
        inst_id = inst["id"]
        channel = inst["channel"]
        app_id = inst["app_id"]
        app_secret = inst["app_secret"]
        sender = FeishuSender(channel, app_id, app_secret)

        def on_message(data: P2ImMessageReceiveV1) -> None:
            rt = self._instances.get(inst_id)
            if rt is None or not rt.active:
                return  # 实例已停用/删除，忽略
            msg = _parse_event(data, inst_id, channel)
            if msg is None:
                return
            # ACL：群聊必须 @机器人；私聊直接响应
            if msg.chat_type == "group" and not msg.mentioned:
                return
            try:
                self._inbox.put_nowait(msg)
            except queue.Full:
                storage.update_feishu_status(inst_id, "error", "消息队列已满，丢弃入站消息")

        try:
            handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(on_message)
                .build()
            )
            domain = lark.LARK_DOMAIN if channel == "lark" else lark.FEISHU_DOMAIN
            ws_client = lark.ws.Client(
                app_id, app_secret,
                event_handler=handler, domain=domain,
                log_level=lark.LogLevel.WARNING,
            )
        except Exception as exc:  # noqa: BLE001
            storage.update_feishu_status(inst_id, "error", f"长连接初始化失败：{exc}")
            return

        def _run() -> None:
            try:
                ws_client.start()  # 阻塞，SDK 自动重连
            except Exception as exc:  # noqa: BLE001
                storage.update_feishu_status(inst_id, "error", f"长连接异常退出：{exc}")

        t = threading.Thread(target=_run, daemon=True, name=f"feishu-ws-{inst_id}")
        with self._lock:
            self._instances[inst_id] = _Runtime(sender=sender, thread=t, active=True)
        t.start()
        # 异步验证凭据（取一次 tenant_access_token）
        threading.Thread(target=self._verify_one, args=(inst_id, sender), daemon=True).start()

    def _verify_one(self, inst_id: int, sender: FeishuSender) -> None:
        try:
            sender.verify()
            storage.update_feishu_status(inst_id, "connected", "")
        except Exception as exc:  # noqa: BLE001
            storage.update_feishu_status(inst_id, "error", f"凭据验证失败：{exc}")

    # ---- 消息分发（单 worker 串行）----

    def _dispatch(self) -> None:
        while True:
            msg = self._inbox.get()
            if msg is None:
                return  # 哨兵：进程退出
            try:
                self._handle_message(msg)
            except Exception:  # noqa: BLE001 - 单条失败不影响后续
                pass

    def _handle_message(self, msg: IncomingMessage) -> None:
        rt = self._instances.get(msg.instance_id)
        if rt is None or not rt.active:
            return
        text = msg.text.strip()
        if not text:
            return
        inst = storage.get_feishu_instance(msg.instance_id)
        if not inst or not inst["model_config_id"]:
            self._safe_reply(rt, msg, "⚠️ 未关联模型配置，无法核查。请先在「设置」中保存模型配置，再在 IM 接入面板关联。")
            return
        mc = storage.get_model_config(inst["model_config_id"])
        if mc is None:
            self._safe_reply(rt, msg, "⚠️ 关联的模型配置已失效，请重新在 IM 接入面板关联。")
            return
        llm_config = LLMConfig(
            base_url=mc["base_url"], api_key=mc["api_key"],
            protocol=mc["protocol"], model=mc["model"],
        )
        reply_text = handle_im_message(text, llm_config)
        self._safe_reply(rt, msg, reply_text)

    def _safe_reply(self, rt: _Runtime, msg: IncomingMessage, text: str) -> None:
        try:
            rt.sender.reply_or_send(msg.message_id, msg.chat_id, text)
        except Exception as exc:  # noqa: BLE001
            storage.update_feishu_status(msg.instance_id, "error", f"回复失败：{exc}")

    # ---- 对外 API（供 app.py 路由调用）----

    def save_instance(
        self, name: str, channel: str, app_id: str, app_secret: str,
        owner_open_id: str = "", model_config_id: int | None = None, enabled: bool = True,
    ) -> dict:
        """保存实例并立即启动长连接。"""
        inst = storage.upsert_feishu_instance(
            name, channel, app_id, app_secret, owner_open_id, model_config_id, enabled,
        )
        if enabled and app_id and app_secret:
            self._start_one(inst)
            self._ensure_worker()
        return inst

    def stop_instance(self, instance_id: int) -> None:
        """停用：设 active=False（ws.Client 无 stop，连接不立即断开，下次启动不再加载）。"""
        with self._lock:
            rt = self._instances.get(instance_id)
            if rt:
                rt.active = False
        storage.set_feishu_enabled(instance_id, False)

    def delete_instance(self, instance_id: int) -> bool:
        with self._lock:
            rt = self._instances.pop(instance_id, None)
            if rt:
                rt.active = False
                try:
                    rt.sender.close()
                except Exception:  # noqa: BLE001
                    pass
        return storage.delete_feishu_instance(instance_id)

    def state(self) -> dict:
        insts = storage.list_feishu_instances()
        for inst in insts:
            rt = self._instances.get(inst["id"])
            inst["receiving"] = bool(rt and rt.active)
        return {"instances": [_public(inst) for inst in insts]}


def _public(inst: dict) -> dict:
    """抹掉 app_secret 后给前端（app_id 不属高敏，保留作展示）。"""
    inst.pop("app_secret", None)
    return inst


def _parse_event(data: P2ImMessageReceiveV1, inst_id: int, channel: str) -> IncomingMessage | None:
    """把 lark-oapi 事件归一化为 IncomingMessage。防回环 + 提取文本。"""
    try:
        event = data.event
        sender = event.sender
        if getattr(sender, "sender_type", "") in ("bot", "app"):
            return None  # 防回环
        msg = event.message
        chat_type = getattr(msg, "chat_type", "") or "p2p"
        mentions = getattr(msg, "mentions", None) or []
        mentioned = len(mentions) > 0
        text = _extract_text(getattr(msg, "message_type", ""), getattr(msg, "content", None))
        if not text:
            return None
        text = _strip_mentions(text, mentions)
        sender_id = getattr(sender, "sender_id", None)
        user_id = getattr(sender_id, "open_id", "") if sender_id else ""
        return IncomingMessage(
            instance_id=inst_id, channel=channel, user_id=user_id or "",
            chat_id=getattr(msg, "chat_id", "") or "",
            chat_type=chat_type, message_id=getattr(msg, "message_id", "") or "",
            text=text, mentioned=mentioned,
        )
    except Exception:  # noqa: BLE001 - 解析失败丢弃，不影响其它消息
        return None


def _extract_text(message_type: str, content: str | None) -> str:
    """从消息 content（JSON 字符串）提取纯文本。"""
    if not content:
        return ""
    try:
        c = json.loads(content)
    except json.JSONDecodeError:
        return ""
    if message_type == "text":
        return c.get("text", "")
    if message_type == "post":
        parts: list[str] = []
        for _, line in c.items():
            if isinstance(line, list):
                for node in line:
                    if isinstance(node, dict) and node.get("tag") in ("text", "a"):
                        parts.append(node.get("text", ""))
                parts.append("\n")
        return "".join(parts)
    return ""


def _strip_mentions(text: str, mentions) -> str:
    """删除 @机器人 的占位 key（如 @_user_1）。"""
    try:
        for m in mentions or []:
            key = getattr(m, "key", None) or ""
            if key:
                text = text.replace(key, "")
    except Exception:  # noqa: BLE001
        pass
    return text.strip()


_bridge: FeishuBridge | None = None


def get_bridge() -> FeishuBridge:
    global _bridge
    if _bridge is None:
        _bridge = FeishuBridge()
    return _bridge
