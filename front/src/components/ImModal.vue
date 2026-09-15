<script setup>
/* IM 接入 · 飞书：扫码 OAuth → 保存实例 → 长连接接收 @机器人核查
   仿 SettingsModal 模式：cfg 由 App 持有传入，toast 回弹。 */
import { ref, watch, onMounted, onUnmounted } from "vue";
import {
  feishuState, feishuScanBegin, feishuScanPoll,
  feishuSaveInstance, feishuStopInstance, feishuDeleteInstance,
  listConfigs,
} from "../api.js";

const props = defineProps({ open: Boolean, cfg: { type: Object, required: true } });
const emit = defineEmits(["close", "toast"]);

const instances = ref([]);
const modelConfigs = ref([]);
const modelConfigId = ref(null);   // 扫码保存时关联的模型配置
const instanceName = ref("");      // 可选实例名

const scanning = ref(false);
const qrUri = ref("");
const scanStatus = ref("");
let scanTimer = null;
let deviceCode = "";               // 不需响应式，普通实例变量即可
let backoff = 0;

watch(() => props.open, (o) => {
  if (o) { loadAll(); }
  else { stopScan(); }
});
onMounted(() => { if (props.open) loadAll(); });
onUnmounted(() => stopScan());

async function loadAll() {
  try { instances.value = await feishuState(props.cfg); }
  catch { instances.value = []; }   // 后端未启动时静默降级
  try {
    modelConfigs.value = await listConfigs(props.cfg);
    if (modelConfigs.value.length && modelConfigId.value == null) {
      modelConfigId.value = modelConfigs.value[0].id;
    }
  } catch { modelConfigs.value = []; }
}

async function startScan() {
  stopScan();
  if (!modelConfigId.value) { emit("toast", "请先选择关联的模型配置"); return; }
  scanning.value = true;
  qrUri.value = "";
  scanStatus.value = "发起扫码…";
  backoff = 0;
  try {
    const r = await feishuScanBegin(props.cfg, "feishu");
    if (r.error) { emit("toast", "扫码发起失败：" + r.error); scanning.value = false; return; }
    deviceCode = r.device_code;
    qrUri.value = r.verification_uri;
    scanStatus.value = "请用飞书 App 扫描下方二维码";
    const interval = Math.max(2000, (r.interval_sec || 3) * 1000);
    pollScan(interval);
  } catch (e) {
    emit("toast", "扫码发起失败：" + e.message);
    scanning.value = false;
  }
}

function pollScan(delay) {
  scanTimer = setTimeout(async () => {
    try {
      const r = await feishuScanPoll(props.cfg, "feishu", deviceCode);
      if (r.verification_uri) qrUri.value = r.verification_uri;
      if (r.device_code) deviceCode = r.device_code;
      if (r.status === "completed") {
        const name = instanceName.value.trim() || `飞书-${(instances.value.length || 0) + 1}`;
        await feishuSaveInstance(props.cfg, {
          name, channel: r.platform || "feishu",
          app_id: r.app_id, app_secret: r.app_secret,
          owner_open_id: r.owner_open_id,
          model_config_id: modelConfigId.value,
          enabled: true,
        });
        emit("toast", "扫码授权成功，已接入飞书");
        scanStatus.value = "✓ 授权成功，已接入";
        stopScan();
        await loadAll();
        return;
      }
      if (r.status === "denied" || r.status === "expired" || r.status === "error") {
        emit("toast", "扫码失败：" + (r.error || r.status));
        scanStatus.value = "✕ " + (r.error || r.status);
        stopScan();
        return;
      }
      // pending（含 slow_down）
      if (r.slow_down) backoff = (backoff || 0) + 2000;
      scanStatus.value = "请用飞书 App 扫描下方二维码";
      const next = Math.max(2000, (r.interval_sec || 3) * 1000) + (backoff || 0);
      pollScan(next);
    } catch (e) {
      emit("toast", "扫码轮询失败：" + e.message);
      stopScan();
    }
  }, delay);
}

function stopScan() {
  if (scanTimer) { clearTimeout(scanTimer); scanTimer = null; }
  scanning.value = false;
}

async function onStop(inst) {
  try {
    await feishuStopInstance(props.cfg, inst.id);
    emit("toast", `已停用 ${inst.name}`);
    await loadAll();
  } catch (e) { emit("toast", "停用失败：" + e.message); }
}

async function onDelete(inst) {
  if (!confirm(`删除实例「${inst.name}」？`)) return;
  try {
    await feishuDeleteInstance(props.cfg, inst.id);
    emit("toast", `已删除 ${inst.name}`);
    await loadAll();
  } catch (e) { emit("toast", "删除失败：" + e.message); }
}

const STATUS_LABEL = { connected: "已连接", configured: "已配置", error: "错误", stopped: "已停用" };
function statusLabel(s) { return STATUS_LABEL[s] || s; }
function statusCls(s) { return "st-" + (s || "configured"); }
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-labelledby="imTitle">
      <div class="card-head">
        <h2 id="imTitle">IM 接入 · 飞书</h2>
        <span class="sub">扫码即接入，无需手动填凭证</span>
        <span class="sp"></span>
        <button class="icon" title="关闭" @click="emit('close')">✕</button>
      </div>

      <div class="im-body">
        <div class="field span2">
          <span>关联模型配置</span>
          <select v-model="modelConfigId" :disabled="!modelConfigs.length">
            <option v-for="c in modelConfigs" :key="c.id" :value="c.id">{{ c.name }}（{{ c.model }}）</option>
          </select>
        </div>
        <p v-if="!modelConfigs.length" class="sub im-hint">⚠ 请先在「设置」中保存一个模型配置，接入后 @机器人将用该配置核查传闻。</p>

        <label class="field span2">
          <span>实例名称（可选）</span>
          <input v-model="instanceName" placeholder="如：核真飞书机器人" />
        </label>

        <div class="im-scan">
          <button class="primary" :disabled="scanning || !modelConfigId" @click="startScan">
            {{ scanning ? "扫码中…" : "扫码接入飞书" }}
          </button>
          <div v-if="qrUri" class="im-qr">
            <img :src="qrUri" alt="飞书扫码接入" />
            <p class="sub">{{ scanStatus }}</p>
          </div>
          <p v-else-if="scanning" class="sub">{{ scanStatus }}</p>
        </div>
        <p class="sub im-hint">扫码后飞书将自动创建 PersonalAgent 应用凭据（app_id/app_secret），并建立 WebSocket 长连接接收消息。</p>

        <div v-if="instances.length" class="im-instances">
          <div class="card-subhead">已接入实例 <span class="sub">{{ instances.length }} 个</span></div>
          <div v-for="inst in instances" :key="inst.id" class="im-row">
            <span class="im-name">{{ inst.name }}</span>
            <span class="im-channel">{{ inst.channel }}</span>
            <span class="tag" :class="statusCls(inst.status)">{{ statusLabel(inst.status) }}</span>
            <span v-if="inst.last_error" class="im-err" :title="inst.last_error">⚠</span>
            <span class="sp"></span>
            <button v-if="inst.enabled" class="ghost" @click="onStop(inst)">停用</button>
            <button class="ghost" @click="onDelete(inst)">删除</button>
          </div>
        </div>
        <p v-else class="sub">尚未接入任何飞书实例。</p>

        <div class="im-usage">
          <div class="card-subhead">使用方式</div>
          <ul class="im-ul">
            <li>在飞书群或私聊 <b>@核真机器人</b>，发送一条股市传闻</li>
            <li>机器人自动核查并以纯文本结论回复</li>
            <li>群聊必须 @机器人，私聊可直接发消息</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.im-body { padding: 0 2px; display: flex; flex-direction: column; gap: 12px; }
.im-hint { margin: 2px 2px 0; }
.im-scan { display: flex; flex-direction: column; align-items: center; gap: 10px; margin: 4px 0; }
.im-qr { text-align: center; }
.im-qr img { width: 200px; height: 200px; image-rendering: pixelated; border: 1px solid var(--border-soft); border-radius: var(--radius, 8px); }
.im-instances { display: flex; flex-direction: column; gap: 2px; }
.im-row { display: flex; align-items: center; gap: 8px; padding: 8px 4px; border-bottom: 1px solid var(--border-soft); }
.im-name { font-weight: 600; }
.im-channel { color: var(--sub, #888); font-size: 0.85em; }
.im-err { color: var(--danger, #e5484d); cursor: help; }
.tag.st-connected { color: #16a06a; }
.tag.st-configured { color: #888; }
.tag.st-stopped { color: #888; }
.tag.st-error { color: #e5484d; }
.im-usage { margin-top: 4px; }
.im-ul { margin: 6px 0 0 18px; padding: 0; color: var(--text, #333); line-height: 1.8; }
.im-ul li { list-style: disc; }
.card-subhead { font-weight: 600; font-size: 0.95em; display: flex; align-items: center; gap: 8px; }
</style>
