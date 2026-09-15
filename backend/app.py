"""核真 Veritas 后端入口（FastAPI）。

对应 PRD §5 接口契约。启动：uv run uvicorn app:app --reload --port 8000
"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from data.local_data import RUMORS
from llm import LLMError, chat
from pipeline import build_graph, run_check
from schemas import LLMConfig, LLMTestResult, RumorCheckResult

app = FastAPI(title="核真 Veritas 后端", version="0.1.0")

# MVP 允许任意来源（前端部署在 GitHub Pages、自带 Key）；上线需收紧。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class LLMTestRequest(BaseModel):
    llm: LLMConfig


class RumorCheckRequest(BaseModel):
    rumor_text: str
    llm: LLMConfig


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/rumors")
def list_rumors() -> dict:
    return {"rumors": [{"id": i, "text": r} for i, r in enumerate(RUMORS, 1)]}


@app.post("/api/llm/test")
def test_llm(req: LLMTestRequest) -> LLMTestResult:
    """连通测试：发起一次最小对话调用。失败也返回 200 + ok=false（语义化）。"""
    messages = [
        {"role": "system", "content": "你是连通测试助手。"},
        {"role": "user", "content": "请回复 ok。"},
    ]
    try:
        resp = chat(messages, req.llm)
    except LLMError as exc:
        return LLMTestResult(ok=False, error=exc.detail, detail=f"status={exc.status}")
    return LLMTestResult(ok=True, model=req.llm.model, reply=resp.content)


@app.post("/api/rumor/check")
def check_rumor(req: RumorCheckRequest) -> RumorCheckResult:
    """核查传闻：执行 LangGraph 流水线，返回结构化结果。"""
    try:
        return run_check(req.rumor_text, req.llm)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败：status={exc.status}, {exc.detail}")
    except Exception as exc:  # noqa: BLE001 - 流水线内部异常统一兜底
        raise HTTPException(status_code=500, detail=f"核查失败：{exc}")


@app.post("/api/rumor/check/stream")
def check_rumor_stream(req: RumorCheckRequest) -> StreamingResponse:
    """流式核查：SSE 推送 planner/evidence/judge 各节点过程，最后推送结果。

    事件：start / node / done / error。前端用 fetch + ReadableStream 消费（POST）。
    对应 AGENT.md §5.4 front/ 真实前端的流式需求。
    """
    def gen():
        try:
            graph = build_graph()
            final: RumorCheckResult | None = None
            yield _sse("start", {"rumor_text": req.rumor_text})
            for chunk in graph.stream(
                {"rumor_text": req.rumor_text, "llm_config": req.llm},
                stream_mode="updates",
            ):
                for node, update in chunk.items():
                    yield _sse("node", {"node": node, "output": _serialize(update)})
                    res = update.get("result")
                    if isinstance(res, RumorCheckResult):
                        final = res
            yield _sse("done", {"result": _serialize(final)} if final else {})
        except LLMError as exc:
            yield _sse("error", {"status": exc.status, "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _serialize(obj):
    """递归序列化 Pydantic 对象为 JSON 兼容结构。"""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    return obj


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
