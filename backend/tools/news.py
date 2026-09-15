"""资讯查询工具。"""
from __future__ import annotations

from data.local_data import raw_news
from schemas import NewsItem


def get_news(company: str) -> list[NewsItem]:
    """按公司名查近期资讯列表，查无返回空列表。"""
    return [NewsItem(company=company, text=t) for t in raw_news(company)]
