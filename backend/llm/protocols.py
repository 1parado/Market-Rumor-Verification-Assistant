"""三协议 HTTP 适配。

把统一中间格式（见 client.py）转换到各协议原生请求体，并把响应归一化为 ChatResponse。
对应 PRD §8 协议适配表。

已知简化（MVP）：
- OpenAI Responses 的 input 项按 message/function_call/function_call_output 构造，
  部分第三方兼容端点可能未实现 /responses（仅支持 /chat/completions）。
- Anthropic base_url 兼容「…/v1」与裸域名两种填法。
- 流式响应未支持（MVP 同步调用）。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from llm.base import ChatResponse, LLMError, ToolCall

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _join_url(base_url: str, suffix: str) -> str:
    return base_url.rstrip("/") + suffix


def _trim(s: str, n: int = 500) -> str:
    return s if len(s) <= n else s[:n] + "..."


def _tool_name(tool_choice: str | dict) -> str | None:
    """从统一 tool_choice {type:function,function:{name}} 提取工具名。"""
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") or {}
        return fn.get("name") or tool_choice.get("name")
    return None


def _to_responses_tool_choice(tool_choice: str | dict) -> str | dict:
    """Responses 用 {type:function,name}（无 function 包裹）。"""
    name = _tool_name(tool_choice)
    if name:
        return {"type": "function", "name": name}
    return tool_choice


def _to_anthropic_tool_choice(tool_choice: str | dict) -> str | dict:
    """Anthropic 用 {type:tool,name}；required→any。"""
    name = _tool_name(tool_choice)
    if name:
        return {"type": "tool", "name": name, "disable_parallel_tool_use": True}
    if tool_choice == "required":
        return {"type": "any"}
    return tool_choice


def _post(url: str, api_key: str, body: dict, anthropic: bool = False) -> dict:
    headers = {"Content-Type": "application/json"}
    if anthropic:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise LLMError(0, f"network error: {exc}") from exc
    if r.status_code >= 400:
        raise LLMError(r.status_code, _trim(r.text))
    return r.json()


def _parse_args(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": raw}


# ===== OpenAI Chat Completions =====
def openai_chat(messages, llm_config, tools, tool_choice) -> ChatResponse:
    url = _join_url(llm_config.base_url, "/chat/completions")
    body: dict[str, Any] = {
        "model": llm_config.model,
        "messages": [_to_openai_chat_message(m) for m in messages],
        "temperature": llm_config.temperature,
    }
    if tools:
        body["tools"] = [_to_openai_chat_tool(t) for t in tools]
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
    resp = _post(url, llm_config.api_key, body)
    msg = resp["choices"][0]["message"]
    return _parse_openai_chat_message(msg, resp)


def _to_openai_chat_message(m: dict) -> dict:
    role = m["role"]
    if role == "tool":
        return {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m.get("content")}
    out: dict[str, Any] = {"role": role, "content": m.get("content")}
    if m.get("tool_calls"):
        out["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                },
            }
            for tc in m["tool_calls"]
        ]
    return out


def _to_openai_chat_tool(t: dict) -> dict:
    return t if "function" in t else {"type": "function", "function": t}


def _parse_openai_chat_message(msg: dict, raw: dict) -> ChatResponse:
    tool_calls = [
        ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=_parse_args(tc["function"].get("arguments")))
        for tc in (msg.get("tool_calls") or [])
    ]
    return ChatResponse(content=msg.get("content"), tool_calls=tool_calls, raw=raw)


# ===== OpenAI Responses =====
def openai_responses(messages, llm_config, tools, tool_choice) -> ChatResponse:
    url = _join_url(llm_config.base_url, "/responses")
    body: dict[str, Any] = {
        "model": llm_config.model,
        "input": _to_responses_input(messages),
        "temperature": llm_config.temperature,
    }
    if tools:
        body["tools"] = [_to_responses_tool(t) for t in tools]
        if tool_choice is not None:
            body["tool_choice"] = _to_responses_tool_choice(tool_choice)
    resp = _post(url, llm_config.api_key, body)
    return _parse_responses(resp)


def _to_responses_input(messages: list[dict]) -> list[dict]:
    items: list[dict] = []
    for m in messages:
        role = m["role"]
        if role == "system":
            items.append({"type": "message", "role": "system", "content": [{"type": "input_text", "text": m.get("content") or ""}]})
        elif role == "user":
            items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": m.get("content") or ""}]})
        elif role == "assistant":
            if m.get("content"):
                items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": m["content"]}]})
            for tc in m.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": tc["id"], "name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": m.get("content") or ""})
    return items


def _to_responses_tool(t: dict) -> dict:
    fn = t.get("function", t)
    return {
        "type": "function",
        "name": fn["name"],
        "description": fn.get("description", ""),
        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _parse_responses(resp: dict) -> ChatResponse:
    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") in ("output_text", "text"):
                    content_parts.append(block.get("text", ""))
        elif item.get("type") == "function_call":
            tool_calls.append(ToolCall(id=item.get("call_id", ""), name=item["name"], arguments=_parse_args(item.get("arguments"))))
    return ChatResponse(content="\n".join(content_parts) or None, tool_calls=tool_calls, raw=resp)


# ===== Anthropic Messages =====
def anthropic(messages, llm_config, tools, tool_choice) -> ChatResponse:
    url = _anthropic_url(llm_config.base_url)
    system, conv = _split_anthropic_messages(messages)
    body: dict[str, Any] = {
        "model": llm_config.model,
        "messages": conv,
        "max_tokens": 4096,
        "temperature": llm_config.temperature,
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = [_to_anthropic_tool(t) for t in tools]
        if tool_choice is not None:
            body["tool_choice"] = _to_anthropic_tool_choice(tool_choice)
    resp = _post(url, llm_config.api_key, body, anthropic=True)
    return _parse_anthropic(resp)


def _anthropic_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base + "/messages" if base.endswith("/v1") else base + "/v1/messages"


def _split_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = [m["content"] for m in messages if m["role"] == "system" and m.get("content")]
    conv: list[dict] = []
    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]})
            conv.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            conv.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m.get("content") or ""}]})
        else:
            conv.append({"role": role, "content": m.get("content") or ""})
    return "\n\n".join(system_parts), conv


def _to_anthropic_tool(t: dict) -> dict:
    fn = t.get("function", t)
    return {
        "name": fn["name"],
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _parse_anthropic(resp: dict) -> ChatResponse:
    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in resp.get("content", []):
        if block.get("type") == "text":
            content_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(ToolCall(id=block.get("id", ""), name=block["name"], arguments=block.get("input", {})))
    return ChatResponse(content="\n".join(content_parts) or None, tool_calls=tool_calls, raw=resp)


# ===== 拉取模型列表 =====
def _get(url: str, api_key: str, anthropic: bool = False) -> dict:
    headers = {"Content-Type": "application/json"}
    if anthropic:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = httpx.get(url, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise LLMError(0, f"network error: {exc}") from exc
    if r.status_code >= 400:
        raise LLMError(r.status_code, _trim(r.text))
    return r.json()


def list_models(llm_config) -> list[str]:
    """拉取可用模型列表，三协议适配。"""
    if llm_config.protocol == "anthropic":
        base = llm_config.base_url.rstrip("/")
        url = base + "/models" if base.endswith("/v1") else base + "/v1/models"
        resp = _get(url, llm_config.api_key, anthropic=True)
    else:
        resp = _get(_join_url(llm_config.base_url, "/models"), llm_config.api_key)
    return [m["id"] for m in resp.get("data", []) if m.get("id")]
