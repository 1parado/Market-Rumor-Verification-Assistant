"""行情查询工具。"""
from __future__ import annotations

from data.local_data import raw_quote
from schemas import QuoteSnapshot


def get_quote(company: str) -> QuoteSnapshot | None:
    """按公司名查最新行情快照，查无返回 None。"""
    q = raw_quote(company)
    if not q:
        return None
    return QuoteSnapshot(
        company=company,
        code=q.get("code"),  # type: ignore[arg-type]
        price=q.get("price"),  # type: ignore[arg-type]
        change_pct=q.get("change_pct"),  # type: ignore[arg-type]
        date=q.get("date"),  # type: ignore[arg-type]
    )
