<script setup>
import { ref, computed } from "vue";
import { api, loadCfg, saveCfg, streamCheck } from "./api.js";
import SettingsModal from "./components/SettingsModal.vue";
import ImModal from "./components/ImModal.vue";

/* ---------- 全局状态 ---------- */
const cfg = ref(loadCfg());
const view = ref("home");            // home | work
const showSettings = ref(false);
const showIm = ref(false);

const rumorText = ref("");
const samples = ref([]);
const procLines = ref([]);           // { cls, text }
const procStatus = ref("");
const result = ref(null);
const docMd = ref("");

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
    return { cls, label, text: c ? c.text : "断言" + v.claim_id, reasoning: v.reasoning, source: v.source, source_ref: v.source_ref };
  })
);

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

function onStart(){
  const text = rumorText.value.trim();
  if(!text){ toast("请输入传闻"); return; }
  saveCfg(cfg.value);
  view.value = "work";
  procLines.value = [];
  procStatus.value = "核查中…";
  result.value = null;
  docMd.value = "";
  checking.value = true;
  streamCheck(cfg.value, text, handleEvent)
    .then(() => { procStatus.value = "✓ 完成"; })
    .catch(e => {
      procStatus.value = "✕ 失败";
      pushLine("error", "✕ " + e.message);
    })
    .finally(() => { checking.value = false; });
}

function handleEvent(event, data){
  if(event === "start") pushLine("start", `开始核查：${data.rumor_text || ""}`);
  else if(event === "node") renderNode(data.node, data.output);
  else if(event === "done"){ result.value = data.result; docMd.value = buildDoc(data.result); }
  else if(event === "error") pushLine("error", `✕ ${data.detail || data.status || "错误"}`);
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
  rumorText.value = "";
  view.value = "home";
}
</script>

<template>
  <header class="topbar">
    <div class="tb-left">
      <button class="icon" title="IM 接入（飞书）" @click="showIm = true">
        <svg class="ico" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
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
        <div class="card-head"><h2>传闻</h2><button class="ghost" @click="onNewCheck">＋ 新建核查</button></div>
        <p class="rumor-echo">{{ rumorText }}</p>
      </div>

      <div class="card">
        <div class="card-head"><h2>Agent 过程</h2><span class="sub">{{ procStatus }}</span></div>
        <div class="proc-log">
          <div v-for="(l, i) in procLines" :key="i" class="prow" :class="'k-' + l.cls">{{ l.text }}</div>
        </div>
      </div>

      <div v-if="result" class="card">
        <div class="card-head"><h2>核查结果</h2><span class="sub">{{ result.data_date ? "数据日期 " + result.data_date : "" }}</span></div>
        <div class="final"><span class="vbadge" :class="finalVerdict.cls">● {{ finalVerdict.label }}</span></div>
        <p class="basis">{{ result.basis }}</p>
        <div v-if="verifications.length" class="verts">
          <div v-for="(v, i) in verifications" :key="i" class="vert">
            <div class="vhead"><span class="tag" :class="v.cls">{{ v.label }}</span><span class="vt">{{ v.text }}</span></div>
            <div class="vreason">{{ v.reasoning }}</div>
            <div class="vref">{{ v.source ? "来源：" + v.source + (v.source_ref ? " · " + v.source_ref : "") : "" }}</div>
          </div>
        </div>
        <div v-if="result.sources && result.sources.length" class="src"><b>引用来源：</b>{{ result.sources.join(" · ") }}</div>
      </div>

      <div v-if="docMd" class="card">
        <div class="card-head"><h2>核查报告</h2><button class="ghost" @click="onCopyMd">复制 Markdown</button></div>
        <pre class="doc">{{ docMd }}</pre>
      </div>
    </section>
  </main>

  <SettingsModal :open="showSettings" @close="showSettings = false" @toast="toast" />
  <ImModal :open="showIm" @close="showIm = false" />

  <div id="toast"><span id="toastMsg"></span></div>
</template>
