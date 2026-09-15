"""LLM 调用层：三协议适配 + 统一入口。"""
from llm.base import ChatResponse, LLMError, ToolCall
from llm.client import chat

__all__ = ["chat", "ChatResponse", "ToolCall", "LLMError"]
