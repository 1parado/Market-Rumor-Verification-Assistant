"""公告查询工具。"""
from __future__ import annotations

from data.local_data import raw_announcements
from schemas import AnnouncementItem


def get_announcements(company: str) -> list[AnnouncementItem]:
    """按公司名查近期公告列表，查无返回空列表。"""
    return [AnnouncementItem(company=company, text=t) for t in raw_announcements(company)]
