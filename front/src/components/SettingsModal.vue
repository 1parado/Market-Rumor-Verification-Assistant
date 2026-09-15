<script setup>
import { ref, reactive, watch } from "vue";
import { api, llmPayload, loadCfg, saveCfg } from "../api.js";

const props = defineProps({ open: Boolean });
const emit = defineEmits(["close", "toast"]);

const form = reactive(loadCfg());
const testStatus = ref({ cls: "status", text: "" });
const testing = ref(false);
const fetching = ref(false);
const models = ref([]);

/* 变更即静默保存（不含 baseUrl，见 api.js） */
watch(form, () => saveCfg({ ...form }), { deep: true });

watch(() => props.open, (o) => { if(o){ Object.assign(form, loadCfg()); testStatus.value = { cls: "status", text: "" }; } });

async function onTest(){
  testStatus.value = { cls: "status", text: "测试中…" };
  testing.value = true;
  try{
    const r = await api(form, "/api/llm/test", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ llm: llmPayload(form) }),
    });
    if(r.ok) testStatus.value = { cls: "status ok", text: `✓ ${r.model} · ${r.reply || ""}` };
    else testStatus.value = { cls: "status fail", text: `✕ ${r.error || "失败"} ${r.detail || ""}` };
  }catch(e){ testStatus.value = { cls: "status fail", text: "✕ " + e.message }; }
  finally{ testing.value = false; }
}

async function onFetchModels(){
  testStatus.value = { cls: "status", text: "拉取模型中…" };
  fetching.value = true;
  try{
    const r = await api(form, "/api/llm/models", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ llm: llmPayload(form) }),
    });
    if(r.ok && r.models && r.models.length){
      models.value = r.models;
      if(!form.model) form.model = r.models[0];
      testStatus.value = { cls: "status ok", text: `✓ 拉取 ${r.models.length} 个模型` };
    }else{
      testStatus.value = { cls: "status fail", text: `✕ ${r.error || "未返回模型"} ${r.detail || ""}` };
    }
  }catch(e){ testStatus.value = { cls: "status fail", text: "✕ " + e.message }; }
  finally{ fetching.value = false; }
}
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-labelledby="settingsTitle">
      <div class="card-head">
        <h2 id="settingsTitle">设置 · 模型配置</h2>
        <span class="sub">自带 URL / Key，仅存本地</span>
        <span class="sp"></span>
        <button class="icon" title="关闭" @click="emit('close')">✕</button>
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
        <label class="field span2"><span>模型</span>
          <input v-model="form.model" placeholder="填好后可一键拉取模型列表" list="modelList" />
          <datalist id="modelList">
            <option v-for="m in models" :key="m" :value="m" />
          </datalist>
        </label>
        <div class="field span2 actions">
          <button class="ghost" :disabled="fetching" @click="onFetchModels">拉取模型</button>
          <button class="primary" :disabled="testing" @click="onTest">连通测试</button>
          <span :class="testStatus.cls">{{ testStatus.text }}</span>
        </div>
      </div>
      <p class="sub" style="margin:10px 2px 0">改动自动保存到本地 · 后端地址默认与本站一致</p>
    </div>
  </div>
</template>
