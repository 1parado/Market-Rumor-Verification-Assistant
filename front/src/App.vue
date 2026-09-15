<script setup>
import { ref, computed, onMounted } from "vue";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api, loadCfg, saveCfg, streamCheck, getRun, sendChat } from "./api.js";
import SettingsModal from "./components/SettingsModal.vue";
import ImModal from "./components/ImModal.vue";
import HistoryModal from "./components/HistoryModal.vue";

/* Markdown 渲染（LLM 输出经 DOMPurify 消毒后注入） */
marked.setOptions({ breaks: true, gfm: true });
function renderMd(text){
  if(!text) return "";
  return DOMPurify.sanitize(marked.parse(text));
}

/* ---------- 全局状态 ---------- */
const cfg = ref(loadCfg());          // 唯一配置源：弹窗直接改它，不再有副本互相覆盖
const view = ref("home");            // home | work
const showSettings = ref(false);
const showIm = ref(false);
const showHistory = ref(false);

const rumorText = ref("");
const samples = ref([]);
const procLines = ref([]);           // { cls, text }
const procStatus = ref("");
const result = ref(null);
const docMd = ref("");
const runId = ref(null);             // 当次/回放的运行 id（有值才会话可追问）

const V_MAP = { credible: ["v-credible", "可信"], questionable: ["v-questionable", "存疑"], unverifiable: ["v-unverifiable", "无法核实"] };
const T_MAP = { supports: ["supports", "支持"], refutes: ["refutes", "反驳"], unverifiable: ["unverifiable", "无法核实"] };

const finalVerdict = computed(() => {
  if(!result.value) return null;
  const [cls, label] = V_MAP[result.value.final_verdict] || V_MAP.unverifiable;
  return { cls, label };
});
const claimMap = computed(() => {
  const m = {};
  (result.value?.claims || []).forEach(c => (m[c.id] = c));
  return m;
});
const verifications = computed(() =>
  (result.value?.verifications || []).map(v => {
    const [cls, label] = T_MAP[v.verdict] || T_MAP.unverifiable;
    const c = claimMap.value[v.claim_id];
    const conf = v.confidence ?? ({ supports: 85, refutes: 80, unverifiable: 30 }[v.verdict] ?? 50);
    const isWeb = v.source === "web" && (v.source_ref || "").startsWith("http");
    return { cls, label, claim_id: v.claim_id, text: c ? c.text : "断言" + v.claim_id, reasoning: v.reasoning, source: v.source,
             source_ref: isWeb ? "" : v.source_ref, url: isWeb ? v.source_ref : null, conf };
  })
);

/* 搜索带回的参考网页 */
const webSources = computed(() => result.value?.web_sources || []);
function hostOf(u){
  try{ return new URL(u).hostname.replace(/^www\./, ""); }catch{ return u; }
}

/* 置信度：judge 输出优先；缺失时按各断言判定估算 */
const confidence = computed(() => {
  if(result.value?.confidence != null) return { value: result.value.confidence, estimated: false };
  if(!verifications.value.length) return null;
  const est = Math.round(verifications.value.reduce((s, v) => s + v.conf, 0) / verifications.value.length);
  return { value: est, estimated: true };
});
/* 环形图：r=30, 周长≈188.5 */
const CONF_C = 2 * Math.PI * 30;
const confDash = computed(() => {
  if(!confidence.value) return {};
  const len = (Math.max(0, Math.min(100, confidence.value.value)) / 100) * CONF_C;
  return { len, rest: CONF_C - len };
});
const confColor = computed(() => confColorOf(confidence.value?.value ?? 0));
/* 置信度三色区间：高绿 / 中黄 / 低红 */
function confColorOf(v){
  return v >= 75 ? "#16a06a" : v >= 45 ? "#eab308" : "#e5484d";
}

/* 断言行展开状态 + Agent 过程折叠 + 证据快照行 */
const openClaims = ref({});
const showProc = ref(false);
const showDoc = ref(false);
const statClaims = ref(0);
const statEv = ref(0);
const evidenceRows = ref([]);
/* 反驳计数（元信息行警示用） */
const verdictStats = computed(() => {
  const vs = result.value?.verifications || [];
  const c = { supports: 0, refutes: 0, unverifiable: 0 };
  vs.forEach(v => { c[v.verdict] = (c[v.verdict] || 0) + 1; });
  return vs.length ? c : null;
});
const procSummary = computed(() =>
  `规划 ${statClaims.value} 断言 · 取证 ${statEv.value} 条 · ${procStatus.value || "未开始"}`
);
function toggleClaim(i){ openClaims.value[i] = !openClaims.value[i]; }
function claimType(v){ return claimMap.value[v.claim_id]?.type || "claim"; }
function resetExplore(){
  openClaims.value = {};
  showProc.value = false;
  showDoc.value = false;
  evidenceRows.value = [];
  statClaims.value = 0;
  statEv.value = 0;
}
const EV_LABEL = { quote: "quote", announcement: "公告", news: "news", web: "web" };
function formatEvidence(list){
  return (list || []).map(e => {
    const p = e.payload || {};
    if(e.source === "quote")
      return { label: "quote", date: p.date || "", text: `价格 ${p.price} · 涨跌幅 ${p.change_pct}%` };
    const m = /^(\d{4}-\d{2}-\d{2})\s*(.*)$/.exec(p.text || "");
    return { label: EV_LABEL[e.source] || e.source, date: m ? m[1] : "", text: m ? m[2] : (e.source === "web" ? p.title : (p.text || "")) };
  });
}

/* token 用量：done 事件 / 历史记录 */
const usage = ref(null);
const fmtNum = (n) => (n == null ? "-" : n.toLocaleString("en-US"));

/* ---------- 会话（用户 ↔ Agent） ----------
   按 runId 隔离：chatCache 保存每个会话的消息，切换核查/回放历史互不串线 */
const chatCache = {};
const chatMsgs = ref([]);
const chatInput = ref("");
const chatSending = ref(false);

function loadChat(id){
  chatMsgs.value = chatCache[id] || [];
}
function cacheChat(){
  if(runId.value != null) chatCache[runId.value] = chatMsgs.value;
}

async function onSendChat(){
  const text = chatInput.value.trim();
  if(!text || !runId.value) return;
  const rid = runId.value;                  // 锁定当前会话，发送期间切换视图也不串
  chatInput.value = "";
  chatMsgs.value.push({ role: "user", content: text });
  chatSending.value = true;
  let u = null;
  try{
    const r = await sendChat(cfg.value, rid, text);
    u = r.usage || null;
    if(runId.value === rid) chatMsgs.value.push({ role: "assistant", content: r.reply || "（空回复）" });
  }  catch(e){
    if(runId.value === rid) chatMsgs.value.push({ role: "assistant", content: "✕ " + e.message });
  }finally{
    chatSending.value = false;
    if(runId.value === rid){
      chatCache[rid] = chatMsgs.value;
      if(u) toast(`本次追问消耗 ${fmtNum(u.total_tokens)} tokens（入 ${fmtNum(u.prompt_tokens)} / 出 ${fmtNum(u.completion_tokens)}）`);
    }
  }
}

/* ---------- 通用 ---------- */
function toast(msg){
  $("toastMsg").textContent = msg;
  $("toast").classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => $("toast").classList.remove("show"), 2600);
}
function $(id){ return document.getElementById(id); }

function onTheme(){
  const d = document.documentElement.getAttribute("data-theme") === "dark";
  document.documentElement.setAttribute("data-theme", d ? "light" : "dark");
}

function onPaste(){
  navigator.clipboard.readText()
    .then(t => { if(t.trim()){ rumorText.value = t.trim(); toast("已粘贴剪贴板内容"); } else toast("剪贴板为空"); })
    .catch(() => { toast("无法读取剪贴板，请手动粘贴"); });
}

async function onLoadRumors(){
  try{
    const r = await api(cfg.value, "/api/rumors");
    samples.value = r.rumors || [];
    toast(`已载入 ${samples.value.length} 条样例，点击编号填入`);
  }catch(e){ toast("载入失败：" + e.message); }
}

function pickSample(s){ rumorText.value = s.text; }

/* ---------- 核查流程 ---------- */
const checking = ref(false);

const STEP_LABEL = { planner: "规划中…", evidence: "取证中…", judge: "裁决中…" };

function onStart(){
  const text = rumorText.value.trim();
  if(!text){ toast("请输入传闻"); return; }
  saveCfg({ protocol: cfg.value.protocol, apiBase: cfg.value.apiBase, apiKey: cfg.value.apiKey, model: cfg.value.model });
  cacheChat();
  resetExplore();
  view.value = "work";
  procLines.value = [];
  procStatus.value = "核查中…";
  result.value = null;
  docMd.value = "";
  runId.value = null;
  usage.value = null;
  chatMsgs.value = [];
  checking.value = true;
  streamCheck(cfg.value, text, handleEvent)
    .then(() => { procStatus.value = "✓ 完成"; })
    .catch(e => {
      procStatus.value = "✕ 失败：" + (e.message || "连接中断");
      pushLine("error", "✕ " + e.message);
    })
    .finally(() => { checking.value = false; });
}

function handleEvent(event, data){
  if(event === "start"){
    runId.value = data.run_id || null;
    if(runId.value != null) loadChat(runId.value);
    pushLine("start", `开始核查：${data.rumor_text || ""}`);
  }
  else if(event === "step"){
    const label = STEP_LABEL[data.node] || "处理中…";
    procStatus.value = label;
    pushLine("step", "⏳ " + label);
  }
  else if(event === "node") renderNode(data.node, data.output);
  else if(event === "done"){ result.value = data.result; docMd.value = buildDoc(data.result); usage.value = data.usage || null; }
  else if(event === "error"){
    const reason = data.detail || (data.status ? `LLM 调用失败（status=${data.status}）` : "未知错误");
    procStatus.value = "✕ 失败：" + reason;
    pushLine("error", "✕ " + reason);
  }
}

function renderNode(node, out){
  if(!out) return;
  if(node === "planner"){
    statClaims.value = (out.claims || []).length;
    const cs = (out.companies || []).map(c => c.name).join("、") || "无";
    pushLine("plan", `▶ 规划：识别公司 [${cs}]，分解 ${(out.claims || []).length} 条断言`);
    (out.claims || []).forEach(c => pushLine("plan-sub", `    · [${c.type}] ${c.text}（${c.company}）${c.expected ? "· 期望：" + c.expected : ""}`));
  }else if(node === "evidence"){
    const list = out.evidence || [];
    const web = list.filter(e => e.source === "web");
    statEv.value = list.length;
    evidenceRows.value = formatEvidence(list);
    pushLine("ev", `▶ 取证：${list.length} 条证据${web.length ? `（含 ${web.length} 条网页）` : ""}`);
    list.forEach(e => {
      const r = e.source === "quote" ? `价格=${e.payload.price} 涨跌幅=${e.payload.change_pct}%`
        : e.source === "web" ? `${e.payload.title}`
        : (e.payload.text || "").slice(0, 50);
      pushLine("ev-sub", `    · ${e.source}(${e.company}) → ${r}`);
    });
  }else if(node === "judge"){
    pushLine("judge", "▶ 裁决：基于数据快照逐条核查");
  }
}

function pushLine(cls, text){
  procLines.value.push({ cls, text });
}

function buildDoc(r){
  if(!r) return "";
  const vMap = { credible: "可信", questionable: "存疑", unverifiable: "无法核实" };
  const vm = { supports: "支持", refutes: "反驳", unverifiable: "无法核实" };
  const m = {};
  (r.claims || []).forEach(c => (m[c.id] = c));
  const L = ["# 传闻核查报告", "", "## 传闻", r.rumor_text, "", "## 判断", `**${vMap[r.final_verdict] || "无法核实"}**`, "", "## 依据", r.basis || "", "## 逐条核查"];
  (r.verifications || []).forEach(v => {
    const c = m[v.claim_id];
    L.push(`- [${c ? c.text : "断言" + v.claim_id}] — ${vm[v.verdict] || "无法核实"}：${v.reasoning}` + (v.source ? `（来源：${v.source}${v.source_ref ? " · " + v.source_ref : ""}）` : ""));
  });
  L.push("");
  if(r.sources && r.sources.length){ L.push("## 数据来源"); r.sources.forEach(s => L.push("- " + s)); L.push(""); }
  if(r.data_date) L.push(`> 数据日期：${r.data_date}`);
  return L.join("\n");
}

function onCopyMd(){
  if(!docMd.value) return;
  navigator.clipboard.writeText(docMd.value).then(() => toast("已复制 Markdown")).catch(() => toast("复制失败"));
}

function onNewCheck(){
  cacheChat();
  rumorText.value = "";
  view.value = "home";
}

/* ---------- 历史回放 ---------- */

/* URL ?run=N 直接回放（可分享/刷新恢复）；?theme=dark|light 指定主题 */
onMounted(() => {
  const sp = new URLSearchParams(location.search);
  const theme = sp.get("theme");
  if(theme === "dark" || theme === "light") document.documentElement.setAttribute("data-theme", theme);
  const n = parseInt(sp.get("run"), 10);
  if(n) onOpenRun(n);
});

async function onOpenRun(id){
  try{
    cacheChat();
    resetExplore();
    const run = await getRun(cfg.value, id);
    showHistory.value = false;
    rumorText.value = run.rumor_text;
    runId.value = run.id;
    view.value = "work";
    procLines.value = [];
    (run.events || []).forEach(e => {
      if(e.event === "start") pushLine("start", `开始核查：${e.payload.rumor_text || ""}`);
      else if(e.event === "step") pushLine("step", "⏳ " + (STEP_LABEL[e.payload.node] || "处理中…"));
      else if(e.event === "node") renderNode(e.payload.node, e.payload.output);
      else if(e.event === "error") pushLine("error", "✕ " + (e.payload.detail || "错误"));
    });
    result.value = run.result;
    docMd.value = run.report_md || buildDoc(run.result);
    usage.value = (run.prompt_tokens || run.completion_tokens)
      ? { prompt_tokens: run.prompt_tokens || 0, completion_tokens: run.completion_tokens || 0,
          total_tokens: (run.prompt_tokens || 0) + (run.completion_tokens || 0) }
      : null;
    chatMsgs.value = (run.messages || []).map(m => ({ role: m.role, content: m.content }));
    chatCache[run.id] = chatMsgs.value;
    procStatus.value = run.status === "done" ? "✓ 完成（历史回放）"
      : run.status === "error" ? "✕ 失败（历史回放）" + (run.error ? "：" + run.error : "")
      : "核查中…";
    toast(`已载入历史记录 #${run.id}`);
  }catch(e){ toast("载入失败：" + e.message); }
}
</script>

<template>
  <header class="topbar">
    <div class="tb-left">
      <button class="icon" title="IM 接入（飞书）" @click="showIm = true">
        <svg class="ico" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      </button>
      <button class="icon" title="历史核查" @click="showHistory = true">
        <svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      </button>
    </div>
    <div class="tb-center">核真</div>
    <div class="tb-right">
      <button class="icon" title="切换主题" @click="onTheme">◐</button>
      <button class="icon" title="设置" @click="showSettings = true">
        <svg class="ico" viewBox="0 0 24 24"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
      </button>
    </div>
  </header>

  <main class="wrap">
    <!-- 首页 -->
    <section v-if="view === 'home'" class="home">
      <h1 class="home-title">准备开始核查?</h1>
      <form class="pill-form" @submit.prevent="onStart">
        <span class="pill-ico" aria-hidden="true">
          <svg class="ico" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        </span>
        <input id="rumorText" v-model="rumorText" placeholder="输入传闻 / 粘贴文本" autocomplete="off" />
        <div class="pill-actions">
          <span class="pill-sep" aria-hidden="true"></span>
          <button type="button" class="pill-act" title="粘贴剪贴板" @click="onPaste">
            <svg class="ico" viewBox="0 0 24 24"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>
          </button>
          <button type="submit" class="pill-go" title="开始核查">
            <svg class="ico" viewBox="0 0 24 24"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </button>
        </div>
      </form>
      <div v-if="samples.length" class="samples">
        <button v-for="s in samples" :key="s.id" class="sample" :title="s.text" @click="pickSample(s)">#{{ s.id }}</button>
      </div>
      <button class="home-link" @click="onLoadRumors">＋ 载入样例传闻</button>
      <p class="home-hint">核查前请先在 <button class="linklike" @click="showSettings = true">设置</button> 中完成模型配置与连通测试</p>
    </section>

    <!-- 工作视图：结论导向 -->
    <section v-else>
      <div class="card verdict-card">
        <div class="vc-top">
          <span class="vbadge" :class="finalVerdict.cls">
            <svg v-if="finalVerdict.cls !== 'v-credible'" class="ico vico" viewBox="0 0 24 24"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <span v-else class="vdot"></span>
            {{ finalVerdict.label }}
          </span>
          <span v-if="runId" class="sub">#{{ runId }}</span>
          <span class="sp"></span>
          <span v-if="usage" class="tok-pill" title="本次核查全部 LLM 调用消耗（含规划/取证/裁决）">
            <span class="tok-num">{{ fmtNum(usage.total_tokens) }}</span> tokens
            <span class="tok-detail">入 {{ fmtNum(usage.prompt_tokens) }} · 出 {{ fmtNum(usage.completion_tokens) }}<span v-if="usage.calls"> · {{ usage.calls }} 次</span></span>
          </span>
          <button class="ghost" @click="onNewCheck">＋ 新建核查</button>
          <div v-if="confidence" class="conf-donut" :title="confidence.estimated ? '置信度（按断言判定估算）' : '置信度（模型评估）'">
            <svg viewBox="0 0 72 72" width="72" height="72">
              <defs>
                <linearGradient :id="'confGrad' + (runId || 'x')" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" :stop-color="confColor"/>
                  <stop offset="100%" :stop-color="confColor" stop-opacity=".4"/>
                </linearGradient>
              </defs>
              <circle cx="36" cy="36" r="30" fill="none" stroke="var(--border-soft)" stroke-width="5"/>
              <circle cx="36" cy="36" r="30" fill="none" :stroke="`url(#confGrad${runId || 'x'})`" stroke-width="5" stroke-linecap="round"
                      :stroke-dasharray="`${confDash.len} ${confDash.rest}`" transform="rotate(-90 36 36)"/>
              <text x="36" y="41" text-anchor="middle" class="conf-num">{{ confidence.value }}<tspan class="conf-pct">%</tspan></text>
            </svg>
            <span class="conf-cap">置信度{{ confidence.estimated ? "（估）" : "" }}</span>
          </div>
        </div>

        <p class="vc-rumor">「{{ rumorText }}」</p>
        <p v-if="result && result.basis" class="vc-summary md" v-html="renderMd(result.basis)"></p>

        <template v-if="result">
          <div v-if="verifications.length" class="vc-section">
            <div class="vc-sec-head">断言核查 <span class="sub">{{ verifications.length }} 条 · 点击展开核查理由</span></div>
            <div v-for="(v, i) in verifications" :key="i" class="claim-row" :class="{ open: openClaims[i] }">
              <button class="claim-head" @click="toggleClaim(i)">
                <span class="mtype">{{ claimType(v) }}</span>
                <span class="claim-text">{{ v.text }}</span>
                <span class="claim-conf" :style="{ color: confColorOf(v.conf) }">{{ v.conf }}%</span>
                <span class="tag" :class="v.cls">{{ v.label }}</span>
                <svg class="chev ico" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
              </button>
              <div v-show="openClaims[i]" class="claim-body">
                <div class="vreason md" v-html="renderMd(v.reasoning)"></div>
                <div class="vref">
                  <template v-if="v.url">来源：<a class="vlink" :href="v.url" target="_blank" rel="noopener">{{ hostOf(v.url) }} ↗</a></template>
                  <template v-else>{{ v.source ? "来源：" + v.source + (v.source_ref ? " · " + v.source_ref : "") : "" }}</template>
                </div>
              </div>
            </div>
          </div>

          <div v-if="evidenceRows.length" class="vc-section">
            <div class="vc-sec-head">数据快照证据 <span class="sub">{{ evidenceRows.length }} 条</span></div>
            <div v-for="(e, i) in evidenceRows" :key="i" class="ev-row">
              <span class="mtype">{{ e.label }}</span>
              <span class="ev-date">{{ e.date }}</span>
              <span class="ev-text">{{ e.text }}</span>
            </div>
          </div>

          <div v-if="webSources.length" class="web-sources">
            <div class="vc-sec-head">参考网页 <span class="sub">来自真实网络搜索</span></div>
            <a v-for="(w, i) in webSources" :key="w.url" class="ws-item" :href="w.url" target="_blank" rel="noopener" :title="w.title">
              <span class="ws-idx">{{ i + 1 }}</span>
              <span class="ws-main">
                <span class="ws-title">{{ w.title }}</span>
                <span class="ws-meta">{{ hostOf(w.url) }}{{ w.query ? " · 查询：" + w.query : "" }}</span>
                <span v-if="w.snippet" class="ws-snip">{{ w.snippet }}</span>
              </span>
            </a>
          </div>

          <div class="vc-meta">
            <span v-if="result.data_date">数据日期 {{ result.data_date }}</span>
            <span v-if="verdictStats && verdictStats.refutes > 0" class="meta-warn">⚠ {{ verdictStats.refutes }} 条断言被反驳</span>
          </div>
        </template>
        <div v-else class="sub vc-waiting">{{ procStatus }}</div>
      </div>

      <div v-if="runId" class="card">
        <div class="card-head"><h2>会话</h2><span class="sub">#{{ runId }} · 与 Agent 追问本次核查，记录已持久化</span></div>
        <div class="chat-log">
          <div v-if="!chatMsgs.length" class="sub">还没有消息，例如可以问：「主要依据是哪些数据？」</div>
          <div v-for="(m, i) in chatMsgs" :key="m.role + '-' + i" class="chat-msg" :class="m.role">
            <div class="chat-role">{{ m.role === "user" ? "你" : "Agent" }}</div>
            <div v-if="m.role === 'user'" class="chat-bubble">{{ m.content }}</div>
            <div v-else class="chat-bubble md" v-html="renderMd(m.content)"></div>
          </div>
        </div>
        <form class="chat-form" @submit.prevent="onSendChat">
          <input v-model="chatInput" placeholder="输入追问…" autocomplete="off" :disabled="chatSending" />
          <button class="primary" type="submit" :disabled="chatSending || !chatInput.trim()">{{ chatSending ? "发送中…" : "发送" }}</button>
        </form>
      </div>

      <div class="card panel-card">
        <button class="panel-head" @click="showProc = !showProc">
          <h2>Agent 过程</h2>
          <span class="sub">{{ procSummary }}</span>
          <span class="sp"></span>
          <svg class="chev ico" :class="{ rot: showProc }" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        <div v-show="showProc" class="proc-log">
          <div v-for="(l, i) in procLines" :key="i" class="prow" :class="'k-' + l.cls">{{ l.text }}</div>
        </div>
      </div>

      <div v-if="docMd" class="card panel-card">
        <button class="panel-head" @click="showDoc = !showDoc">
          <h2>核查报告</h2>
          <span class="sub">Markdown · 点击{{ showDoc ? "收起" : "展开" }}</span>
          <span class="sp"></span>
          <button class="ghost" @click.stop="onCopyMd">复制 Markdown</button>
          <svg class="chev ico" :class="{ rot: showDoc }" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        <div v-show="showDoc" class="doc md" v-html="renderMd(docMd)"></div>
      </div>
    </section>
  </main>

  <SettingsModal :open="showSettings" :cfg="cfg" @close="showSettings = false" @toast="toast" />
  <ImModal :open="showIm" :cfg="cfg" @close="showIm = false" @toast="toast" />
  <HistoryModal :open="showHistory" :cfg="cfg" @close="showHistory = false" @open-run="onOpenRun" @toast="toast" />

  <div id="toast"><span id="toastMsg"></span></div>
</template>
