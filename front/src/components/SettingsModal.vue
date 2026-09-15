<script setup>
import { ref, reactive, computed, watch, onMounted } from "vue";
import { api, llmPayload, loadCfg, saveCfg, listConfigs, saveConfig, deleteConfig } from "../api.js";

const props = defineProps({ open: Boolean, cfg: { type: Object, required: true } });
const emit = defineEmits(["close", "toast"]);

/* cfg 由 App 持有并传入（单一数据源），此处直接读写它，避免两份副本互相覆盖 */
const form = props.cfg;
const testStatus = ref({ cls: "status", text: "" });
const testing = ref(false);
const fetching = ref(false);
const models = ref([]);
const manual = ref(false);

/* 保存到后端 */
const saveName = ref("");
const saved = ref([]);
const saving = ref(false);
const activeConfigId = ref(null);

const modelOptions = computed(() => {
  const list = [...models.value];
  if(form.model && !list.includes(form.model)) list.unshift(form.model);
  return list;
});

watch(form, () => saveCfg({ ...toPlain(form) }), { deep: true });

watch(() => props.open, (o) => {
  if(o){
    Object.assign(form, loadCfg());
    testStatus.value = { cls: "status", text: "" };
    refreshSaved();
  }
});

onMounted(() => { if(props.open) refreshSaved(); });

function toPlain(c){ return { protocol: c.protocol, apiBase: c.apiBase, apiKey: c.apiKey, model: c.model }; }

async function refreshSaved(){
  try{ saved.value = await listConfigs(form); }
  catch{ saved.value = []; }  // 后端未启动时静默降级为纯本地模式
}

async function onSave(){
  const name = saveName.value.trim();
  if(!name){ emit("toast", "请先填写配置名称"); return; }
  saving.value = true;
  try{
    const r = await saveConfig(form, name);
    activeConfigId.value = r.config?.id ?? null;
    emit("toast", `已保存配置「${name}」`);
    await refreshSaved();
  }catch(e){ emit("toast", "保存失败：" + e.message); }
  finally{ saving.value = false; }
}

function applySaved(c){
  form.protocol = c.protocol; form.apiBase = c.base_url; form.apiKey = c.api_key; form.model = c.model;
  saveCfg({ ...toPlain(form) });
  activeConfigId.value = c.id;
  saveName.value = c.name;
  emit("toast", `已应用配置「${c.name}」`);
}

async function onDelSaved(c){
  try{
    await deleteConfig(form, c.id);
    if(activeConfigId.value === c.id) activeConfigId.value = null;
    await refreshSaved();
    emit("toast", `已删除配置「${c.name}」`);
  }catch(e){ emit("toast", "删除失败：" + e.message); }
}

async function onTest(){
  testStatus.value = { cls: "status", text: "测试中…" };
  testing.value = true;
  try{
    const r = await api(form, "/api/llm/test", JSON_OPTS());
    if(r.ok) testStatus.value = { cls: "status ok", text: `✓ ${r.model} · ${r.reply || ""}` };
    else testStatus.value = { cls: "status fail", text: `✕ ${r.error || "失败"} ${r.detail || ""}` };
  }catch(e){ testStatus.value = { cls: "status fail", text: "✕ " + e.message }; }
  finally{ testing.value = false; }
}

async function onFetchModels(){
  testStatus.value = { cls: "status", text: "拉取模型中…" };
  fetching.value = true;
  try{
    const r = await api(form, "/api/llm/models", JSON_OPTS());
    if(r.ok && r.models && r.models.length){
      models.value = r.models;
      manual.value = false;
      if(!form.model) form.model = r.models[0];
      testStatus.value = { cls: "status ok", text: `✓ 拉取 ${r.models.length} 个模型` };
    }else{
      testStatus.value = { cls: "status fail", text: `✕ ${r.error || "未返回模型"} ${r.detail || ""}` };
    }
  }catch(e){ testStatus.value = { cls: "status fail", text: "✕ " + e.message }; }
  finally{ fetching.value = false; }
}

function JSON_OPTS(){
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ llm: llmPayload(form) }) };
}
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-labelledby="settingsTitle">
      <div class="card-head">
        <h2 id="settingsTitle">设置 · 模型配置</h2>
        <span class="sub">自带 URL / Key，可保存到服务端</span>
        <span class="sp"></span>
        <button class="icon" title="关闭" @click="emit('close')">✕</button>
      </div>

      <div v-if="saved.length" class="field span2 saved-row">
        <span>已保存配置</span>
        <div class="saved-list">
          <span v-for="c in saved" :key="c.id" class="saved-chip" :class="{ active: c.id === activeConfigId }">
            <button class="saved-use" :title="`${c.model} @ ${c.base_url}`" @click="applySaved(c)">{{ c.name }}</button>
            <button class="saved-del" title="删除该配置" @click="onDelSaved(c)">✕</button>
          </span>
        </div>
      </div>

      <div class="form">
        <label class="field span2"><span>Base URL</span><input v-model="form.apiBase" placeholder="https://api.openai.com/v1"></label>
        <label class="field"><span>API Key</span><input v-model="form.apiKey" type="password" placeholder="sk-..."></label>
        <label class="field"><span>协议</span>
          <select v-model="form.protocol">
            <option value="openai_chat">OpenAI Chat Completions</option>
            <option value="openai_responses">OpenAI Responses</option>
            <option value="anthropic">Anthropic Messages</option>
          </select>
        </label>
        <div class="field span2"><span>模型</span>
          <div v-if="models.length && !manual" class="model-row">
            <select v-model="form.model">
              <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
            </select>
            <button class="ghost" type="button" title="手动填写模型名" @click="manual = true">手动输入</button>
          </div>
          <div v-else class="model-row">
            <input v-model="form.model" placeholder="填写 URL / Key 后点击「拉取模型」获取列表" />
            <button v-if="models.length" class="ghost" type="button" @click="manual = false">选列表</button>
          </div>
        </div>
        <label class="field"><span>配置名称</span><input v-model="saveName" placeholder="如：deepseek-主账号" @keyup.enter="onSave"></label>
        <div class="field span2 actions">
          <button class="primary" :disabled="saving" @click="onSave">保存配置</button>
          <button class="ghost" :disabled="fetching" @click="onFetchModels">拉取模型</button>
          <button class="ghost" :disabled="testing" @click="onTest">连通测试</button>
          <span :class="testStatus.cls">{{ testStatus.text }}</span>
        </div>
      </div>
      <p class="sub" style="margin:10px 2px 0">改动自动保存到本地 · 「保存配置」存到服务端可多设备复用 · 后端地址默认与本站一致</p>
    </div>
  </div>
</template>
