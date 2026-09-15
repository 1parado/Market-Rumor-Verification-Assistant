<script setup>
import { ref, watch } from "vue";
import { listRuns, deleteRun } from "../api.js";

const props = defineProps({ open: Boolean, cfg: { type: Object, required: true } });
const emit = defineEmits(["close", "open-run", "toast"]);

const runs = ref([]);
const loading = ref(false);

const V_MAP = { credible: "可信", questionable: "存疑", unverifiable: "无法核实" };
const V_CLS = { credible: "v-credible", questionable: "v-questionable", unverifiable: "v-unverifiable" };

watch(() => props.open, (o) => { if(o) refresh(); });

async function refresh(){
  loading.value = true;
  try{ runs.value = await listRuns(props.cfg); }
  catch(e){ emit("toast", "载入历史失败：" + e.message); runs.value = []; }
  finally{ loading.value = false; }
}

function fmt(ts){
  if(!ts) return "";
  return ts.replace("T", " ").slice(0, 16);
}

async function onDel(r){
  try{
    await deleteRun(props.cfg, r.id);
    await refresh();
    emit("toast", "已删除该记录");
  }catch(e){ emit("toast", "删除失败：" + e.message); }
}
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-labelledby="historyTitle">
      <div class="card-head">
        <h2 id="historyTitle">历史核查</h2>
        <span class="sub">过程 / 结果 / 会话均已在服务端持久化</span>
        <span class="sp"></span>
        <button class="icon" title="刷新" @click="refresh">↻</button>
        <button class="icon" title="关闭" @click="emit('close')">✕</button>
      </div>

      <div v-if="loading" class="sub" style="padding:8px 2px">载入中…</div>
      <div v-else-if="!runs.length" class="sub" style="padding:8px 2px">暂无记录，去首页发起第一次核查吧</div>

      <div v-else class="run-list">
        <div v-for="r in runs" :key="r.id" class="run-item" role="button" tabindex="0"
             @click="emit('open-run', r.id)" @keydown.enter="emit('open-run', r.id)" @keydown.space.prevent="emit('open-run', r.id)">
          <div class="run-title">{{ r.title }}</div>
          <div v-if="r.error" class="run-err" :title="r.error">✕ {{ r.error }}</div>
          <div class="run-meta">
            <span v-if="r.final_verdict" class="vbadge sm" :class="V_CLS[r.final_verdict] || 'v-unverifiable'">● {{ V_MAP[r.final_verdict] || "无法核实" }}</span>
            <span class="tag" :class="'st-' + r.status">{{ r.status === "done" ? "完成" : r.status === "error" ? "失败" : "进行中" }}</span>
            <span class="sub">{{ fmt(r.created_at) }}</span>
            <span class="sp"></span>
            <button class="saved-del" title="删除记录" @click.stop="onDel(r)">✕</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
