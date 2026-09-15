"""资讯核查 Agent：把 get_news 结果转成 Evidence 列表。"""
from __future__ import annotations

from schemas import Evidence
from tools.news import get_news


def collect_news_evidence(company: str) -> list[Evidence]:
    """取近期资讯，每条转成 news 来源 Evidence。"""
    items = get_news(company)
    return [Evidence(company=company, source="news", payload={"text": n.text}) for n in items]
