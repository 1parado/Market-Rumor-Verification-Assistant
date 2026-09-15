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
    return { cls, label, text: c ? c.text : "断言" + v.claim_id, reasoning: v.reasoning, source: v.source, source_ref: v.source_ref, conf };
  })
);

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
const confColor = computed(() => {
  if(!confidence.value) return "var(--text-3)";
  const v = confidence.value.value;
  return v >= 75 ? "#16a06a" : v >= 45 ? "#f08c00" : "#e5484d";
});

/* 断言判定统计 → 底部状态条 */
const verdictStats = computed(() => {
  const vs = result.value?.verifications || [];
  if(!vs.length) return null;
  const c = { supports: 0, refutes: 0, unverifiable: 0 };
  vs.forEach(v => { c[v.verdict] = (c[v.verdict] || 0) + 1; });
  return c;
});

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
    const cs = (out.companies || []).map(c => c.name).join("、") || "无";
    pushLine("plan", `▶ 规划：识别公司 [${cs}]，分解 ${(out.claims || []).length} 条断言`);
    (out.claims || []).forEach(c => pushLine("plan-sub", `    · [${c.type}] ${c.text}（${c.company}）${c.expected ? "· 期望：" + c.expected : ""}`));
  }else if(node === "evidence"){
    pushLine("ev", `▶ 取证：${(out.evidence || []).length} 条证据`);
    (out.evidence || []).forEach(e => {
      const r = e.source === "quote" ? `价格=${e.payload.price} 涨跌幅=${e.payload.change_pct}%` : (e.payload.text || "").slice(0, 50);
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

/* URL ?run=N 直接回放（可分享/刷新恢复） */
onMounted(() => {
  const n = parseInt(new URLSearchParams(location.search).get("run"), 10);
  if(n) onOpenRun(n);
});

async function onOpenRun(id){
  try{
    cacheChat();
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

    <!-- 工作视图 -->
    <section v-else>
      <div class="card">
        <div class="card-head"><h2>传闻</h2><span v-if="runId" class="sub">#{{ runId }}</span><span class="sp"></span><button class="ghost" @click="onNewCheck">＋ 新建核查</button></div>
        <p class="rumor-echo">{{ rumorText }}</p>
      </div>

      <div class="card">
        <div class="card-head"><h2>Agent 过程</h2><span class="sub">{{ procStatus }}</span></div>
        <div class="proc-log">
          <div v-for="(l, i) in procLines" :key="i" class="prow" :class="'k-' + l.cls">{{ l.text }}</div>
        </div>
      </div>

      <div v-if="result" class="card">
        <div class="card-head">
          <h2>核查结果</h2>
          <span class="sub">{{ result.data_date ? "数据日期 " + result.data_date : "" }}</span>
          <span class="sp"></span>
          <span v-if="usage" class="tok-chip" title="本次核查全部 LLM 调用消耗（含规划/取证/裁决）">
            ⚡ {{ fmtNum(usage.total_tokens) }} tokens<span v-if="usage.calls"> · {{ usage.calls }} 次调用</span>（入 {{ fmtNum(usage.prompt_tokens) }} / 出 {{ fmtNum(usage.completion_tokens) }}）
          </span>
        </div>
        <div class="final">
          <span class="vbadge" :class="finalVerdict.cls">
            <svg v-if="finalVerdict.cls === 'v-questionable'" class="ico vico" viewBox="0 0 24 24"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <span v-else class="vdot"></span>
            {{ finalVerdict.label }}
          </span>
          <div v-if="confidence" class="conf-donut" :title="confidence.estimated ? '置信度（按断言判定估算）' : '置信度（模型评估）'">
            <svg viewBox="0 0 72 72" width="72" height="72">
              <defs>
                <linearGradient id="confGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" :stop-color="confColor"/>
                  <stop offset="100%" :stop-color="confColor" stop-opacity=".45"/>
                </linearGradient>
              </defs>
              <circle cx="36" cy="36" r="30" fill="none" stroke="var(--border-soft)" stroke-width="5.5"/>
              <circle cx="36" cy="36" r="30" fill="none" stroke="url(#confGrad)" stroke-width="5.5" stroke-linecap="round"
                      :stroke-dasharray="`${confDash.len} ${confDash.rest}`" transform="rotate(-90 36 36)"/>
              <text x="36" y="41" text-anchor="middle" class="conf-num">{{ confidence.value }}<tspan class="conf-pct">%</tspan></text>
            </svg>
            <span class="conf-cap">置信度{{ confidence.estimated ? "（估）" : "" }}</span>
          </div>
        </div>
        <p class="basis md" v-html="renderMd(result.basis)"></p>
        <div v-if="verifications.length" class="verts">
          <div v-for="(v, i) in verifications" :key="i" class="vert">
            <div class="vhead"><span class="tag" :class="v.cls">{{ v.label }}</span><span class="vt">{{ v.text }}</span>
              <span class="sp"></span>
              <span class="conf-pill" :title="'置信度 ' + v.conf + '/100'">
                <span class="conf-bar"><span class="conf-fill" :style="{ width: v.conf + '%', background: v.conf >= 75 ? 'var(--ok)' : v.conf >= 45 ? 'var(--warn)' : 'var(--danger)' }"></span></span>
                <span class="conf-val">{{ v.conf }}%</span>
              </span>
            </div>
            <div class="vreason md" v-html="renderMd(v.reasoning)"></div>
            <div class="vref">{{ v.source ? "来源：" + v.source + (v.source_ref ? " · " + v.source_ref : "") : "" }}</div>
          </div>
        </div>
        <div v-if="verdictStats" class="verdict-strip" :class="{ warn: verdictStats.refutes > 0 }">
          <div class="vs-bar">
            <span class="vs-seg ok" :style="{ flex: verdictStats.supports }" v-show="verdictStats.supports"></span>
            <span class="vs-seg bad" :style="{ flex: verdictStats.refutes }" v-show="verdictStats.refutes"></span>
            <span class="vs-seg unk" :style="{ flex: verdictStats.unverifiable }" v-show="verdictStats.unverifiable"></span>
          </div>
          <div class="vs-legend">
            <span class="ok"><i></i>支持 {{ verdictStats.supports }}</span>
            <span class="bad"><i></i>反驳 {{ verdictStats.refutes }}</span>
            <span class="unk"><i></i>无法核实 {{ verdictStats.unverifiable }}</span>
          </div>
        </div>
        <div v-if="result.sources && result.sources.length" class="src"><b>引用来源：</b>{{ result.sources.join(" · ") }}</div>
      </div>

      <div v-if="docMd" class="card">
        <div class="card-head"><h2>核查报告</h2><button class="ghost" @click="onCopyMd">复制 Markdown</button></div>
        <div class="doc md" v-html="renderMd(docMd)"></div>
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
    </section>
  </main>

  <SettingsModal :open="showSettings" :cfg="cfg" @close="showSettings = false" @toast="toast" />
  <ImModal :open="showIm" @close="showIm = false" />
  <HistoryModal :open="showHistory" :cfg="cfg" @close="showHistory = false" @open-run="onOpenRun" @toast="toast" />

  <div id="toast"><span id="toastMsg"></span></div>
</template>
