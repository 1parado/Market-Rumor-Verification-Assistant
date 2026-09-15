"""LLM 层基础数据类与异常。

无外部依赖，独立于 protocols/client，避免循环导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """LLM 调用失败统一异常；status=0 表示网络层错误。"""

    def __init__(self, status: int, detail: str):
        super().__init__(f"LLM call failed [{status}]: {detail}")
        self.status = status
        self.detail = detail


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict | None = None
