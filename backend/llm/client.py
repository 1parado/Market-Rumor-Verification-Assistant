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
from llm.tokens import extract_usage, record as record_usage


def _flatten_messages(messages: list[dict]) -> str:
    """把中间格式消息拼成纯文本，供 tiktoken 兜底计数。"""
    parts = []
    for m in messages:
        if m.get("content"):
            parts.append(str(m["content"]))
        for tc in m.get("tool_calls") or []:
            parts.append(str(tc.get("arguments", "")))
    return "\n".join(parts)


def _validate(llm_config: LLMConfig) -> None:
    """调用前校验配置，避免 httpx 因空 Key 拼出非法头（b'Bearer '）而抛裸异常。"""
    if not (llm_config.api_key or "").strip():
        raise LLMError(400, "API Key 为空：请先在设置中填写 API Key")
    if not (llm_config.base_url or "").strip():
        raise LLMError(400, "Base URL 为空：请先在设置中填写 Base URL")
    if not (llm_config.model or "").strip():
        raise LLMError(400, "模型为空：请先在设置中选择模型")


def chat(
    messages: list[dict],
    llm_config: LLMConfig,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
) -> ChatResponse:
    """统一 LLM 调用：分发 + token 用量统计（真实 usage 优先，tiktoken 兜底）。"""
    _validate(llm_config)
    prompt_text = _flatten_messages(messages)
    resp = _dispatch(messages, llm_config, tools, tool_choice)
    completion_text = (resp.content or "") + "".join(
        str(tc.arguments) for tc in resp.tool_calls
    )
    resp.prompt_tokens, resp.completion_tokens = extract_usage(resp.raw, prompt_text, completion_text)
    record_usage(resp.prompt_tokens, resp.completion_tokens)
    key = getattr(llm_config, "usage_key", None)
    if key:
        from llm.tokens import record_to
        record_to(key, resp.prompt_tokens, resp.completion_tokens)
    return resp


def _dispatch(
    messages: list[dict],
    llm_config: LLMConfig,
    tools: list[dict] | None,
    tool_choice: str | dict | None,
) -> ChatResponse:
    from llm import protocols  # 延迟导入，避免与 protocols 的导入环

    if llm_config.protocol == "openai_chat":
        return protocols.openai_chat(messages, llm_config, tools, tool_choice)
    if llm_config.protocol == "openai_responses":
        return protocols.openai_responses(messages, llm_config, tools, tool_choice)
    if llm_config.protocol == "anthropic":
        return protocols.anthropic(messages, llm_config, tools, tool_choice)
    raise LLMError(400, f"unknown protocol: {llm_config.protocol}")


def list_models(llm_config: LLMConfig) -> list[str]:
    """拉取可用模型列表，转发到 protocols。"""
    from llm import protocols  # 延迟导入，避免与 protocols 的导入环

    _validate(llm_config)
    return protocols.list_models(llm_config)
