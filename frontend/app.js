/* 核真 Veritas · app.js — 交互逻辑（遵循 AGENT.md 原则四） */
"use strict";

/* ---------- 主题切换（浅色默认，深色同规格；记忆用户偏好） ---------- */
const root = document.documentElement;
const themeBtn = document.getElementById("themeBtn");
const savedTheme = localStorage.getItem("vt-theme");
if (savedTheme) root.setAttribute("data-theme", savedTheme);
themeBtn.onclick = () => {
  const dark = root.getAttribute("data-theme") === "dark";
  root.setAttribute("data-theme", dark ? "light" : "dark");
  localStorage.setItem("vt-theme", dark ? "light" : "dark");
};

/* ---------- 自主程度滑块 ---------- */
const dial = document.getElementById("dial");
const dialFill = document.getElementById("dialFill");
const autoPct = document.getElementById("autoPct");
function syncDial() {
  dialFill.style.width = dial.value + "%";
  autoPct.textContent = dial.value + "%";
}
dial.oninput = syncDial;
syncDial();

/* ---------- 中栏视图切换 ---------- */
document.querySelectorAll(".mtab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".mtab").forEach((x) => x.classList.toggle("on", x === t));
    document.querySelectorAll(".mview").forEach((v) => v.classList.toggle("on", v.id === "v-" + t.dataset.v));
  })
);

/* ---------- 右栏标签切换 ---------- */
document.querySelectorAll(".r-tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".r-tab").forEach((x) => x.classList.toggle("on", x === t));
    document.querySelectorAll(".r-view").forEach((v) => v.classList.toggle("on", v.id === "r-" + t.dataset.r));
  })
);

/* ---------- 左右侧栏：边缘把手（点击折叠 / 拖拽调宽 / 双击重置） ---------- */
const shell = document.querySelector(".shell");
const SIDEBAR_MIN = 180;
const SIDEBAR_MAX = 520;

const gutters = [
  { el: document.getElementById("leftGutter"),  side: "left",  open: "‹", closed: "›", label: "左侧栏" },
  { el: document.getElementById("rightGutter"), side: "right", open: "›", closed: "‹", label: "右侧栏" },
];

function syncGutters() {
  gutters.forEach((g) => {
    const hidden = shell.classList.contains(g.side + "-hidden");
    const btn = g.el.querySelector(".gutter-btn");
    btn.textContent = hidden ? g.closed : g.open;
    btn.setAttribute("title", (hidden ? "显示" : "隐藏") + g.label);
    btn.setAttribute("aria-expanded", String(!hidden));
    g.el.classList.toggle("is-collapsed", hidden);
  });
}

function sidebarEl(g) {
  return g.side === "left"
    ? g.el.previousElementSibling
    : g.el.nextElementSibling;
}

gutters.forEach((g) => {
  const btn = g.el.querySelector(".gutter-btn");

  /* 点击按钮 = 折叠 / 展开 */
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const hidden = shell.classList.toggle(g.side + "-hidden");
    syncGutters();
    toast((hidden ? "已隐藏 · 拖动边缘可再展开 " : "已显示") + g.label);
  });

  /* 拖拽把手 = 调宽；折叠状态拖拽 = 直接展开 */
  let dragging = false, startX = 0, startW = 0;
  g.el.addEventListener("pointerdown", (e) => {
    if (e.target === btn) return;
    if (shell.classList.contains(g.side + "-hidden")) {
      shell.classList.remove(g.side + "-hidden");
      syncGutters();
      toast("已显示" + g.label);
      return;
    }
    dragging = true;
    startX = e.clientX;
    startW = sidebarEl(g).getBoundingClientRect().width;
    g.el.classList.add("dragging");
    document.body.classList.add("resizing");
    g.el.setPointerCapture(e.pointerId);
  });
  g.el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    let w = g.side === "left" ? startW + dx : startW - dx;
    w = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w));
    shell.style.setProperty("--" + g.side + "-w", w + "px");
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    g.el.classList.remove("dragging");
    document.body.classList.remove("resizing");
  };
  g.el.addEventListener("pointerup", endDrag);
  g.el.addEventListener("pointercancel", endDrag);

  /* 双击 = 重置为默认宽度 */
  g.el.addEventListener("dblclick", (e) => {
    if (e.target === btn) return;
    shell.style.removeProperty("--" + g.side + "-w");
    toast(g.label + "宽度已重置");
  });
});

syncGutters();

/* 侧栏宽度持久化：拖拽结束保存，刷新恢复 */
gutters.forEach((g) => {
  const saved = parseInt(localStorage.getItem("vt-w-" + g.side), 10);
  if (saved >= SIDEBAR_MIN && saved <= SIDEBAR_MAX) {
    shell.style.setProperty("--" + g.side + "-w", saved + "px");
  }
  g.el.addEventListener("pointerup", () => {
    const w = parseInt(shell.style.getPropertyValue("--" + g.side + "-w"), 10);
    if (w) localStorage.setItem("vt-w-" + g.side, w);
  });
});

/* ---------- 结果卡：点击 / Enter 展开完整依据（渐进披露） ---------- */
document.querySelectorAll(".result-card").forEach((card) => {
  const toggle = () => {
    const open = card.classList.toggle("open");
    card.setAttribute("aria-expanded", String(open));
  };
  card.addEventListener("click", (e) => {
    if (e.target.closest("button, a")) return;
    toggle();
  });
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  });
});

/* ---------- 结果卡折叠：Plan / Conversation 默认收起 ---------- */
document.querySelectorAll(".fold-toggle").forEach((btn) =>
  btn.addEventListener("click", () => {
    const card = btn.closest(".card");
    const closed = card.classList.toggle("closed");
    btn.setAttribute("aria-expanded", String(!closed));
  })
);

/* ---------- Escape Hatch：暂停 / 接管 ---------- */
let paused = false;
const quitBtn = document.getElementById("quitBtn");
quitBtn.addEventListener("click", () => {
  paused = !paused;
  quitBtn.textContent = paused ? "▶ 恢复执行" : "⏸ 暂停 / 接管";
  quitBtn.style.color = paused ? "var(--warn)" : "";
  const chip = document.getElementById("runChip");
  chip.classList.toggle("paused", paused);
  chip.innerHTML = paused
    ? '<i style="background:var(--warn);animation:none"></i>已暂停 · 等待接管'
    : '<i></i>Running · 4/5';
  toast(paused ? "所有 Agent 已暂停，控制权移交给你" : "任务已恢复执行");
});

/* Esc 键 = 暂停/接管（AGENT.md 键盘优先） */
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") quitBtn.click();
});

/* ---------- 审批：可撤销而非阻断 ---------- */
let apprLeft = document.querySelectorAll("[data-appr]").length;
let lastAction = null; // { card, undone }

function appr(btn, msg, kind) {
  const card = btn.closest("[data-appr]");
  card.classList.add("leaf");
  apprLeft--;
  refreshApprCount();
  lastAction = { card };
  const undo = showToast(msg, true);
  if (undo) {
    document.getElementById("undoBtn").onclick = () => {
      card.classList.remove("leaf");
      apprLeft++;
      refreshApprCount();
      hideToast();
      toast("已撤销");
      lastAction = null;
    };
  }
}
function refreshApprCount() {
  const n = document.getElementById("apprN");
  n.textContent = apprLeft;
  n.style.display = apprLeft ? "" : "none";
  document.getElementById("apprSub").textContent = apprLeft + " 项";
}

/* ---------- toast（含 5s 撤销窗口） ---------- */
const toastEl = document.getElementById("toast");
const toastMsg = document.getElementById("toastMsg");
const undoBtn = document.getElementById("undoBtn");
let toastTimer;
function showToast(msg, withUndo) {
  toastMsg.textContent = msg;
  undoBtn.hidden = !withUndo;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, withUndo ? 5000 : 2600);
  return withUndo;
}
function hideToast() {
  toastEl.classList.remove("show");
}
function toast(msg) {
  showToast(msg, false);
}

/* ---------- 活动条目展开 ---------- */
function tg(el) {
  el.closest(".act").classList.toggle("open");
}

/* ---------- 插件开关 ---------- */
document.querySelectorAll(".sw").forEach((s) =>
  s.addEventListener("click", () => {
    s.classList.toggle("on");
    toast(s.classList.contains("on") ? "插件已启用" : "插件已停用");
  })
);

/* ---------- 左栏会话切换 ---------- */
document.querySelectorAll(".s-row").forEach((r) =>
  r.addEventListener("click", () => {
    if (!r.querySelector(".g")) return;
    document.querySelectorAll(".s-row").forEach((x) => x.classList.remove("on"));
    r.classList.add("on");
  })
);

/* ---------- 低频活动流模拟（9s 一条，暂停时停止） ---------- */
const feed = [
  { cls: "ok", t: "行情查询器", n: 'get_quote("新湾储能") → 首日 -12.3%，破发确认', d: '{ "price":18.75, "change_pct":-0.8 }' },
  { cls: "ok", t: "主 Agent", n: "传闻⑤ 指代消解 → 新湾储能（301901）", d: 'entity.resolve("上月的储能新股")' },
  { cls: "run", t: "资讯扫描器", n: "扫描睿驰半导体近 30 天资讯…", d: 'get_news("睿驰半导体") → 1 条' },
];
let fi = 0;
setInterval(() => {
  if (paused) return;
  const f = feed[fi++ % feed.length];
  const now = new Date();
  const el = document.createElement("div");
  el.className = "act " + f.cls;
  el.innerHTML =
    '<div class="at"><span>' + now.toTimeString().slice(0, 8) + "</span><span>" + f.t + "</span></div>" +
    '<div class="an">' + f.n + '</div>' +
    '<div class="ad" onclick="tg(this)">' + f.d + '</div>' +
    '<div class="full">' + f.d + "</div>";
  const list = document.getElementById("actList");
  list.prepend(el);
  while (list.children.length > 8) list.lastChild.remove();
}, 9000);
