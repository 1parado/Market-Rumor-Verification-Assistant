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
from llm import LLMError, chat, list_models
from llm import tokens
from pipeline import build_graph, run_check
from schemas import LLMConfig, LLMTestResult, RumorCheckResult
import storage
import feishu
from feishu import oauth as feishu_oauth
from feishu.models import ScanBeginRequest, ScanPollRequest, FeishuInstanceSave

app = FastAPI(title="核真 Veritas 后端", version="0.2.0")

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


class ConfigSaveRequest(BaseModel):
    """保存模型配置（按名称 upsert）。"""

    name: str
    llm: LLMConfig


class RunChatRequest(BaseModel):
    """运行内会话：用户消息 + 模型配置。"""

    message: str
    llm: LLMConfig


@app.on_event("startup")
def on_startup() -> None:
    storage.init_db()
    stale = storage.fail_stale_runs()
    if stale:
        print(f"[startup] 已将 {stale} 条中断遗留的 running 记录标记为失败")
    # 加载已保存的飞书实例并建立 WebSocket 长连接
    feishu.get_bridge().load_and_start_all()


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


@app.post("/api/llm/models")
def list_models_api(req: LLMTestRequest) -> dict:
    """拉取可用模型列表（GET {base_url}/models，三协议适配）。"""
    try:
        models = list_models(req.llm)
    except LLMError as exc:
        return {"ok": False, "error": exc.detail, "detail": f"status={exc.status}"}
    return {"ok": True, "models": models}


# ===== 模型配置持久化 =====

@app.get("/api/configs")
def get_configs() -> dict:
    return {"configs": storage.list_configs()}


@app.post("/api/configs")
def save_config(req: ConfigSaveRequest) -> dict:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="配置名称不能为空")
    cfg = storage.upsert_config(name, req.llm.protocol, req.llm.base_url, req.llm.api_key, req.llm.model)
    return {"ok": True, "config": cfg}


@app.delete("/api/configs/{config_id}")
def remove_config(config_id: int) -> dict:
    if not storage.delete_config(config_id):
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"ok": True}


# ===== 核查运行持久化 =====

@app.get("/api/runs")
def get_runs(limit: int = 50) -> dict:
    return {"runs": storage.list_runs(limit)}


@app.get("/api/runs/{run_id}")
def get_run_detail(run_id: int) -> dict:
    run = storage.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return {"run": run}


@app.delete("/api/runs/{run_id}")
def remove_run(run_id: int) -> dict:
    if not storage.delete_run(run_id):
        raise HTTPException(status_code=404, detail="运行不存在")
    return {"ok": True}


@app.post("/api/runs/{run_id}/chat")
def run_chat(run_id: int, req: RunChatRequest) -> dict:
    """运行内会话：基于该次核查结果回答追问，双向消息落库。"""
    run = storage.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    storage.add_message(run_id, "user", req.message)

    result = run.get("result") or {}
    verdict_map = {"credible": "可信", "questionable": "存疑", "unverifiable": "无法核实"}
    claims = {c["id"]: c["text"] for c in result.get("claims", [])}
    checks = "\n".join(
        f"- [{verdict_map.get(v.get('verdict'), '无法核实')}] {claims.get(v.get('claim_id'), v.get('claim_id', ''))}：{v.get('reasoning', '')}"
        for v in result.get("verifications", [])
    )
    system = (
        "你是「核真」市场传闻核查助手。以下是本次核查的结论与依据，"
        "请据此用简体中文回答用户的追问；不确定时明确说明，不要编造数据。\n\n"
        f"传闻：{run['rumor_text']}\n"
        f"结论：{verdict_map.get(result.get('final_verdict', ''), '未知')}\n"
        f"依据：{result.get('basis', '') or '（无）'}\n"
    )
    if checks:
        system += f"逐条核查：\n{checks}\n"
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in run.get("messages", [])[-10:]
    ]
    messages = [{"role": "system", "content": system}, *history]
    collector = tokens.start_collector()
    try:
        resp = chat(messages, req.llm)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败：status={exc.status}, {exc.detail}")
    finally:
        usage = collector.totals()
        tokens.stop_collector()
    reply = storage.add_message(run_id, "assistant", resp.content)
    storage.add_tokens(run_id, usage["prompt_tokens"], usage["completion_tokens"])
    return {"ok": True, "reply": reply["content"], "usage": usage}


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

    事件：start（含 run_id）/ node / done / error。全程逐条落库（SQLite），
    前端可用 GET /api/runs/{id} 回放过程与结果。
    """
    def gen():
        run_id = storage.create_run(req.rumor_text)
        usage_key = str(run_id)
        tokens.register(usage_key)
        llm_cfg = req.llm.model_copy(update={"usage_key": usage_key})
        # 直线流水线节点顺序：节点 A 完成即乐观推送节点 B「进行中」，
        # 让前端在 LLM 调用期间也能看到实时进度（否则十几秒无任何输出）。
        next_step = {"planner": "evidence", "evidence": "judge"}

        def push_step(node: str):
            payload = {"node": node}
            yield _sse("step", payload)
            storage.add_event(run_id, "step", payload)

        try:
            graph = build_graph()
            final: RumorCheckResult | None = None
            yield _sse("start", {"rumor_text": req.rumor_text, "run_id": run_id})
            storage.add_event(run_id, "start", {"rumor_text": req.rumor_text})
            yield from push_step("planner")
            for chunk in graph.stream(
                {"rumor_text": req.rumor_text, "llm_config": llm_cfg},
                stream_mode="updates",
            ):
                for node, update in chunk.items():
                    payload = {"node": node, "output": _serialize(update)}
                    yield _sse("node", payload)
                    storage.add_event(run_id, "node", payload)
                    if node in next_step:
                        yield from push_step(next_step[node])
                    res = update.get("result")
                    if isinstance(res, RumorCheckResult):
                        final = res
            usage = tokens.collect(usage_key) or {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            done_payload = {"result": _serialize(final), "run_id": run_id, "usage": usage} if final \
                else {"run_id": run_id, "usage": usage}
            yield _sse("done", done_payload)
            if final:
                serialized = _serialize(final)
                storage.finish_run(
                    run_id, "done", serialized, report_md=_result_md(serialized),
                    prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"],
                )
            else:
                storage.finish_run(run_id, "error", error="流水线未产出结果")
        except LLMError as exc:
            usage = tokens.collect(usage_key)
            detail = f"LLM 调用失败（status={exc.status}）：{exc.detail}"
            payload = {"status": exc.status, "detail": exc.detail}
            yield _sse("error", payload)
            storage.add_event(run_id, "error", payload)
            storage.finish_run(run_id, "error", error=detail,
                               prompt_tokens=(usage or {}).get("prompt_tokens", 0),
                               completion_tokens=(usage or {}).get("completion_tokens", 0))
        except Exception as exc:  # noqa: BLE001
            usage = tokens.collect(usage_key)
            payload = {"detail": str(exc)}
            yield _sse("error", payload)
            storage.add_event(run_id, "error", payload)
            storage.finish_run(run_id, "error", error=f"核查异常：{exc}",
                               prompt_tokens=(usage or {}).get("prompt_tokens", 0),
                               completion_tokens=(usage or {}).get("completion_tokens", 0))
        finally:
            tokens.stop_collector()

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


def _result_md(r: dict) -> str:
    """把核查结果渲染为 Markdown 报告（与前端 buildDoc 同构，落库 report_md）。"""
    v_map = {"credible": "可信", "questionable": "存疑", "unverifiable": "无法核实"}
    t_map = {"supports": "支持", "refutes": "反驳", "unverifiable": "无法核实"}
    claims = {c["id"]: c["text"] for c in r.get("claims", [])}
    lines = ["# 传闻核查报告", "", "## 传闻", r.get("rumor_text", ""), "",
             "## 判断", f"**{v_map.get(r.get('final_verdict', ''), '无法核实')}**", "",
             "## 依据", r.get("basis", "") or "", "## 逐条核查"]
    for v in r.get("verifications", []):
        ref = v.get("source") or ""
        ref += f" · {v['source_ref']}" if v.get("source_ref") else ""
        lines.append(
            f"- [{claims.get(v.get('claim_id'), v.get('claim_id', ''))}] — "
            f"{t_map.get(v.get('verdict', ''), '无法核实')}：{v.get('reasoning', '')}"
            + (f"（来源：{ref}）" if ref else "")
        )
    lines.append("")
    if r.get("web_sources"):
        lines.append("## 参考网页")
        for i, w in enumerate(r["web_sources"], 1):
            lines.append(f"{i}. [{w.get('title', w.get('url', ''))}]({w.get('url', '')})")
            if w.get("snippet"):
                lines.append(f"   > {w['snippet']}")
        lines.append("")
    if r.get("sources"):
        lines.append("## 数据来源")
        lines += [f"- {s}" for s in r["sources"]]
        lines.append("")
    if r.get("data_date"):
        lines.append(f"> 数据日期：{r['data_date']}")
    return "\n".join(lines)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ===== 飞书接入 =====


def _feishu_public(inst: dict) -> dict:
    """抹掉 app_secret 后给前端（与 bridge.state 一致，路由层再保险一次）。"""
    inst.pop("app_secret", None)
    return inst


@app.post("/api/feishu/scan/begin")
def feishu_scan_begin(req: ScanBeginRequest) -> dict:
    """发起扫码：返回二维码 data URL + device_code。"""
    r = feishu_oauth.scan_begin(req.channel)
    return {
        "device_code": r.device_code,
        "verification_uri": r.verification_uri,
        "interval_sec": r.interval_sec,
        "expire_in_sec": r.expire_in_sec,
        "platform": r.platform,
        "error": r.error,
    }


@app.post("/api/feishu/scan/poll")
def feishu_scan_poll(req: ScanPollRequest) -> dict:
    """轮询扫码状态：completed 时返回 app_id/app_secret。"""
    r = feishu_oauth.scan_poll(req.channel, req.device_code)
    return {
        "status": r.status,
        "app_id": r.app_id,
        "app_secret": r.app_secret,
        "owner_open_id": r.owner_open_id,
        "platform": r.platform,
        "error": r.error,
        "slow_down": r.slow_down,
        "interval_sec": r.interval_sec,
    }


@app.get("/api/feishu/instances")
def feishu_list_instances() -> dict:
    """已保存实例列表（含运行状态）。"""
    return feishu.get_bridge().state()


@app.get("/api/feishu/state")
def feishu_state() -> dict:
    """IM 接入面板加载用：实例列表 + 运行状态。"""
    return feishu.get_bridge().state()


@app.post("/api/feishu/instances")
def feishu_save_instance(req: FeishuInstanceSave) -> dict:
    """保存扫码所得实例并立即建立长连接。"""
    if not req.app_id or not req.app_secret:
        raise HTTPException(status_code=400, detail="app_id / app_secret 不能为空")
    inst = feishu.get_bridge().save_instance(
        req.name, req.channel, req.app_id, req.app_secret,
        req.owner_open_id, req.model_config_id, req.enabled,
    )
    return {"ok": True, "instance": _feishu_public(inst)}


@app.delete("/api/feishu/instances/{instance_id}")
def feishu_delete_instance(instance_id: int) -> dict:
    if not feishu.get_bridge().delete_instance(instance_id):
        raise HTTPException(status_code=404, detail="实例不存在")
    return {"ok": True}


@app.post("/api/feishu/instances/{instance_id}/stop")
def feishu_stop_instance(instance_id: int) -> dict:
    """停用实例（标志位过滤，连接不立即断开）。"""
    feishu.get_bridge().stop_instance(instance_id)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
