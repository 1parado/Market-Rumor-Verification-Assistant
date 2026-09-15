<script setup>
defineProps({ open: Boolean });
const emit = defineEmits(["close"]);
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-labelledby="imTitle">
      <div class="card-head">
        <h2 id="imTitle">IM 接入</h2>
        <span class="sp"></span>
        <button class="icon" title="关闭" @click="emit('close')">✕</button>
      </div>
      <div class="im-body">
        <div class="im-badge">飞书 · Lark</div>
        <p>IM 功能入口已预留，后续将接入飞书：</p>
        <ul>
          <li>群内 <b>@核真机器人</b> 直接发起传闻核查</li>
          <li>核查完成后自动推送<b>结论卡片</b>到群聊</li>
          <li>低置信度结果转私聊<b>人工审批</b></li>
        </ul>
        <p class="sub">当前版本：敬请期待</p>
      </div>
    </div>
  </div>
</template>
