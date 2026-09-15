/* 核真 Veritas · 配置存取 + 后端 API 封装 */
const KEY = "veritas.config";

export function defaultCfg(){
  return {
    protocol: "openai_chat",
    apiBase: "https://api.openai.com/v1",
    apiKey: "",
    model: "gpt-4o",
    // 后端地址不暴露给用户：默认空 = 同源（dev 走 Vite 代理，生产与后端同域部署）
    baseUrl: "",
  };
}

export function loadCfg(){
  try{
    const c = JSON.parse(localStorage.getItem(KEY) || "{}");
    delete c.baseUrl; // 静默固定走同源/代理，忽略历史存储值
    return { ...defaultCfg(), ...c };
  }
  catch{ return defaultCfg(); }
}
export function saveCfg(cfg){
  localStorage.setItem(KEY, JSON.stringify(cfg));
}

export function llmPayload(cfg){
  return { base_url: cfg.apiBase, api_key: cfg.apiKey, protocol: cfg.protocol, model: cfg.model };
}

export async function api(cfg, path, opts = {}){
  const r = await fetch((cfg.baseUrl || "").replace(/\/$/, "") + path, opts);
  if(!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json();
}

/* ===== 持久化 API（后端 SQLite）===== */
const JSON_OPTS = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** 已保存的模型配置列表 */
export const listConfigs = (cfg) => api(cfg, "/api/configs").then(r => r.configs || []);
/** 按名称保存/覆盖模型配置 */
export const saveConfig = (cfg, name) => api(cfg, "/api/configs", JSON_OPTS({ name, llm: llmPayload(cfg) }));
export const deleteConfig = (cfg, id) => api(cfg, `/api/configs/${id}`, { method: "DELETE" });

/** 核查运行历史 */
export const listRuns = (cfg) => api(cfg, "/api/runs").then(r => r.runs || []);
export const getRun = (cfg, id) => api(cfg, `/api/runs/${id}`).then(r => r.run);
export const deleteRun = (cfg, id) => api(cfg, `/api/runs/${id}`, { method: "DELETE" });
/** 运行内会话：向 Agent 追问 */
export const sendChat = (cfg, runId, message) => api(cfg, `/api/runs/${runId}/chat`, JSON_OPTS({ message, llm: llmPayload(cfg) }));

/** SSE 流式核查：onEvent(event, data) */
export async function streamCheck(cfg, text, onEvent){
  const r = await fetch((cfg.baseUrl || "").replace(/\/$/, "") + "/api/rumor/check/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rumor_text: text, llm: llmPayload(cfg) }),
  });
  if(!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text().catch(() => r.statusText)}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while(true){
    const { done, value } = await reader.read();
    if(done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while((idx = buf.indexOf("\n\n")) >= 0){
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      onEvent(...parseSSE(block));
    }
  }
}

function parseSSE(block){
  let event = "message", data = "";
  block.split(/\n/).forEach(line => {
    if(line.startsWith("event:")) event = line.slice(6).trim();
    else if(line.startsWith("data:")) data += line.slice(5).trim();
  });
  try{ data = data ? JSON.parse(data) : {}; }catch{ /* keep raw */ }
  return [event, data];
}
