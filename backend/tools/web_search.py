"""真实网络搜索工具（Perplexity 式来源带回）。

优先级：
  1. Tavily API（环境变量 TAVILY_API_KEY，质量最高，免费档可用）
  2. ddgs 多后端轮询（duckduckgo → bing → google → auto），无 Key 可用
  3. 全部失败返回空列表 —— 取证节点优雅降级到本地数据，不阻塞核查

返回结构：[{title, url, snippet}]，与搜索引擎无关的统一格式。
"""
from __future__ import annotations

import os
from typing import Any

import httpx

_TIMEOUT = 12.0
_BACKENDS = ("duckduckgo", "bing", "google", "auto")


def _tavily_search(query: str, max_results: int) -> list[dict[str, Any]]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": max_results,
                  "search_depth": "basic"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for item in r.json().get("results", []):
            url = item.get("url", "")
            if url:
                out.append({"title": item.get("title") or url, "url": url,
                            "snippet": (item.get("content") or "")[:220]})
        return out
    except Exception:  # noqa: BLE001 - 网络/配额失败静默降级
        return []


def _ddgs_search(query: str, max_results: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    for backend in _BACKENDS:
        try:
            raw = DDGS().text(query, max_results=max_results, backend=backend)
        except Exception:  # noqa: BLE001 - 单后端失败换下一个
            continue
        out = []
        for x in raw or []:
            url = x.get("href") or x.get("url") or ""
            if url.startswith("http"):
                out.append({"title": x.get("title") or url, "url": url,
                            "snippet": (x.get("body") or "")[:220]})
        if out:
            return out
    return []


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """执行一次网络搜索，返回 [{title, url, snippet}]；失败返回 []。"""
    if not query.strip():
        return []
    results = _tavily_search(query, max_results)
    if results:
        return results
    try:
        return _ddgs_search(query, max_results)
    except Exception:  # noqa: BLE001 - ddgs 未安装等
        return []
