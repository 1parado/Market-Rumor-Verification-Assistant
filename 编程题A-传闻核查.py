"""
编程题：市场传闻核查助手
============================================================
用户会转发各种股市传闻，做一个核查助手：调用工具查证，
给出「可信 / 存疑 / 无法核实」的判断和依据。

硬性要求：
  1. 判断必须基于工具查到的数据，给出能复核的依据
  2. 数据里查不到的信息要明说「无法核实」，绝不编造
  3. 一条传闻可能涉及多家公司，涉及几家就要查几家
  4. 输出结构化结果（判断 + 依据 + 引用的数据来源）

给好：call_llm（HTTP 已封装）+ 三个查询工具和本地数据 + RUMORS（5 条待核查传闻）
你做：check_rumor(rumor_text)

用你自己的大模型 API（OpenAI 兼容），填好顶部三行就能跑。
跑 `python3 编程题A-传闻核查.py` 验证。

提交：代码 + README（怎么跑/设计思路/已知缺陷）+ AI 协作过程记录。
提交前删掉你的 API key。
============================================================
"""
import json
import os
import time
import requests

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")   # 换成你用的 base_url
API_KEY  = os.environ.get("LLM_API_KEY", "<你自己的 key>")
MODEL    = os.environ.get("LLM_MODEL", "gpt-4o")


def call_llm(messages, tools=None, tool_choice=None):
    """带 429/5xx 退避重试的最小封装。"""
    payload = {"model": MODEL, "messages": messages}
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    for attempt in range(4):
        r = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))   # 退避 5/10/15/20s
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


# ===== 工具（已实现，别改数据）=====
_QUOTES = {
    "恒润科技": {"code": "301566", "price": 42.18, "change_pct": 10.0, "date": "2026-08-07"},
    "蓝湾生物": {"code": "688321", "price": 55.60, "change_pct": 2.4,  "date": "2026-08-07"},
    "睿驰半导体": {"code": "301818", "price": 28.90, "change_pct": -1.2, "date": "2026-08-07"},
    "新湾储能": {"code": "301901", "price": 18.75, "change_pct": -0.8, "date": "2026-08-07"},
    "青云数科": {"code": "300998", "price": 63.40, "change_pct": -6.2, "date": "2026-08-07"},
    "澜星电子": {"code": "301233", "price": 12.06, "change_pct": 1.3,  "date": "2026-08-07"},
}

_ANNOUNCEMENTS = {
    "恒润科技": ["2026-08-05 股票交易异常波动公告：公司生产经营正常，无应披露而未披露的重大事项。"],
    "蓝湾生物": ["2026-08-06 关于 LW-102 三期临床试验结果的公告：试验达到主要终点，公司将尽快推进上市申请。"],
    "睿驰半导体": ["2026-07-28 2026 年半年度业绩预告：预计归母净利润同比增长 15%–25%。"],
    "新湾储能": ["2026-07-15 首次公开发行股票并在创业板上市公告书。"],
    "青云数科": [],
    "澜星电子": [],
}

_NEWS = {
    "恒润科技": ["2026-08-07 恒润科技今日涨停，成交额创近一年新高，龙虎榜显示两机构席位净买入。"],
    "蓝湾生物": ["2026-08-06 蓝湾生物新药三期临床达标，多家券商上调评级。"],
    "睿驰半导体": ["2026-08-01 睿驰半导体半年报预增，车规芯片出货量环比回升。"],
    "新湾储能": ["2026-07-16 新湾储能上市首日破发，收跌 12.3%，为本月第二只破发新股。"],
    "青云数科": ["2026-08-07 计算板块今日回调，青云数科领跌。"],
    "澜星电子": [],
}


def get_quote(company):
    """按公司名查最新行情（价格 / 涨跌幅 / 日期），查无返回 None"""
    return _QUOTES.get(company)

def get_announcements(company):
    """按公司名查近期公告列表，查无返回空列表"""
    return _ANNOUNCEMENTS.get(company, [])

def get_news(company):
    """按公司名查近期资讯列表，查无返回空列表"""
    return _NEWS.get(company, [])


# 待核查传闻
RUMORS = [
    "听说恒润科技昨天涨停了，是不是有大资金进场？",
    "朋友圈说蓝湾生物的新药三期临床失败了，股价要崩。",
    "群里传计算板块今天集体大跌，青云数科和澜星电子都跌超 5 个点。",
    "内部消息：睿驰半导体要被国资重组，下周复牌直接翻倍。",
    "上个月上市的那个做储能的新股听说破发了。",
]


# ===== 你要补的部分 =====
def check_rumor(rumor_text):
    """核查 rumor_text：返回结构化结果——判断（可信/存疑/无法核实）+ 依据 + 数据来源。
    涉及多家公司要逐家查证；数据里没有的信息明说无法核实，不编造。

    三段流水线（与后端 backend/ 的 LangGraph 版同构）：
      1. 规划：LLM 工具调用 → 识别公司（限候选清单，防编造）+ 分解原子断言
      2. 取证：纯工具调用（不调 LLM）→ 对每家公司聚合行情/公告/资讯快照
      3. 裁决：快照注入 prompt → LLM 工具调用逐条判定 + 汇总三分类结论
    """
    # -- 1. 规划：识别公司 + 分解断言（只能从候选清单选，禁止编造公司） --
    candidates = "\n".join(f"- {n}({q['code']})" for n, q in _QUOTES.items())
    plan = _force_tool(
        [
            {"role": "system", "content": (
                "你是市场传闻核查规划员。把传闻分解为可核查的原子断言，并识别涉及的所有公司"
                "（含间接指代，如「上个月上市的储能新股」→ 新湾储能）。\n"
                f"候选公司清单（只能从中选取，禁止编造清单外的公司）：\n{candidates}\n"
                "断言类型：price（价格/涨跌）、event（事件/公告）、spread（资金/情绪类）。"
            )},
            {"role": "user", "content": f"传闻：{rumor_text}"},
        ],
        _PLAN_TOOL, "plan_rumor",
    ) or {"companies": [], "claims": []}

    # -- 2. 取证：涉及几家查几家，纯工具调用聚合数据快照 --
    snapshot = []
    for c in plan.get("companies", []):
        name = c["name"]
        q = get_quote(name)
        if q:
            snapshot.append(f"【{name}】行情：代码={q['code']} 价格={q['price']} 涨跌幅={q['change_pct']}% 日期={q['date']}")
        for a in get_announcements(name):
            snapshot.append(f"【{name}】公告：{a}")
        for n in get_news(name):
            snapshot.append(f"【{name}】资讯：{n}")
    snapshot_text = "\n".join(snapshot) or "（无任何数据）"

    # -- 3. 裁决：快照是唯一事实来源，查不到就标 unverifiable --
    claims_text = "\n".join(
        f"- [{c['id']}]({c['type']}, 公司={c['company']}): {c['text']}"
        for c in plan.get("claims", [])
    ) or "（未能分解出断言）"
    verdict = _force_tool(
        [
            {"role": "system", "content": (
                "你是市场传闻核查裁决员。基于下方数据快照对每条断言逐条判断，再汇总整体判断。\n"
                "规则：\n"
                "1. 所有判断必须基于数据快照；快照中没有的信息一律标 unverifiable，禁止编造。\n"
                "2. 数值引用只能来自快照字段值，不得自行计算或臆测。\n"
                "3. verdict：supports（快照支持）/ refutes（快照相反）/ unverifiable（快照无相关信息）。\n"
                "4. final_verdict：credible（全部 supports）/ questionable（部分支持部分反驳或与快照有出入）"
                "/ unverifiable（相关数据缺失）。\n"
                "5. reasoning 必须引用快照中的具体字段值或原文片段；source 与 source_ref 指明出处。"
            )},
            {"role": "user", "content": f"传闻：{rumor_text}\n\n待核查断言：\n{claims_text}\n\n数据快照：\n{snapshot_text}"},
        ],
        _VERIFY_TOOL, "verify_rumor",
    ) or {"final_verdict": "unverifiable", "basis": "模型未返回结构化核查结果", "verifications": []}

    # -- 4. 结构化输出：判断 + 依据 + 逐条核查（含可复核出处）--
    claim_text = {c["id"]: c["text"] for c in plan.get("claims", [])}
    final = _derive_final(verdict)
    return {
        "传闻": rumor_text,
        "判断": {"credible": "credible", "questionable": "questionable", "unverifiable": "unverifiable"}.get(final, final),
        "依据": verdict.get("basis", ""),
        "逐条核查": [
            {
                "断言": claim_text.get(v.get("claim_id"), v.get("claim_id")),
                "判定": {"supports": "支持", "refutes": "反驳", "unverifiable": "无法核实"}
                .get(v.get("verdict", "unverifiable"), "无法核实"),
                "理由": v.get("reasoning", ""),
                "出处": f"{v.get('source', '')} {v.get('source_ref', '')}".strip(),
            }
            for v in verdict.get("verifications", []) if isinstance(v, dict)
        ],
        "数据来源": sorted({
            v["source_ref"] for v in verdict.get("verifications", [])
            if isinstance(v, dict) and v.get("source_ref")
        }),
    }


def _derive_final(verdict):
    """final_verdict 枚举兜底：模型返回缺失/不规范时，从逐条判定推导。"""
    final = verdict.get("final_verdict")
    if final in {"credible", "questionable", "unverifiable"}:
        return final
    vs = verdict.get("verifications", [])
    if not vs:
        return "unverifiable"
    vals = {v.get("verdict") for v in vs if isinstance(v, dict)}
    if "refutes" in vals:
        return "questionable"          # 有反驳：至少存疑
    if vals == {"supports"}:
        return "credible"              # 全部支持
    return "unverifiable"              # 只有支持+无法核实：整体证据不足


def _force_tool(messages, tool, name):
    """强制 LLM 调用指定工具并解析参数；未返回结构化结果时返回 None（上层兜底）。"""
    msg = call_llm(messages, tools=[tool], tool_choice={"type": "function", "function": {"name": name}})
    for tc in msg.get("tool_calls") or []:
        if tc["function"]["name"] == name:
            try:
                return json.loads(tc["function"]["arguments"])
            except (ValueError, TypeError):
                return None
    return None


_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "plan_rumor",
        "description": "把股市传闻分解为可核查的原子断言，并识别涉及的公司",
        "parameters": {
            "type": "object",
            "properties": {
                "companies": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "name": {"type": "string"}, "code": {"type": "string"}}},
                },
                "claims": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "id": {"type": "string"}, "text": {"type": "string"},
                        "company": {"type": "string"},
                        "type": {"type": "string", "enum": ["price", "event", "spread"]},
                        "expected": {"type": "string"}},
                        "required": ["id", "text", "company", "type"]},
                },
            },
            "required": ["companies", "claims"],
        },
    },
}

_VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "verify_rumor",
        "description": "基于数据快照对每条断言给出判断并汇总",
        "parameters": {
            "type": "object",
            "properties": {
                "verifications": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "claim_id": {"type": "string"},
                        "verdict": {"type": "string", "enum": ["supports", "refutes", "unverifiable"]},
                        "reasoning": {"type": "string"},
                        "source": {"type": "string", "enum": ["quote", "announcement", "news"]},
                        "source_ref": {"type": "string"}},
                        "required": ["claim_id", "verdict", "reasoning"]},
                },
                "final_verdict": {"type": "string", "enum": ["credible", "questionable", "unverifiable"]},
                "basis": {"type": "string"},
            },
            "required": ["verifications", "final_verdict", "basis"],
        },
    },
}


if __name__ == "__main__":
    for i, r in enumerate(RUMORS, 1):
        print(f"--- 传闻 {i}：{r} ---")
        print(json.dumps(check_rumor(r), ensure_ascii=False, indent=2), "\n")
