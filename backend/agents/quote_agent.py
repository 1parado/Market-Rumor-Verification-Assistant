"""行情核查 Agent：把 get_quote 结果转成 Evidence。"""
from __future__ import annotations

from schemas import Evidence
from tools.quote import get_quote


def collect_quote_evidence(company: str) -> Evidence | None:
    """取行情快照，转成 quote 来源 Evidence；查无返回 None。"""
    q = get_quote(company)
    if not q:
        return None
    return Evidence(company=company, source="quote", payload=q.model_dump())
