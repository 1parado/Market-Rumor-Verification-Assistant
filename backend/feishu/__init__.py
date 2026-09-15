"""飞书接入模块：扫码 OAuth + WebSocket 长连接接收 + @机器人核查回复。

get_bridge() 返回进程级单例 FeishuBridge，由 app.py startup 调 load_and_start_all()。
"""
from __future__ import annotations

from .bridge import FeishuBridge, get_bridge

__all__ = ["FeishuBridge", "get_bridge"]
