/* 核真 Veritas · 真实接通前端 — 输入 + Agent 流式过程 + 结果 + 文档 */
"use strict";
const $ = (id) => document.getElementById(id);
const KEY = "veritas.config";

function loadCfg(){ try{ return JSON.parse(localStorage.getItem(KEY) || "{}"); }catch{ return {}; } }
function saveCfg(o){ localStorage.setItem(KEY, JSON.stringify(o)); }
function applyCfg(){
  const c = loadCfg();
  $("protocol").value = c.protocol || "openai_chat";
  $("apiBase").value = c.apiBase || "https://api.openai.com/v1";
  $("model").value = c.model || "gpt-4o";
  $("apiKey").value = c.apiKey || "";
  $("temperature").value = c.temperature ?? 0;
  $("baseUrl").value = c.baseUrl || "http://localhost:8000";
}
function currentCfg(){
  return {
    protocol: $("protocol").value, apiBase: $("apiBase").value.trim(), apiKey: $("apiKey").value.trim(),
    model: $("model").value.trim(), temperature: Number($("temperature").value || 0),
    baseUrl: $("baseUrl").value.trim().replace(/\/$/, ""),
  };
}
function llmPayload(){
  const c = currentCfg();
  return { base_url: c.apiBase, api_key: c.apiKey, protocol: c.protocol, model: c.model, temperature: c.temperature };
}
async function api(path, opts){
  const r = await fetch(currentCfg().baseUrl + path, opts);
  if(!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text().catch(() => r.statusText)}`);
  return r.json();
}

/* 连通测试 */
$("testBtn").onclick = async () => {
  saveCfg(currentCfg());
  const st = $("testStatus"); st.className = "status"; st.textContent = "测试中…";
  $("testBtn").disabled = true;
  try{
    const r = await api("/api/llm/test", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({llm:llmPayload()})});
    if(r.ok){ st.className = "status ok"; st.textContent = `✓ ${r.model} · ${r.reply||""}`; $("checkBtn").disabled = false; toast("连通成功，可开始核查"); }
    else{ st.className = "status fail"; st.textContent = `✕ ${r.error||"失败"} ${r.detail||""}`; }
  }catch(e){ st.className = "status fail"; st.textContent = "✕ " + e.message; }
  finally{ $("testBtn").disabled = false; }
};

/* 载入样例 */
$("loadRumors").onclick = async () => {
  try{
    const r = await api("/api/rumors");
    const box = $("samples"); box.innerHTML = "";
    r.rumors.forEach(x => {
      const b = document.createElement("button"); b.className = "sample"; b.textContent = `#${x.id}`;
      b.title = x.text; b.onclick = () => { $("rumorText").value = x.text; };
      box.appendChild(b);
    });
    toast("已载入 " + r.rumors.length + " 条样例");
  }catch(e){ toast("载入失败：" + e.message); }
};

/* 核查（流式） */
$("checkBtn").onclick = async () => {
  const text = $("rumorText").value.trim();
  if(!text){ toast("请输入传闻"); return; }
  saveCfg(currentCfg());
  $("procCard").hidden = false; $("resultCard").hidden = true; $("docCard").hidden = true;
  $("procLog").innerHTML = ""; $("procStatus").textContent = "核查中…";
  $("checkBtn").disabled = true; $("checkStatus").className = "status"; $("checkStatus").textContent = "";
  try{
    await streamCheck(text);
    $("procStatus").textContent = "✓ 完成";
    $("checkStatus").className = "status ok"; $("checkStatus").textContent = "✓ 核查完成";
  }catch(e){
    $("procStatus").textContent = "✕ 失败";
    $("checkStatus").className = "status fail"; $("checkStatus").textContent = "✕ " + e.message;
  }finally{ $("checkBtn").disabled = false; }
};

async function streamCheck(text){
  const r = await fetch(currentCfg().baseUrl + "/api/rumor/check/stream", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ rumor_text: text, llm: llmPayload() }),
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
      const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const { event, data } = parseSSE(block);
      handleEvent(event, data);
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
  return { event, data };
}

function handleEvent(event, data){
  if(event === "start"){ appendProc("start", `开始核查：${data.rumor_text || ""}`); }
  else if(event === "node"){ renderNode(data.node, data.output); }
  else if(event === "done"){ renderResult(data.result); renderDoc(data.result); }
  else if(event === "error"){ appendProc("error", `✕ ${data.detail || data.status || "错误"}`); }
}

function renderNode(node, out){
  if(!out) return;
  if(node === "planner"){
    const cs = (out.companies || []).map(c => c.name).join("、") || "无";
    appendProc("plan", `▶ 规划：识别公司 [${cs}]，分解 ${(out.claims||[]).length} 条断言`);
    (out.claims || []).forEach(c => appendProc("plan-sub", `    · [${c.type}] ${c.text}（${c.company}）${c.expected ? "· 期望：" + c.expected : ""}`));
  } else if(node === "evidence"){
    const evs = out.evidence || [];
    appendProc("ev", `▶ 取证：${evs.length} 条证据`);
    evs.forEach(e => {
      const r = e.source === "quote" ? `价格=${e.payload.price} 涨跌幅=${e.payload.change_pct}%` : (e.payload.text || "").slice(0, 50);
      appendProc("ev-sub", `    · ${e.source}(${e.company}) → ${r}`);
    });
  } else if(node === "judge"){
    appendProc("judge", "▶ 裁决：基于数据快照逐条核查");
  }
}

function appendProc(kind, text){
  const el = document.createElement("div"); el.className = "prow k-" + kind; el.textContent = text;
  $("procLog").appendChild(el);
  $("procLog").scrollTop = $("procLog").scrollHeight;
}

function renderResult(r){
  if(!r) return;
  $("resultCard").hidden = false;
  $("dataDate").textContent = r.data_date ? `数据日期 ${r.data_date}` : "";
  const vMap = { credible: ["v-credible","可信"], questionable: ["v-questionable","存疑"], unverifiable: ["v-unverifiable","无法核实"] };
  const [vc, vl] = vMap[r.final_verdict] || vMap.unverifiable;
  const claimMap = {}; (r.claims || []).forEach(c => claimMap[c.id] = c);
  const tm = { supports: ["supports","支持"], refutes: ["refutes","反驳"], unverifiable: ["unverifiable","无法核实"] };
  const verts = (r.verifications || []).map(v => {
    const c = claimMap[v.claim_id];
    const [tc, tl] = tm[v.verdict] || tm.unverifiable;
    return `<div class="vert"><div class="vhead"><span class="tag ${tc}">${tl}</span><span class="vt">${c ? esc(c.text) : "断言" + v.claim_id}</span></div><div class="vreason">${esc(v.reasoning)}</div><div class="vref">${v.source ? ("来源：" + v.source + (v.source_ref ? " · " + esc(v.source_ref) : "")) : ""}</div></div>`;
  }).join("");
  $("resultBody").innerHTML =
    `<div class="final"><span class="vbadge ${vc}">● ${vl}</span></div>` +
    `<p class="basis">${esc(r.basis || "")}</p>` +
    (verts ? `<div class="verts">${verts}</div>` : "") +
    ((r.sources && r.sources.length) ? `<div class="src"><b>引用来源：</b>${r.sources.map(esc).join(" · ")}</div>` : "");
  $("resultBody").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderDoc(r){
  if(!r) return;
  $("docCard").hidden = false;
  const vMap = { credible:"可信", questionable:"存疑", unverifiable:"无法核实" };
  const vm = { supports:"支持", refutes:"反驳", unverifiable:"无法核实" };
  const claimMap = {}; (r.claims || []).forEach(c => claimMap[c.id] = c);
  const L = [];
  L.push("# 传闻核查报告", "");
  L.push("## 传闻", r.rumor_text, "");
  L.push("## 判断", `**${vMap[r.final_verdict] || "无法核实"}**`, "");
  L.push("## 依据", r.basis || "", "");
  L.push("## 逐条核查");
  (r.verifications || []).forEach(v => {
    const c = claimMap[v.claim_id];
    L.push(`- [${c ? c.text : "断言" + v.claim_id}] — ${vm[v.verdict] || "无法核实"}：${v.reasoning}` + (v.source ? `（来源：${v.source}${v.source_ref ? " · " + v.source_ref : ""}）` : ""));
  });
  L.push("");
  if(r.sources && r.sources.length){ L.push("## 数据来源"); r.sources.forEach(s => L.push("- " + s)); L.push(""); }
  if(r.data_date){ L.push(`> 数据日期：${r.data_date}`); }
  $("docMd").textContent = L.join("\n");
}

$("copyMd").onclick = () => {
  const t = $("docMd").textContent; if(!t) return;
  navigator.clipboard.writeText(t).then(() => toast("已复制 Markdown")).catch(() => toast("复制失败"));
};

function esc(s){ return String(s || "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

let tt;
function toast(msg){ $("toastMsg").textContent = msg; $("toast").classList.add("show"); clearTimeout(tt); tt = setTimeout(() => $("toast").classList.remove("show"), 2600); }

$("themeBtn").onclick = () => { const d = document.documentElement.getAttribute("data-theme") === "dark"; document.documentElement.setAttribute("data-theme", d ? "light" : "dark"); };

applyCfg();
$("checkBtn").disabled = true;
