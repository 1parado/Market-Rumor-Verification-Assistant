"""公告核查 Agent：把 get_announcements 结果转成 Evidence 列表。"""
from __future__ import annotations

from schemas import Evidence
from tools.announcements import get_announcements


def collect_announcement_evidence(company: str) -> list[Evidence]:
    """取近期公告，每条转成 announcement 来源 Evidence。"""
    items = get_announcements(company)
    return [Evidence(company=company, source="announcement", payload={"text": a.text}) for a in items]
