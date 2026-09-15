"""取证节点：对每个识别出的公司聚合行情/公告/资讯，形成数据快照。

本地工具（行情/公告/资讯，笔试题虚构数据）+ 真实网络搜索（Perplexity 式来源带回）。
搜索只做工具调用，不调 LLM、不做算术；失败优雅降级到本地数据。
参考 TradingAgents v0.4.0 数据锚定：快照作为后续 judge 的唯一事实来源。
"""
from __future__ import annotations

from agents.announce_agent import collect_announcement_evidence
from agents.news_agent import collect_news_evidence
from agents.quote_agent import collect_quote_evidence
from schemas import CheckState, Claim, Evidence
from tools.web_search import web_search

_MAX_RESULTS_PER_QUERY = 4


def gather_evidence(state: CheckState) -> dict:
    """evidence 节点：输出 {evidence}。"""
    companies = state.get("companies", [])
    claims: list[Claim] = state.get("claims", [])
    evidence: list[Evidence] = []
    for c in companies:
        name = c.name if hasattr(c, "name") else c["name"]
        qe = collect_quote_evidence(name)
        if qe:
            evidence.append(qe)
        evidence.extend(collect_announcement_evidence(name))
        evidence.extend(collect_news_evidence(name))

    # 真实网络搜索：按 planner 设计的查询词逐条取证，带回网页（标题/URL/摘要）
    for claim in claims:
        for query in (claim.queries or [])[:2]:
            for hit in web_search(query, max_results=_MAX_RESULTS_PER_QUERY):
                evidence.append(Evidence(
                    company=claim.company,
                    source="web",
                    payload={
                        "title": hit["title"],
                        "url": hit["url"],
                        "snippet": hit["snippet"],
                        "query": query,
                    },
                ))
    return {"evidence": evidence}
