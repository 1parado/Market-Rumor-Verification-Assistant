"""飞书接入相关请求模型（响应直接返 dict，与现有 app.py 路由风格一致）。"""
from __future__ import annotations

from pydantic import BaseModel


class ScanBeginRequest(BaseModel):
    channel: str = "feishu"  # feishu | lark


class ScanPollRequest(BaseModel):
    channel: str = "feishu"
    device_code: str


class FeishuInstanceSave(BaseModel):
    """扫码完成或手动填写后保存飞书实例。"""

    name: str
    channel: str = "feishu"
    app_id: str
    app_secret: str
    owner_open_id: str = ""
    model_config_id: int | None = None
    enabled: bool = True
