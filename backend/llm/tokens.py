"""Token 用量统计。

优先级：API 返回的真实 usage（raw.usage）> tiktoken 本地计数 > 字符数/4 估算。
tiktoken 首次使用需下载词表，失败时静默降级，不阻塞业务。

跨调用累计：client.chat() 每次调用后调用 record()；请求侧通过 start_collector()
在 contextvar 挂一个收集器，一次核查（LangGraph 多节点多次 LLM 调用）结束后
读取 totals() 汇总落库。contextvar 天然隔离并发请求（uvicorn 线程池每任务独立上下文）。
"""
from __future__ import annotations

import contextvars
import threading

_enc = None
_fallback = False
_lock = threading.Lock()

_usage_var: contextvars.ContextVar["UsageCollector | None"] = contextvars.ContextVar("llm_usage", default=None)


def _get_enc():
    global _enc, _fallback
    if _fallback:
        return None
    if _enc is not None:
        return _enc
    with _lock:
        if _enc is None and not _fallback:
            try:
                import tiktoken

                _enc = tiktoken.get_encoding("cl100k_base")
            except Exception:  # noqa: BLE001 - 词表下载失败/网络受限时降级
                _fallback = True
    return _enc


def count_text(text: str) -> int:
    """单段文本 token 数：tiktoken 优先，失败按「字符数/4」估算。"""
    if not text:
        return 0
    enc = _get_enc()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:  # noqa: BLE001
            pass
    return max(1, (len(text) + 3) // 4)


def extract_usage(raw: dict | None, prompt_text: str, completion_text: str) -> tuple[int, int]:
    """从 API 原始响应提取 usage；缺失时用 tiktoken 估算。"""
    usage = (raw or {}).get("usage") or {}
    try:
        p = int(usage.get("prompt_tokens"))
        c = int(usage.get("completion_tokens"))
        if p >= 0 and c >= 0:
            return p, c
    except (TypeError, ValueError):
        pass
    return count_text(prompt_text), count_text(completion_text)


class UsageCollector:
    """聚合一次请求内所有 LLM 调用的 token 用量。"""

    def __init__(self):
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def add(self, prompt: int, completion: int) -> None:
        self.calls += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    def totals(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
        }


def start_collector() -> UsageCollector:
    """在当前上下文挂收集器（每次核查/会话请求开始时调用）。"""
    collector = UsageCollector()
    _usage_var.set(collector)
    return collector


def stop_collector() -> None:
    _usage_var.set(None)


def record(prompt: int, completion: int) -> None:
    collector = _usage_var.get()
    if collector is not None:
        collector.add(prompt, completion)


# ===== 注册表方案（跨线程可靠）=====
# SSE 生成器每次 yield 后在不同线程池线程恢复，contextvar 副本会丢；
# 长任务（流式核查）改用按 key 注册的全局收集器，key 随 LLMConfig.usage_key 传递。

_registry: dict[str, UsageCollector] = {}
_reg_lock = threading.Lock()


def register(key: str) -> None:
    with _reg_lock:
        _registry[key] = UsageCollector()


def record_to(key: str, prompt: int, completion: int) -> None:
    with _reg_lock:
        collector = _registry.get(key)
    if collector is not None:
        collector.add(prompt, completion)


def collect(key: str) -> dict | None:
    """取走并移除该 key 的收集器。"""
    with _reg_lock:
        collector = _registry.pop(key, None)
    return collector.totals() if collector else None
