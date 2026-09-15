"""统一 LLM 调用入口。

对外 chat() 按 LLMConfig.protocol 分发到 protocols 的具体实现，返回归一化 ChatResponse。

输入 messages 采用统一中间格式（类 OpenAI Chat）：
  {role: "system"|"user"|"assistant"|"tool", content: str}
  assistant 带工具调用：{role:"assistant", content:str|None, tool_calls:[{id,name,arguments(dict)}]}
  工具结果：{role:"tool", tool_call_id:str, content:str}
protocols 负责转换到各协议原生格式。
tools 统一格式：{type:"function", function:{name,description,parameters}}。
对应 PRD §8。
"""
from __future__ import annotations

from schemas import LLMConfig
from llm.base import ChatResponse, LLMError


def chat(
    messages: list[dict],
    llm_config: LLMConfig,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
) -> ChatResponse:
    """统一 LLM 调用，按 protocol 分发。"""
    from llm import protocols  # 延迟导入，避免与 protocols 的导入环

    if llm_config.protocol == "openai_chat":
        return protocols.openai_chat(messages, llm_config, tools, tool_choice)
    if llm_config.protocol == "openai_responses":
        return protocols.openai_responses(messages, llm_config, tools, tool_choice)
    if llm_config.protocol == "anthropic":
        return protocols.anthropic(messages, llm_config, tools, tool_choice)
    raise LLMError(400, f"unknown protocol: {llm_config.protocol}")
