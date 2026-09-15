"""取证节点：对每个识别出的公司聚合行情/公告/资讯，形成数据快照。

纯工具调用，不调 LLM，不做算术（AGENT.md 引用 FinRobot/AlphaAnalyst 原则）。
参考 TradingAgents v0.4.0 数据锚定：快照作为后续 judge 的唯一事实来源。
"""
from __future__ import annotations

from agents.announce_agent import collect_announcement_evidence
from agents.news_agent import collect_news_evidence
from agents.quote_agent import collect_quote_evidence
from schemas import CheckState, Evidence


def gather_evidence(state: CheckState) -> dict:
    """evidence 节点：输出 {evidence}。"""
    companies = state.get("companies", [])
    evidence: list[Evidence] = []
    for c in companies:
        name = c.name if hasattr(c, "name") else c["name"]
        qe = collect_quote_evidence(name)
        if qe:
            evidence.append(qe)
        evidence.extend(collect_announcement_evidence(name))
        evidence.extend(collect_news_evidence(name))
    return {"evidence": evidence}
