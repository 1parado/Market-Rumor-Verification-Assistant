"""核真 Veritas 数据模型。

所有跨模块流转的结构化数据在此定义（Pydantic），作为单一真相源。
对应 PRD §7 数据结构。
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

# ===== LLM 配置 =====
Protocol = Literal["openai_chat", "openai_responses", "anthropic"]


class LLMConfig(BaseModel):
    """用户自带模型配置，由前端随请求传入，后端不落盘 Key。"""

    base_url: str
    api_key: str
    protocol: Protocol
    model: str
    temperature: float = 0.0


# ===== 工具返回 =====
class QuoteSnapshot(BaseModel):
    company: str
    code: str | None = None
    price: float | None = None
    change_pct: float | None = None
    date: str | None = None


class AnnouncementItem(BaseModel):
    company: str
    text: str


class NewsItem(BaseModel):
    company: str
    text: str


# ===== 核查流水线领域模型 =====
class CompanyRef(BaseModel):
    name: str
    code: str | None = None


ClaimType = Literal["price", "event", "spread"]


class Claim(BaseModel):
    """传闻分解出的可核查原子断言。"""

    id: str
    text: str
    company: str
    type: ClaimType
    expected: str | None = None


EvidenceSource = Literal["quote", "announcement", "news"]


class Evidence(BaseModel):
    company: str
    source: EvidenceSource
    payload: dict[str, Any] = Field(default_factory=dict)


Verdict = Literal["supports", "refutes", "unverifiable"]


class Verification(BaseModel):
    claim_id: str
    verdict: Verdict
    reasoning: str
    source: EvidenceSource | None = None
    source_ref: str | None = None


FinalVerdict = Literal["credible", "questionable", "unverifiable"]


class RumorCheckResult(BaseModel):
    """核查最终结构化输出，对应 PRD §5.4 响应。"""

    rumor_text: str
    companies: list[CompanyRef] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    verifications: list[Verification] = Field(default_factory=list)
    final_verdict: FinalVerdict = "unverifiable"
    basis: str = ""
    sources: list[str] = Field(default_factory=list)
    data_date: str | None = None


class LLMTestResult(BaseModel):
    ok: bool
    model: str | None = None
    reply: str | None = None
    error: str | None = None
    detail: str | None = None


# ===== LangGraph 流水线状态 =====
class CheckState(TypedDict, total=False):
    """LangGraph 节点间传递的状态；各节点返回 dict 子集更新对应字段。"""

    rumor_text: str
    llm_config: LLMConfig
    companies: list[CompanyRef]
    claims: list[Claim]
    evidence: list[Evidence]
    verifications: list[Verification]
    result: RumorCheckResult
