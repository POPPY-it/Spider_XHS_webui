
"use strict";
const $ = (id) => document.getElementById(id);

/* ---------- 通用 ---------- */
function toast(msg, isErr) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  $("toasts").appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 250); }, 3200);
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    const err = (data && data.error) || (data && data.msg) || ("请求失败 " + res.status);
    const e = new Error(err); e.status = res.status; throw e;
  }
  return data;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtCount(n) {
  if (n == null) return "0";
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, "") + "万";
  return String(n);
}

/* ---------- Tab 切换 ---------- */
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "account") refreshAuth();
    if (btn.dataset.tab === "history") loadHistory();
    if (btn.dataset.tab === "talent") loadPgyStatus();
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "comment-analyze") loadCommentAnalysis();
  });
});
$("sidebar-account").addEventListener("click", () => {
  document.querySelector('.nav-item[data-tab="account"]').click();
});

/* ---------- 账号状态 ---------- */
async function refreshAuth() {
  try {
    const st = await api("/api/auth/status");
    const chipName = $("chip-name"), chipState = $("chip-state"), chipM = $("chip-medallion");
    const an = $("auth-name"), ar = $("auth-redid"), ab = $("auth-badge");
    if (st.valid && st.user) {
      const u = st.user;
      chipName.textContent = u.nickname || "已登录";
      chipState.textContent = "登录态有效 · 小红书";
      chipState.className = "state ok";
      if (u.avatar) chipM.innerHTML = `<img src="${esc(u.avatar)}" referrerpolicy="no-referrer" alt="">`;
      else chipM.textContent = (u.nickname || "书").slice(0, 1);
      an.textContent = u.nickname || "未知用户";
      ar.textContent = "ID " + (u.red_id || "-");
      ab.className = "badge ok"; ab.textContent = "登录有效";
      $("auth-avatar").innerHTML = u.avatar
        ? `<img src="${esc(u.avatar)}" referrerpolicy="no-referrer" alt="">` : (u.nickname || "书").slice(0, 1);
    } else {
      const reason = st.error || "未配置 Cookie";
      chipName.textContent = "未登录";
      chipState.textContent = "登录态失效";
      chipState.className = "state bad";
      chipM.textContent = "!";
      an.textContent = "登录态无效";
      ar.textContent = "";
      ab.className = "badge bad"; ab.textContent = "未登录";
      $("auth-avatar").textContent = "!";
      if (st.error) toast("登录态无效：" + reason, true);
    }
  } catch (e) { toast("读取登录态失败：" + e.message, true); }
}

/* ---------- 任务进度（采集 / 导出共用） ---------- */
function bindProgress(kind) {
  const P = {
    start: $(kind + "-start"), cancel: $(kind + "-cancel"),
    wrap: $(kind + "-progress"), label: $(kind + "-label"),
    count: $(kind + "-count"), fill: $(kind + "-fill"), log: $(kind + "-log"),
  };
  let pollTimer = null;
  let taskId = null;

  function setRunning(running) {
    P.start.disabled = running;
    P.wrap.style.display = running ? "block" : "none";
  }
  function render(t) {
    P.label.textContent = t.phase === "discover" ? "正在发现笔记…" : (t.kind === "crawl" ? "正在采集…" : "正在导出…");
    if (t.total > 0) {
      P.count.textContent = `${t.progress} / ${t.total}`;
      P.fill.style.width = Math.round(t.progress / t.total * 100) + "%";
    } else {
      P.count.textContent = "发现中…";
    }
    const box = P.log;
    box.innerHTML = t.log.map(l => {
      const cls = /✗|失败|错误/.test(l) ? " err" : (/✓|成功/.test(l) ? " ok" : "");
      return `<div class="line${cls}">${esc(l)}</div>`;
    }).join("");
    box.scrollTop = box.scrollHeight;
  }
  function poll() {
    pollTimer = setInterval(async () => {
      try {
        const t = await api("/api/tasks/" + taskId);
        render(t);
        if (t.status !== "running") {
          clearInterval(pollTimer); setRunning(false);
          if (t.status === "done" && t.result) {
            toast(kind === "crawl"
              ? `采集完成：成功 ${t.result.note_count} / ${t.result.total} 篇`
              : `导出完成：${t.result.note_count} 篇 → ${t.result.collection}`);
          } else if (t.status === "cancelled") {
            toast("任务已取消", true);
          } else if (t.status === "error") {
            toast("任务失败：" + (t.error || "未知错误"), true);
          }
        }
      } catch (e) { clearInterval(pollTimer); setRunning(false); toast("进度读取失败：" + e.message, true); }
    }, 1000);
  }
  P.cancel.addEventListener("click", async () => {
    try { await api("/api/tasks/" + taskId + "/cancel", { method: "POST" }); toast("已发送取消请求"); }
    catch (e) { toast(e.message, true); }
  });
  return { start: P.start, setRunning, begin: (id) => { taskId = id; render({phase:"discover",progress:0,total:0,log:[],kind}); setRunning(true); poll(); } };
}
const crawlP = bindProgress("crawl");
const exportP = bindProgress("export");

/* ---------- 采集 ---------- */
let crawlMode = "search";
document.querySelectorAll("#crawl-source .pill").forEach(p => p.addEventListener("click", () => {
  document.querySelectorAll("#crawl-source .pill").forEach(x => x.classList.remove("active"));
  p.classList.add("active"); crawlMode = p.dataset.mode;
  $("crawl-note-field").style.display = crawlMode === "note" ? "" : "none";
  $("crawl-user-field").style.display = crawlMode === "user" ? "" : "none";
  $("crawl-search-fields").style.display = crawlMode === "search" ? "" : "none";
}));
$("crawl-save").addEventListener("change", () => {
  $("crawl-excel-field").style.display = ["all", "excel"].includes($("crawl-save").value) ? "" : "none";
});
$("crawl-start").addEventListener("click", async () => {
  const body = { mode: crawlMode };
  if (crawlMode === "note") {
    if (!$("crawl-note-url").value.trim()) return toast("请填写笔记链接", true);
    body.note_url = $("crawl-note-url").value.trim();
  } else if (crawlMode === "user") {
    if (!$("crawl-user-url").value.trim()) return toast("请填写用户主页链接", true);
    body.user_url = $("crawl-user-url").value.trim();
  } else {
    if (!$("crawl-query").value.trim()) return toast("请填写搜索关键词", true);
    body.query = $("crawl-query").value.trim();
    body.require_num = parseInt($("crawl-num").value) || 10;
    body.sort_type_choice = parseInt($("crawl-sort").value);
    body.note_type = parseInt($("crawl-ntype").value);
    body.note_time = parseInt($("crawl-ntime").value);
  }
  body.save_choice = $("crawl-save").value;
  body.excel_name = $("crawl-excel").value.trim();
  try {
    const res = await api("/api/tasks/crawl", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    crawlP.begin(res.task_id);
  } catch (e) { toast(e.message, true); }
});
$("crawl-open-dir").addEventListener("click", async () => {
  try {
    const d = await api("/api/datas");
    const res = await api("/api/datas/open", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ path: d.excel_dir }) });
    toast("已在访达中打开 datas 目录");
  } catch (e) { toast(e.message, true); }
});

/* ---------- 导出 ---------- */
let exportMode = "search";
document.querySelectorAll("#export-source .pill").forEach(p => p.addEventListener("click", () => {
  document.querySelectorAll("#export-source .pill").forEach(x => x.classList.remove("active"));
  p.classList.add("active"); exportMode = p.dataset.mode;
  $("export-user-field").style.display = exportMode === "user" ? "" : "none";
  $("export-search-fields").style.display = exportMode === "search" ? "" : "none";
}));
$("export-start").addEventListener("click", async () => {
  const body = { mode: exportMode, include_comments: $("export-comments").checked };
  if (exportMode === "user") {
    if (!$("export-user-url").value.trim()) return toast("请填写用户主页链接", true);
    body.user_url = $("export-user-url").value.trim();
  } else {
    if (!$("export-query").value.trim()) return toast("请填写搜索关键词", true);
    body.query = $("export-query").value.trim();
    body.require_num = parseInt($("export-num").value) || 10;
  }
  body.collection = $("export-collection").value.trim();
  try {
    const res = await api("/api/tasks/export", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    exportP.begin(res.task_id);
  } catch (e) { toast(e.message, true); }
});

/* ---------- 浏览 ---------- */
function renderNote(note) {
  const c = $("browse-note-card");
  const type = note.note_type || "图集";
  let media = "";
  if (type === "视频" && note.video_addr) {
    media = `<div class="video-box"><video src="${esc(note.video_addr)}" controls preload="metadata" referrerpolicy="no-referrer"></video></div>`;
  } else if (note.image_list && note.image_list.length) {
    media = `<div class="img-grid">${note.image_list.map((u, i) =>
      `<img src="${esc(u)}" loading="lazy" referrerpolicy="no-referrer" alt="图${i + 1}">`).join("")}</div>`;
  }
  c.innerHTML = `
    <div class="card-title">笔记详情</div>
    <div class="note-detail">
      <div class="note-title">${esc(note.title || "无标题")}</div>
      <div class="note-meta">
        <span>作者 <b>${esc(note.nickname || "-")}</b></span>
        <span class="stat">♥ <b>${fmtCount(note.liked_count)}</b></span>
        <span class="stat">★ <b>${fmtCount(note.collected_count)}</b></span>
        <span class="stat">✎ <b>${fmtCount(note.comment_count)}</b></span>
        <span class="stat">↗ <b>${fmtCount(note.share_count)}</b></span>
        <span>${esc(note.upload_time || "")}</span>
        <span>${esc(note.ip_location || "")}</span>
        <span>${type}</span>
      </div>
      <div>${(note.tags || []).map(t => `<span class="tag">#${esc(t)}</span>`).join("")}</div>
      ${media}
      ${note.desc ? `<div class="note-desc">${esc(note.desc)}</div>` : ""}
    </div>
    <div class="comments" id="note-comments"></div>`;
  c.style.display = "";
  $("browse-user-card").style.display = "none";
}
function renderComments(comments) {
  const box = $("note-comments");
  if (!comments || !comments.length) { box.innerHTML = `<div class="empty">暂无评论</div>`; return; }
  box.innerHTML = `<div class="card-title" style="margin-top:18px">评论（${comments.length}）</div>` + comments.map(cm => {
    const avatar = cm.avatar
      ? `<img src="${esc(cm.avatar)}" referrerpolicy="no-referrer" alt="">`
      : (cm.nickname || "?").slice(0, 1);
    const replies = (cm.sub_comments || []).map(r => {
      const rn = (r.user_info && r.user_info.nickname) || "?";
      let rtime = "";
      if (r.create_time) { const d = new Date(r.create_time * 1000); rtime = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; }
      return `<div class="r"><b>${esc(rn)}</b>：${esc(r.content || "")} <span class="c-sub">${rtime} · 赞 ${r.like_count || 0}</span></div>`;
    }).join("");
    return `<div class="comment">
      <div class="c-avatar">${avatar}</div>
      <div style="flex:1">
        <div class="c-name">${esc(cm.nickname || "匿名")}</div>
        <div class="c-content">${esc(cm.content || "")}</div>
        <div class="c-sub">${esc(cm.upload_time || "")} · 赞 ${cm.like_count || 0} · ${esc(cm.ip_location || "")}</div>
        ${replies ? `<div class="c-replies">${replies}</div>` : ""}
      </div>
    </div>`;
  }).join("");
}
$("browse-note-btn").addEventListener("click", async () => {
  const url = $("browse-note-url").value.trim();
  if (!url) return toast("请填写笔记链接", true);
  const btn = $("browse-note-btn"); btn.disabled = true;
  try {
    const res = await api("/api/browse/note?url=" + encodeURIComponent(url));
    renderNote(res.note);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
});
$("browse-note-comments-btn").addEventListener("click", async () => {
  const url = $("browse-note-url").value.trim();
  if (!url) return toast("请先填写笔记链接", true);
  const btn = $("browse-note-comments-btn"); btn.disabled = true;
  try {
    const res = await api("/api/browse/note/comments?url=" + encodeURIComponent(url));
    renderComments(res.comments);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
});
$("browse-user-btn").addEventListener("click", async () => {
  const url = $("browse-user-url").value.trim();
  if (!url) return toast("请填写用户主页链接", true);
  const btn = $("browse-user-btn"); btn.disabled = true;
  try {
    const res = await api("/api/browse/user?url=" + encodeURIComponent(url));
    const u = res.user, notes = res.notes;
    const card = $("browse-user-card");
    card.innerHTML = `
      <div class="card-title">用户主页</div>
      <div class="user-card">
        <div class="user-avatar">${u.avatar ? `<img src="${esc(u.avatar)}" referrerpolicy="no-referrer" alt="">` : (u.nickname || "?").slice(0, 1)}</div>
        <div>
          <div class="user-name">${esc(u.nickname || "-")}</div>
          <div class="user-sub">${esc(u.red_id || "")} · ${esc(u.gender || "")} · ${esc(u.ip_location || "")}</div>
          <div class="user-stats">
            <span>粉丝 <b>${fmtCount(u.fans)}</b></span>
            <span>关注 <b>${fmtCount(u.follows)}</b></span>
            <span>获赞 <b>${fmtCount(u.interaction)}</b></span>
          </div>
          ${u.desc ? `<div class="user-sub" style="margin-top:6px">${esc(u.desc)}</div>` : ""}
        </div>
      </div>
      <div class="card-title">全部笔记（${notes.length}）</div>
      <div class="notes-grid">${notes.map(n => `
        <div class="note-cell" data-url="${esc(n.url)}">
          ${n.cover ? `<img class="cover" src="${esc(n.cover)}" loading="lazy" referrerpolicy="no-referrer" alt="">` : `<div class="cover" style="display:grid;place-items:center;color:var(--slate);font-size:11px">${esc(n.type)}</div>`}
          <div class="t">${esc(n.title || "无标题")}</div>
          <div class="s">♥ ${fmtCount(n.liked_count)} · ${esc(n.type)}</div>
        </div>`).join("")}</div>`;
    card.style.display = "";
    card.querySelectorAll(".note-cell").forEach(cell => cell.addEventListener("click", async () => {
      const nurl = cell.dataset.url;
      try {
        const r = await api("/api/browse/note?url=" + encodeURIComponent(nurl));
        renderNote(r.note);
        $("browse-note-url").value = nurl;
        window.scrollTo({ top: $("browse-note-card").offsetTop - 80, behavior: "smooth" });
      } catch (e) { toast(e.message, true); }
    }));
    $("browse-note-card").style.display = "none";
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
});

/* ---------- 账号 ---------- */
$("auth-save-cookie").addEventListener("click", async () => {
  const cookie = $("auth-cookie-input").value.trim();
  if (!cookie) return toast("请粘贴 Cookie", true);
  const btn = $("auth-save-cookie"); btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>验证中`;
  try {
    const res = await api("/api/auth/cookie", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ cookie }) });
    toast("已保存，当前账号：" + (res.nickname || "未知"));
    $("auth-cookie-input").value = "";
    await refreshAuth();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "保存并验证"; }
});

$("auth-import-chrome").addEventListener("click", async () => {
  const btn = $("auth-import-chrome"); btn.disabled = true; btn.textContent = "导入中…";
  try {
    const res = await api("/api/auth/import-chrome", { method: "POST" });
    toast("已从 Chrome 导入会话：" + (res.nickname || ""));
    await refreshAuth();
  } catch (e) { toast("导入失败：" + e.message, true); }
  finally { btn.disabled = false; btn.textContent = "从 Chrome 一键导入"; }
});

/* ---------- 扫码登录 ---------- */
let qrPollTimer = null;
async function startQr() {
  try {
    await api("/api/auth/qr/start", { method: "POST" });
    $("auth-qr-area").style.display = "block";
    $("auth-qr-start").style.display = "none";
    $("auth-qr-regen").style.display = "none";
    $("auth-qr-status").innerHTML = `<span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在初始化…`;
    pollQr();
  } catch (e) { toast(e.message, true); }
}
function pollQr() {
  clearInterval(qrPollTimer);
  qrPollTimer = setInterval(async () => {
    try {
      const st = await api("/api/auth/qr/status");
      if (st.state === "idle") { clearInterval(qrPollTimer); resetQr(); return; }
      if (st.state === "preparing") { $("auth-qr-status").innerHTML = `<span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在初始化设备…`; return; }
      if (st.state === "success") {
        clearInterval(qrPollTimer);
        $("auth-qr-status").innerHTML = `<span class="red">✓ 登录成功${st.nickname ? "：" + esc(st.nickname) : ""}</span>`;
        $("auth-qr-start").style.display = "";
        await refreshAuth();
        return;
      }
      if (st.state === "failed") {
        clearInterval(qrPollTimer);
        $("auth-qr-status").innerHTML = `<span class="red">✗ ${esc(st.error || "登录失败")}</span>`;
        $("auth-qr-regen").style.display = "";
        return;
      }
      // waiting_scan / waiting_confirm
      const msg = st.message || (st.state === "waiting_scan" ? "请用小红书 App 扫描二维码" : "请在手机上确认登录");
      $("auth-qr-status").textContent = msg;
      // 显示二维码图片：qr/start 后需等 preparing 结束才有真实二维码，轮询到就设置 src
      if (st.state === "waiting_scan" || st.state === "waiting_confirm") {
        const img = $("auth-qr-img");
        const src = "/api/auth/qr/image?t=" + Date.now();
        if (img.getAttribute("src") !== src) img.setAttribute("src", src);
      }
    } catch (e) { /* 服务未就绪时忽略 */ }
  }, 1000);
}
function resetQr() {
  $("auth-qr-area").style.display = "none";
  $("auth-qr-start").style.display = "";
  $("auth-qr-regen").style.display = "none";
  $("auth-qr-status").textContent = "";
}
$("auth-qr-start").addEventListener("click", startQr);
$("auth-qr-regen").addEventListener("click", startQr);

// 浏览器扫码登录（Playwright 真实浏览器，绕过设备安全验证风控）
$("auth-browser-login").addEventListener("click", async () => {
  const btn = $("auth-browser-login");
  const statusBox = $("auth-browser-status");
  btn.disabled = true; btn.textContent = "启动中…";
  statusBox.textContent = "正在打开浏览器窗口…";
  try {
    const r = await api("/api/auth/browser-login/start", { method: "POST" });
    // 轮询登录状态
    while (true) {
      await new Promise(res => setTimeout(res, 2000));
      const st = await api("/api/auth/browser-login/status");
      if (st.state === "success") {
        statusBox.innerHTML = `<span class="red">✓ ${esc(st.message)}</span>`;
        toast("登录成功，Cookie 已保存");
        refreshAuth();
        break;
      }
      if (st.state === "failed") {
        statusBox.innerHTML = `<span class="red">✗ ${esc(st.error || st.message)}</span>`;
        toast("浏览器登录失败", true);
        break;
      }
      if (st.state === "running") {
        statusBox.textContent = "请在浏览器窗口扫码登录…";
      }
      if (st.state === "idle") break;
    }
  } catch (e) {
    statusBox.innerHTML = `<span class="red">✗ ${esc(e.message)}</span>`;
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = "浏览器扫码登录（推荐）";
  }
});

/* ---------- 历史 ---------- */
async function loadHistory() {
  try {
    const d = await api("/api/datas");
    // 概览
    const hasData = d.excels.length || d.media_groups.length || d.exports.length;
    $("history-summary").style.display = hasData ? "" : "none";
    $("history-batch-bar").style.display = hasData ? "" : "none";
    $("history-stats").innerHTML = `
      <div class="stat"><b>${(d.talent_exports||[]).length}</b><span>达人导出</span></div>
      <div class="stat"><b>${d.excels.length}</b><span>Excel 表格</span></div>
      <div class="stat"><b>${d.media_groups.length}</b><span>博主媒体夹</span></div>
      <div class="stat"><b>${d.exports.length}</b><span>AI 导出集合</span></div>`;

    // 达人导出（蒲公英）
    const teCard = $("history-talent-export-card");
    const teBox = $("history-talent-exports");
    const teList = d.talent_exports || [];
    if (teList.length) {
      teCard.style.display = "";
      teBox.innerHTML = `<div class="h-list">` + teList.map(x => `
        <div class="h-item" data-path="${esc(x.path)}">
          <input type="checkbox" class="batch-cb" value="${esc(x.path)}">
          <div class="icon">★</div>
          <div class="name">${esc(x.name)}${x.has_json ? `<span class="talent-json-tag">含完整数据</span>` : ""}</div>
          <div class="meta">${x.time} · ${(x.size/1024).toFixed(0)} KB</div>
          <button class="open">详情</button>
          <button class="open" data-json="${esc(x.json_path || '')}">完整数据</button>
          <button class="delete">删除</button>
        </div>`).join("") + `</div>`;
      teBox.querySelectorAll(".h-item").forEach(item => {
        item.addEventListener("click", (ev) => {
          if (ev.target.closest(".open") || ev.target.closest(".delete") || ev.target.closest(".batch-cb") || historyBatchMode) return;
          openExcel(item.dataset.path);
        });
        item.querySelector(".open").addEventListener("click", () => openExcel(item.dataset.path));
        const jsonBtn = item.querySelector('.open[data-json]');
        if (jsonBtn) jsonBtn.addEventListener("click", () => openJsonViewer(jsonBtn.dataset.json));
        item.querySelector(".delete").addEventListener("click", () => deletePath(item.dataset.path));
      });
    } else {
      teCard.style.display = "none";
    }
    // Excel
    const exBox = $("history-excels");
    if (!d.excels.length) { exBox.innerHTML = `<div class="h-empty">还没有保存过 Excel，去「采集」页跑一次吧</div>`; }
    else {
      exBox.innerHTML = `<div class="h-list">` + d.excels.map(e => `
        <div class="h-item" data-path="${esc(e.path)}">
          <input type="checkbox" class="batch-cb" value="${esc(e.path)}">
          <div class="icon">▦</div>
          <div class="name">${esc(e.name)}</div>
          <div class="meta">${e.time} · ${(e.size/1024).toFixed(0)} KB</div>
          <button class="open">详情</button>
          <button class="delete">删除</button>
        </div>`).join("") + `</div>`;
      exBox.querySelectorAll(".h-item").forEach(item => {
        item.addEventListener("click", (ev) => {
          if (ev.target.closest(".open") || ev.target.closest(".delete") || ev.target.closest(".batch-cb") || historyBatchMode) return;
          openExcel(item.dataset.path);
        });
        item.querySelector(".open").addEventListener("click", () => openExcel(item.dataset.path));
        item.querySelector(".delete").addEventListener("click", () => deletePath(item.dataset.path));
      });
    }
    // 媒体
    const mdBox = $("history-media");
    if (!d.media_groups.length) { mdBox.innerHTML = `<div class="h-empty">还没有下载过媒体文件</div>`; }
    else {
      mdBox.innerHTML = `<div class="h-list">` + d.media_groups.map(m => `
        <div class="h-item" data-path="${esc(m.path)}">
          <input type="checkbox" class="batch-cb" value="${esc(m.path)}">
          <div class="icon">◫</div>
          <div class="name">${esc(m.name)}</div>
          <div class="meta">${m.time} · ${m.note_count} 篇</div>
          <button class="open">打开文件夹</button>
          <button class="delete">删除</button>
        </div>`).join("") + `</div>`;
      mdBox.querySelectorAll(".h-item").forEach(item => {
        item.addEventListener("click", (ev) => {
          if (ev.target.closest(".open") || ev.target.closest(".delete") || ev.target.closest(".batch-cb") || historyBatchMode) return;
          openInFinder(item.dataset.path);
        });
        item.querySelector(".open").addEventListener("click", () => openInFinder(item.dataset.path));
        item.querySelector(".delete").addEventListener("click", () => deletePath(item.dataset.path));
      });
    }
    // 导出
    const ex2Box = $("history-exports");
    if (!d.exports.length) { ex2Box.innerHTML = `<div class="h-empty">还没有 AI 导出，去「导出」页跑一次吧</div>`; }
    else {
      ex2Box.innerHTML = `<div class="h-list">` + d.exports.map(x => `
        <div class="h-item" data-path="${esc(x.path)}">
          <input type="checkbox" class="batch-cb" value="${esc(x.path)}">
          <div class="icon">⇪</div>
          <div class="name">${esc(x.name)}</div>
          <div class="meta">${x.time} · ${x.md_count} 篇 Markdown${x.jsonl ? " · JSONL" : ""}</div>
          <button class="open">打开文件夹</button>
          <button class="delete">删除</button>
        </div>`).join("") + `</div>`;
      ex2Box.querySelectorAll(".h-item").forEach(item => {
        item.addEventListener("click", (ev) => {
          if (ev.target.closest(".open") || ev.target.closest(".delete") || ev.target.closest(".batch-cb") || historyBatchMode) return;
          openInFinder(item.dataset.path);
        });
        item.querySelector(".open").addEventListener("click", () => openInFinder(item.dataset.path));
        item.querySelector(".delete").addEventListener("click", () => deletePath(item.dataset.path));
      });
    }
    // 热点分析
    const hsBox = $("history-hotspot");
    if (!d.hotspot_tasks || !d.hotspot_tasks.length) { hsBox.innerHTML = `<div class="h-empty">还没有热点分析记录，去「热点分析」栏目跑一次吧</div>`; }
    else {
      hsBox.innerHTML = `<div class="h-list">` + d.hotspot_tasks.map(x => `
        <div class="h-item" data-path="${esc(x.path)}">
          <div class="icon">◉</div>
          <div class="name">${esc(x.query || ("任务 " + x.task_id))}（${x.note_count} 条）</div>
          <div class="meta">${x.time} · ${x.has_analysis ? '<span style="color:var(--red)">📄 有 AI 报告</span>' : "仅采集"}</div>
          <button class="open">打开文件夹</button>
          <button class="report" ${x.has_analysis ? "" : "disabled"}>查看报告</button>
          <button class="delete">删除</button>
        </div>`).join("") + `</div>`;
      hsBox.querySelectorAll(".h-item").forEach(item => {
        item.addEventListener("click", (ev) => {
          if (ev.target.closest(".open") || ev.target.closest(".report") || ev.target.closest(".delete") || historyBatchMode) return;
          openInFinder(item.dataset.path);
        });
        item.querySelector(".open").addEventListener("click", () => openInFinder(item.dataset.path));
        const reportBtn = item.querySelector(".report");
        reportBtn.addEventListener("click", async () => {
          const taskId = item.dataset.path.split("/").pop();
          try {
            const res = await api("/api/hotspot/tasks/" + encodeURIComponent(taskId) + "/analysis");
            if (!res.ready) { toast("该任务还没有 AI 报告，请在「热点分析」页触发分析"); return; }
            showHsReport(taskId, res.content);
          } catch (e) { toast("加载报告失败：" + e.message, true); }
        });
        item.querySelector(".delete").addEventListener("click", () => deletePath(item.dataset.path));
      });
    }
  } catch (e) { toast("加载历史失败：" + e.message, true); }
}

/* 历史里查看热点分析报告（抽屉） */
function showHsReport(taskId, content) {
  $("hs-note-detail").style.display = "flex";
  setDrawerBackdrop(true);
  $("hs-note-detail-title").textContent = "热点分析报告";
  renderHsReportInto($("hs-note-detail-body"), content);
}

async function openInFinder(path) {
  try { await api("/api/datas/open", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ path }) }); }
  catch (e) { toast(e.message, true); }
}

async function deletePath(path) {
  if (!confirm("确定删除这个文件/文件夹吗？此操作不可恢复。")) return;
  try {
    await api("/api/datas/delete", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ path }) });
    toast("已删除");
    loadHistory();   // 刷新历史列表
  } catch (e) { toast(e.message, true); }
}

/* ---------- 历史批量删除 ---------- */
let historyBatchMode = false;

function setBatchMode(on) {
  historyBatchMode = on;
  const active = $("history-batch-active");
  const startBtn = $("history-batch-start");
  active.style.display = on ? "" : "none";
  startBtn.style.display = on ? "none" : "";
  document.querySelectorAll(".h-item").forEach(item => {
    item.classList.toggle("batch-mode", on);
    if (!on) item.classList.remove("batch-selected");
    const cb = item.querySelector(".batch-cb");
    if (cb) cb.checked = false;
  });
  updateBatchCount();
}

function updateBatchCount() {
  const n = document.querySelectorAll(".h-item .batch-cb:checked").length;
  $("history-batch-count").textContent = `已选 ${n} 项`;
}

$("history-batch-start").addEventListener("click", () => setBatchMode(true));
$("history-batch-cancel").addEventListener("click", () => setBatchMode(false));
$("history-batch-selectall").addEventListener("click", () => {
  document.querySelectorAll(".h-item .batch-cb").forEach(cb => { cb.checked = true; cb.closest(".h-item").classList.add("batch-selected"); });
  updateBatchCount();
});
$("history-batch-invert").addEventListener("click", () => {
  document.querySelectorAll(".h-item .batch-cb").forEach(cb => {
    cb.checked = !cb.checked;
    cb.closest(".h-item").classList.toggle("batch-selected", cb.checked);
  });
  updateBatchCount();
});
$("history-batch-delete").addEventListener("click", async () => {
  const paths = [...document.querySelectorAll(".h-item .batch-cb:checked")].map(cb => cb.value);
  if (!paths.length) return toast("请先勾选要删除的项目", true);
  if (!confirm(`确定删除选中的 ${paths.length} 个项目吗？此操作不可恢复。`)) return;
  let ok = 0, fail = 0;
  for (const p of paths) {
    try { await api("/api/datas/delete", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ path: p }) }); ok++; }
    catch (e) { fail++; }
  }
  toast(`删除完成：成功 ${ok} 个${fail ? `，失败 ${fail} 个` : ""}`);
  setBatchMode(false);
  loadHistory();
});

// 勾选/取消时更新选中状态
document.addEventListener("change", (ev) => {
  if (ev.target.classList && ev.target.classList.contains("batch-cb")) {
    ev.target.closest(".h-item").classList.toggle("batch-selected", ev.target.checked);
    updateBatchCount();
  }
});

let currentExcelPath = "";
async function openExcel(path) {
  currentExcelPath = path;
  $("detail-title").textContent = path.split("/").pop();
  $("history-detail").style.display = "flex";
  setDrawerBackdrop(true);
  $("detail-body").innerHTML = `<div class="empty"><span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在读取…</div>`;
  try {
    const r = await api("/api/datas/excel?path=" + encodeURIComponent(path));
    renderExcelRows(r);
  } catch (e) {
    $("detail-body").innerHTML = `<div class="empty">读取失败：${esc(e.message)}</div>`;
  }
}

// 在历史抽屉里查看达人完整数据 JSON
async function openJsonViewer(jsonPath) {
  if (!jsonPath) return toast("该导出没有完整数据文件", true);
  currentExcelPath = jsonPath;
  $("detail-title").textContent = jsonPath.split("/").pop();
  $("history-detail").style.display = "flex";
  setDrawerBackdrop(true);
  $("detail-body").innerHTML = `<div class="empty"><span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在读取完整数据…</div>`;
  try {
    const rr = await api("/api/datas/json?path=" + encodeURIComponent(jsonPath));
    renderJsonViewer(rr);
  } catch (e) {
    $("detail-body").innerHTML = `<div class="empty">读取失败：${esc(e.message)}</div>`;
  }
}
function renderJsonViewer(r) {
  const body = $("detail-body");
  if (!r.success) { body.innerHTML = `<div class="empty">读取失败：${esc(r.error || "")}</div>`; return; }
  // 新格式：{creators, notes}
  const data = r.data || {};
  const creators = Array.isArray(data) ? data : (data.creators || []);
  const notes = (data.notes || []).length;
  if (!creators.length) { body.innerHTML = `<div class="empty">没有达人数据</div>`; return; }
  body.innerHTML = `<div class="detail-tools">
      <input type="text" id="detail-search" placeholder="搜索达人昵称…">
      <span style="font-size:12px;color:var(--mute)">共 ${creators.length} 位达人 · ${notes} 篇笔记</span>
    </div>
    <div id="detail-cards">${creators.map((t, i) => {
      return `<div class="note-card">
        <div class="nc-head">
          <span class="caret">▶</span>
          <div class="nc-title">${esc(t.nickname || "（未知达人）")}</div>
          <div class="nc-meta">粉丝 ${esc(fmtNum(t.fans))}${t.median_read ? '<span class="t">含中位数</span>' : ""}</div>
        </div>
        <div class="nc-body">
          <div class="nc-stats">
            <span>粉丝 <b>${esc(fmtNum(t.fans))}</b></span>
            <span>阅读中位 <b>${esc(fmtNum(t.median_read))}</b></span>
            <span>互动中位 <b>${esc(fmtNum(t.median_interaction))}</b></span>
          </div>
          <div class="nc-desc" style="font-size:12px">${esc(t.ipLocation || "")} · ${esc((t.tags||[]).join("、") || "无标签")}</div>
          <div class="nc-links"><a href="${esc(t.profileUrl || '#')}" target="_blank" rel="noopener">达人主页 ↗</a></div>
        </div>
      </div>`;
    }).join("")}</div>`;
  // 折叠交互
  document.querySelectorAll("#detail-cards .note-card .nc-head").forEach(head => {
    head.addEventListener("click", () => head.closest(".note-card").classList.toggle("open"));
  });
  // 搜索
  $("detail-search").addEventListener("input", (ev) => {
    const q = ev.target.value.toLowerCase();
    document.querySelectorAll("#detail-cards .note-card").forEach(card => {
      card.style.display = card.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });
}
function renderExcelRows(r) {
  const body = $("detail-body");
  const rows = r.rows || [];
  if (!rows.length) { body.innerHTML = `<div class="empty">表格是空的</div>`; return; }
  const cards = rows.map((row, i) => {
    const title = row["标题"] || "无标题";
    const nick = row["昵称"] || "-";
    const type = row["笔记类型"] || "图集";
    const liked = row["点赞数量"] || "0";
    const collected = row["收藏数量"] || "0";
    const comments = row["评论数量"] || "0";
    const desc = row["描述"] || "";
    const time = row["上传时间"] || "";
    const url = row["笔记url"] || "";
    const imgList = row["图片地址url列表"] || "";
    const imgs = imgList ? imgList.split("','").map(s => s.replace(/^\[['"]?|['"]?\]$/g, "").trim()).filter(Boolean) : [];
    const imgsHtml = imgs.length ? `<div class="nc-imgs">${imgs.map(u => `<img src="${esc(u)}" loading="lazy" referrerpolicy="no-referrer" alt="">`).join("")}</div>` : "";
    const video = row["视频地址url"] || "";
    return `
    <div class="note-card">
      <div class="nc-head">
        <span class="caret">▶</span>
        <div class="nc-title">${esc(title)}</div>
        <div class="nc-meta">${esc(nick)}<span class="t">${esc(type)}</span></div>
      </div>
      <div class="nc-body">
        <div class="nc-stats">
          <span>点赞 <b>${esc(fmtCount(+liked))}</b></span>
          <span>收藏 <b>${esc(fmtCount(+collected))}</b></span>
          <span>评论 <b>${esc(fmtCount(+comments))}</b></span>
          <span>${esc(time)}</span>
        </div>
        ${desc ? `<div class="nc-desc">${esc(desc)}</div>` : ""}
        ${imgsHtml}
        ${video && video !== "None" ? `<div class="nc-links">视频：<a href="${esc(video)}" target="_blank" rel="noopener" referrerpolicy="no-referrer">${esc(video.slice(0, 80))}…</a></div>` : ""}
        ${url ? `<div class="nc-links">原文：<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a></div>` : ""}
      </div>
    </div>`;
  }).join("");
  body.innerHTML = `
    <div class="detail-tools">
      <input type="text" id="detail-search" placeholder="搜索标题 / 作者…">
      <button class="btn btn-ghost" id="detail-expand">全部展开</button>
    </div>
    <div id="detail-cards">${cards}</div>`;
  // 搜索
  $("detail-search").addEventListener("input", (ev) => {
    const q = ev.target.value.toLowerCase();
    document.querySelectorAll("#detail-cards .note-card").forEach(card => {
      const text = card.textContent.toLowerCase();
      card.style.display = text.includes(q) ? "" : "none";
    });
  });
  // 展开/收起
  document.querySelectorAll("#detail-cards .note-card .nc-head").forEach(head => {
    head.addEventListener("click", () => head.closest(".note-card").classList.toggle("open"));
  });
  $("detail-expand").addEventListener("click", () => {
    const all = document.querySelectorAll("#detail-cards .note-card");
    const anyOpen = all.length > 0 && all[0].classList.contains("open");
    all.forEach(c => c.classList.toggle("open", !anyOpen));
  });
}
$("detail-close").addEventListener("click", () => { $("history-detail").style.display = "none"; setDrawerBackdrop(false); });
$("detail-open-btn").addEventListener("click", () => { if (currentExcelPath) openInFinder(currentExcelPath); });

/* ---------- 达人（蒲公英） ---------- */
let pgyCategoryTree = [];        // 类目树，供筛选
let pgySelectedTags = [];        // 已选类目（一级或二级）
let pgyTalents = [];             // 当前搜索结果
let hideDownloaded = false;      // 只看新达人（隐藏已导出过的）

async function loadPgyStatus() {
  try {
    const s = await api("/api/pgy/status");
    const nameBox = $("pgy-cookie-status");
    const subBox = $("pgy-cookie-sub");
    const avatar = $("pgy-account-avatar");
    const editBox = $("pgy-cookie-edit");
    if (s.valid) {
      nameBox.innerHTML = `<span class="dot"></span>${esc(s.nickname || "蒲公英账号")}`;
      subBox.textContent = "蒲公英账号已连接 · Cookie 保存于本机";
      avatar.textContent = (s.nickname || "客").trim()[0];
      $("pgy-filter-card").style.display = "";
      $("pgy-cookie-toggle").textContent = "更换 Cookie";
      loadPgyCategories();
    } else {
      nameBox.innerHTML = `<span class="dot bad"></span>未连接`;
      subBox.textContent = s.saved ? (s.error || "Cookie 无效，请更换") : "请粘贴蒲公英 Cookie 完成连接";
      avatar.textContent = "◉";
      $("pgy-filter-card").style.display = "none";
      $("pgy-results-card").style.display = "none";
      $("pgy-cookie-toggle").textContent = "配置 Cookie";
    }
    // 无论状态如何，编辑框保持关闭
    editBox.style.display = "none";
  } catch (e) {
    $("pgy-cookie-status").textContent = "检查失败";
    $("pgy-cookie-sub").textContent = e.message;
  }
}

async function loadPgyCategories() {
  try {
    const d = await api("/api/pgy/categories");
    pgyCategoryTree = d.tree || [];
    const tabsBox = $("pgy-tabs");
    // 一级类目 = 页签
    tabsBox.innerHTML = pgyCategoryTree.map((first, fi) => {
      const subCount = (first.taxonomy2Tags || []).length;
      const name = esc(String(first.taxonomy1Tag || fi));
      return `<button type="button" class="pgy-tab${fi === 0 ? " active" : ""}" data-fi="${fi}">${name}<span class="cnt">${subCount}</span></button>`;
    }).join("") || `<div class="empty">没有类目数据</div>`;

    // 点击页签：切换激活状态 + 渲染该一级类目的子类目面板
    const renderPanel = (fi) => {
      const first = pgyCategoryTree[fi];
      const label = $("pgy-panel-label");
      const cats = $("pgy-panel-cats");
      if (!first) return;
      label.textContent = `${first.taxonomy1Tag || "类目"} · 点击类目选中，再点取消（可多选）`;
      const allKey = String(fi);
      const allChecked = pgySelectedTags.includes(allKey) ? " checked" : "";
      const subEls = (first.taxonomy2Tags || []).map((tag, si) => {
        const key = `${fi}-${si}`;
        const checked = pgySelectedTags.includes(key) ? " checked" : "";
        return `<button type="button" class="pgy-cat${checked}" data-key="${key}">${esc(String(tag))}</button>`;
      }).join("");
      cats.innerHTML = `<button type="button" class="pgy-cat${allChecked}" data-key="${allKey}">整个「${esc(String(first.taxonomy1Tag || fi))}」</button>` + (subEls || `<span style="font-size:12px;color:var(--mute)">该一级类目下暂无子类目</span>`);
      // 点击胶囊：切换选中态（变色）
      cats.querySelectorAll(".pgy-cat").forEach(cat => {
        cat.addEventListener("click", () => {
          const key = cat.dataset.key;
          const idx = pgySelectedTags.indexOf(key);
          if (idx < 0) { pgySelectedTags.push(key); cat.classList.add("checked"); }
          else { pgySelectedTags.splice(idx, 1); cat.classList.remove("checked"); }
        });
      });
    };
    tabsBox.querySelectorAll(".pgy-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        tabsBox.querySelectorAll(".pgy-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        renderPanel(+tab.dataset.fi);
        $("pgy-panel").scrollTop = 0;   // 切页签回到顶部
      });
    });

    // 默认展示第一个类目的子类目
    renderPanel(0);
  } catch (e) {
    $("pgy-tabs").innerHTML = `<div class="empty">类目加载失败：${esc(e.message)}</div>`;
  }
}

$("pgy-cookie-toggle").addEventListener("click", () => {
  const edit = $("pgy-cookie-edit");
  edit.style.display = edit.style.display === "none" ? "" : "none";
});

$("pgy-cookie-cancel").addEventListener("click", () => {
  $("pgy-cookie-edit").style.display = "none";
  $("pgy-cookie-input").value = "";
});

$("pgy-cookie-save").addEventListener("click", async () => {
  const cookie = $("pgy-cookie-input").value.trim();
  if (!cookie) return toast("请先粘贴蒲公英 Cookie", true);
  const btn = $("pgy-cookie-save"); btn.disabled = true; btn.textContent = "验证中…";
  try {
    const r = await api("/api/pgy/cookie", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ cookie }) });
    toast(`蒲公英账号已连接：${r.nickname || ""}`);
    $("pgy-cookie-input").value = "";
    $("pgy-cookie-edit").style.display = "none";
    await loadPgyStatus();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = "保存并验证";
  }
});

$("pgy-clear").addEventListener("click", () => {
  $("pgy-fans-min").value = ""; $("pgy-fans-max").value = "";
  $("pgy-gender").value = ""; $("pgy-feature-tags").value = "";
  document.querySelectorAll("#pgy-panel-cats .pgy-cat").forEach(cat => cat.classList.remove("checked"));
  pgySelectedTags = [];
  $("pgy-summary").textContent = "";
});

$("pgy-search").addEventListener("click", async () => {
  const fansMin = $("pgy-fans-min").value ? Math.round(+$("pgy-fans-min").value * 10000) : undefined;
  const fansMax = $("pgy-fans-max").value ? Math.round(+$("pgy-fans-max").value * 10000) : undefined;
  const params = new URLSearchParams();
  if (fansMin !== undefined) params.set("fans_min", fansMin);
  if (fansMax !== undefined) params.set("fans_max", fansMax);
  if ($("pgy-gender").value) params.set("gender", $("pgy-gender").value);
  if ($("pgy-feature-tags").value.trim()) params.set("feature_tags", $("pgy-feature-tags").value.trim());
  if ($("pgy-pages").value) params.set("max_pages", +$("pgy-pages").value || 5);
  // 类目 -> 用后端 generate_pugongying_data 兼容的 contentTag
  if (pgySelectedTags.length) {
    // 后端接收逗号分隔的类目选择 key（如 1 或 1-2）
    const catKeys = pgySelectedTags.map(k => pgyCategoryTree[+k.split("-")[0]] ? k : k);
    params.set("content_tags", catKeys.join(","));
  }
  const btn = $("pgy-search"); btn.disabled = true; btn.textContent = "搜索中…";
  $("pgy-summary").textContent = "正在从蒲公英获取达人…";
  try {
    const r = await api("/api/pgy/search?" + params.toString());
    pgyTalents = r.talents || [];
    $("pgy-summary").textContent = r.total !== undefined ? `共匹配 ${r.total} 位达人，已加载 ${pgyTalents.length} 位，正在抓取阅读/互动中位数…` : "";
    $("pgy-export").disabled = !pgyTalents.length;
    $("pgy-export-db").disabled = !pgyTalents.length;
    renderPgyTalents();
    // 搜索完成后自动抓取中位数
    if (pgyTalents.length) runMedianTask();
  } catch (e) {
    $("pgy-summary").textContent = "";
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = "开始筛选";
  }
});

// 后台抓取阅读/互动中位数，进度条实时显示
async function runMedianTask() {
  const prog = $("pgy-median-progress");
  const fill = $("pgy-mp-fill");
  const count = $("pgy-mp-count");
  const label = $("pgy-mp-label");
  prog.style.display = "";
  label.textContent = "正在启动中位数抓取任务…";
  fill.style.width = "0%";
  try {
    const r = await api("/api/pgy/enrich-median", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ talents: pgyTalents }) });
    const taskId = r.task_id;
    // 轮询任务进度
    while (true) {
      await new Promise(res => setTimeout(res, 1000));
      const t = await api("/api/tasks/" + taskId);
      if (t.total > 0) {
        const pct = Math.round(t.progress / t.total * 100);
        fill.style.width = pct + "%";
        count.textContent = `${t.progress}/${t.total}`;
        label.textContent = `抓取中位数中… ${pct}%`;
      }
      if (t.status === "done") {
        fill.style.width = "100%";
        pgyTalents = (t.result && t.result.talents) || pgyTalents;
        applyPgySort();
        renderPgyTalents();
        const got = t.result ? t.result.got : 0;
        label.textContent = `完成：已获取 ${got}/${t.result.total} 位达人的阅读/互动中位数`;
        count.textContent = "";
        $("pgy-summary").textContent = `共匹配 ${t.result.total} 位达人 · 已获取 ${got} 位中位数`;
        toast("阅读/互动中位数已获取，可导出 Excel");
        break;
      }
      if (t.status === "error") {
        label.textContent = "中位数抓取失败";
        toast(t.error || "中位数抓取失败", true);
        break;
      }
    }
  } catch (e) {
    label.textContent = "启动失败";
    toast(e.message, true);
  } finally {
    setTimeout(() => { prog.style.display = "none"; }, 5000);
  }
}

// 排序：本地按字段重排 pgyTalents
function applyPgySort() {
  const sortVal = $("pgy-sort").value;
  if (sortVal === "comprehensiverank") return; // 保持蒲公英综合排名顺序
  const key = sortVal;
  const asc = key.endsWith("_asc");
  const field = asc ? key.slice(0, -4) : key;
  const getVal = (t) => {
    switch (field) {
      case "fans": return Number(t.fansNum ?? t.fansCount ?? 0);
      case "pic_price": return Number(t.picturePrice ?? 0);
      case "video_price": return Number(t.videoPrice ?? 0);
      case "read_median": return Number(t.median_read ?? 0);
      case "inter_median": return Number(t.median_interaction ?? 0);
      default: return 0;
    }
  };
  pgyTalents.sort((a, b) => {
    const diff = getVal(b) - getVal(a);
    return asc ? -diff : diff;
  });
}

$("pgy-sort").addEventListener("change", () => {
  if (!pgyTalents.length) return;
  applyPgySort();
  renderPgyTalents();
});

$("pgy-hide-downloaded").addEventListener("change", (ev) => {
  hideDownloaded = ev.target.checked;
  renderPgyTalents();
});

// 已下载记录管理
$("pgy-manage-downloaded").addEventListener("click", loadDownloadedModal);

async function loadDownloadedModal() {
  const mask = $("pgy-dl-modal");
  mask.style.display = "flex";
  const list = $("pgy-dl-list");
  list.innerHTML = `<div class="pgy-dl-empty">正在加载…</div>`;
  try {
    const d = await api("/api/pgy/downloaded");
    renderDownloadedList(d.items || [], d.count || 0);
  } catch (e) {
    list.innerHTML = `<div class="pgy-dl-empty">加载失败：${esc(e.message)}</div>`;
  }
}

function renderDownloadedList(items, count) {
  const list = $("pgy-dl-list");
  $("pgy-dl-count").textContent = `共 ${count} 条`;
  if (!items.length) {
    list.innerHTML = `<div class="pgy-dl-empty">还没有已下载记录</div>`;
    return;
  }
  list.innerHTML = items.map(it => `
    <label class="pgy-dl-item">
      <input type="checkbox" value="${esc(it.user_id)}">
      <span class="dl-name">${esc(it.name || "（未知达人）")}</span>
      <span class="dl-time">${esc(it.downloaded_at || "")}</span>
    </label>`).join("");
}

$("pgy-dl-close").addEventListener("click", () => { $("pgy-dl-modal").style.display = "none"; });
// 点击遮罩关闭
$("pgy-dl-modal").addEventListener("click", (ev) => { if (ev.target === $("pgy-dl-modal")) $("pgy-dl-modal").style.display = "none"; });

$("pgy-dl-selectall").addEventListener("click", () => {
  document.querySelectorAll("#pgy-dl-list input").forEach(cb => cb.checked = true);
});
$("pgy-dl-invert").addEventListener("click", () => {
  document.querySelectorAll("#pgy-dl-list input").forEach(cb => cb.checked = !cb.checked);
});
$("pgy-dl-remove").addEventListener("click", async () => {
  const ids = [...document.querySelectorAll("#pgy-dl-list input:checked")].map(cb => cb.value);
  if (!ids.length) return toast("请先勾选要删除的记录", true);
  if (!confirm(`确定删除选中的 ${ids.length} 条已下载记录吗？`)) return;
  try {
    const r = await api("/api/pgy/downloaded/remove", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ user_ids: ids }) });
    toast(`已删除 ${r.removed} 条记录`);
    // 刷新列表，同时刷新卡片上的已下载标记
    await loadDownloadedModal();
    await refreshDownloadedFlag();
  } catch (e) { toast(e.message, true); }
});

$("pgy-dl-clearall").addEventListener("click", async () => {
  if (!confirm("确定清空全部已下载记录吗？此操作不可恢复。")) return;
  try {
    await api("/api/pgy/downloaded/reset", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({}) });
    toast("已清空全部记录");
    await loadDownloadedModal();
    await refreshDownloadedFlag();
  } catch (e) { toast(e.message, true); }
});

// 重新拉取已下载标记并重渲染卡片
async function refreshDownloadedFlag() {
  if (!pgyTalents.length) return;
  try {
    const d = await api("/api/pgy/downloaded");
    const set = new Set((d.items || []).map(it => it.user_id));
    pgyTalents.forEach(t => { t.downloaded = set.has(t.userId || t.id); });
    renderPgyTalents();
  } catch (e) {}
}

function renderPgyTalents() {
  const box = $("pgy-results-card");
  if (!pgyTalents.length) {
    $("pgy-results").innerHTML = `<div class="empty"><div style="font-size:26px;margin-bottom:8px">🎯</div>没有匹配的达人<br><span style="font-size:12px;color:var(--mute)">试试放宽粉丝数区间，或减少勾选的类目</span></div>`;
  } else {
    const totalCount = pgyTalents.length;
    const shownCount = hideDownloaded ? pgyTalents.filter(t => !t.downloaded).length : totalCount;
    $("pgy-count").textContent = hideDownloaded ? `${shownCount} 位新达人 / 共 ${totalCount} 位` : `${totalCount} 位`;
    $("pgy-results").innerHTML = pgyTalents.map((t, i) => {
      const nick = t.name || t.nickname || "达人";
      const fans = fmtNum(t.fansNum ?? t.fansCount);
      const pic = fmtPrice(t.picturePrice);
      const vid = fmtPrice(t.videoPrice);
      const tags = (t.personalTags || []).slice(0, 6);
      const loc = t.location || "";
      const avatar = t.headPhoto || t.avatar || t.image || "";
      const userId = t.userId || t.id || "";
      const gender = t.gender === "女" ? "♀" : t.gender === "男" ? "♂" : "";
      const hasMedian = t.median_read !== null && t.median_read !== undefined;
      const medRead = hasMedian ? fmtNum(t.median_read) : null;
      const medInter = hasMedian ? fmtNum(t.median_interaction) : null;
      const done = !!t.downloaded;
      if (hideDownloaded && done) return "";
      const badge = done ? `<span class="pgy-card-badge done">已导出</span>` : "";
      return `<div class="pgy-card">${badge}
        <div class="pgy-card-head">
          <div class="pgy-card-avatar">${avatar ? `<img src="${esc(avatar)}" referrerpolicy="no-referrer" alt="">` : esc((nick||"客").trim()[0])}</div>
          <div style="flex:1;min-width:0">
            <div class="pgy-card-name">${esc(nick)}${gender ? `<span class="tag-chip">${gender}</span>` : ""}</div>
            <div class="pgy-card-redid">${t.redId ? "@" + esc(t.redId) : esc(userId)}</div>
          </div>
        </div>
        <div class="pgy-card-stats">
          <div class="pgy-card-stat"><div class="v">${esc(fans)}</div><div class="k">粉丝</div></div>
          <div class="pgy-card-stat"><div class="v">${esc(pic)}</div><div class="k">图文报价</div></div>
          <div class="pgy-card-stat"><div class="v">${esc(vid)}</div><div class="k">视频报价</div></div>
        </div>
        ${hasMedian ? `<div class="pgy-card-median">
          <div class="pgy-card-stat"><div class="v">${esc(medRead)}</div><div class="k">阅读中位数</div></div>
          <div class="pgy-card-stat"><div class="v">${esc(medInter)}</div><div class="k">互动中位数</div></div>
        </div>` : ""}
        <div class="pgy-card-loc">${loc ? `<span class="pin">📍</span>${esc(loc)}` : ""}</div>
        <div class="pgy-card-tags">${tags.map(tg => `<span class="t">${esc(tg)}</span>`).join("")}</div>
        <div class="pgy-card-foot">
          <div class="pgy-card-price">图文 <b>${esc(pic)}</b> 元 · 视频 <b>${esc(vid)}</b> 元</div>
          <button class="btn btn-ghost pgy-detail-btn" data-i="${i}">看数据 <span class="arr">→</span></button>
        </div>
      </div>`;
    }).join("");
    box.querySelectorAll(".pgy-detail-btn").forEach(b => b.addEventListener("click", () => {
      const t = pgyTalents[+b.dataset.i];
      openPgyDetail(t.userId || t.id || "");
    }));
  }
  box.style.display = "";
}

function fmtNum(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return esc(String(v));
  if (n >= 10000) return (n / 10000).toFixed(n % 10000 ? 1 : 0) + "万";
  return String(n);
}

function fmtPrice(v) {
  // 报价单位是分
  if (v === null || v === undefined || v === 0) return "—";
  const yuan = Number(v) / 100;
  if (isNaN(yuan) || !isFinite(yuan)) return "—";
  return yuan >= 10000 ? (yuan / 10000).toFixed(yuan % 10000 ? 1 : 0) + "万" : String(Math.round(yuan));
}

// 导出/写库任务（mode: "file" 导出文件 | "db" 只写数据库）
async function runExport(mode) {
  if (!pgyTalents.length) return toast("没有可导出的达人", true);
  const limit = +$("pgy-export-limit").value || 1000;
  const exportList = pgyTalents.slice(0, limit);
  if (exportList.length < pgyTalents.length && !confirm(`当前有 ${pgyTalents.length} 位达人，按上限只处理前 ${exportList.length} 位。确定吗？`)) { return; }
  const isDbOnly = mode === "db";
  const btn = isDbOnly ? $("pgy-export-db") : $("pgy-export");
  const origText = btn.textContent;
  btn.disabled = true; btn.textContent = isDbOnly ? "写入中…" : "导出中…";
  const prog = $("pgy-median-progress");
  const fill = $("pgy-mp-fill");
  const count = $("pgy-mp-count");
  const label = $("pgy-mp-label");
  prog.style.display = "";
  label.textContent = isDbOnly ? "正在准备写入数据库…" : "正在准备导出…";
  fill.style.width = "0%";
  try {
    const body = {
      talents: exportList,
      with_comments: !!$("pgy-export-comments").checked,
      db_only: isDbOnly,
    };
    const r = await api("/api/pgy/export", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    const taskId = r.task_id;
    while (true) {
      await new Promise(res => setTimeout(res, 1200));
      const t = await api("/api/tasks/" + taskId);
      if (t.total > 0) {
        const pct = Math.min(99, Math.round(t.progress / t.total * 100));
        fill.style.width = pct + "%";
        count.textContent = `${t.progress}/${t.total}`;
        label.textContent = `正在导出完整数据… ${pct}%`;
      }
      if (t.status === "done") {
        fill.style.width = "100%";
        const res = t.result || {};
        const dbStats = res.db_stats;
        if (isDbOnly) {
          label.textContent = `写入完成：${res.count} 位达人`;
          const dbInfo = dbStats
            ? `达人新增 ${dbStats.creators_inserted} / 更新 ${dbStats.creators_updated} · 笔记新增 ${dbStats.notes_inserted} / 更新 ${dbStats.notes_updated}${dbStats.failed ? ` · 失败 ${dbStats.failed}` : ""}`
            : "";
          $("pgy-summary").innerHTML = `✓ 已写入数据库<br><span style="font-weight:400;font-size:12px;color:var(--slate)">${dbInfo}</span>`;
          toast(`已写入数据库，共 ${res.count} 位达人`);
        } else {
          label.textContent = `导出完成：${res.count} 位达人`;
          const excelFile = res.excel_path || "";
          const jsonFile = res.json_path || "";
          $("pgy-summary").innerHTML = `✓ 导出完成<br><span style="font-weight:400;font-size:12px;color:var(--slate)">Excel：${esc(excelFile)}<br>完整数据：${esc(jsonFile)}</span>`;
          toast(`导出完成，共 ${res.count} 位达人`);
        }
        break;
      }
      if (t.status === "error") {
        label.textContent = "任务失败";
        toast(t.error || "任务失败", true);
        break;
      }
    }
  } catch (e) {
    label.textContent = "启动失败";
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = origText;
    setTimeout(() => { prog.style.display = "none"; }, 8000);
  }
}
$("pgy-export").addEventListener("click", () => runExport("file"));
$("pgy-export-db").addEventListener("click", () => runExport("db"));

async function openPgyDetail(userId) {
  if (!userId) return toast("该达人缺少 ID，无法查看详情", true);
  $("pgy-detail-title").textContent = "达人详情";
  $("pgy-detail").style.display = "flex";
  setDrawerBackdrop(true);
  $("pgy-detail-body").innerHTML = `<div class="empty"><span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在加载…</div>`;
  try {
    const d = await api("/api/pgy/detail?user_id=" + encodeURIComponent(userId));
    $("pgy-detail-body").innerHTML = renderPgyDetail(d);
    // 笔记行点击：懒加载完整详情（正文/图片/评论）
    document.querySelectorAll("#pgy-detail-body .pgy-note-row").forEach(row => {
      row.addEventListener("click", async () => {
        const noteId = row.dataset.noteId;
        if (!noteId) { row.classList.toggle("open"); return; }
        const isOpen = row.classList.toggle("open");
        if (!isOpen) return;
        const detailEl = row.querySelector(".pgy-note-detail");
        if (detailEl.dataset.loaded) return;   // 已加载过
        detailEl.innerHTML = `<div class="pgy-note-big" style="display:none"></div><div class="empty" style="padding:12px"><span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在加载笔记详情…</div>`;
        try {
          const nd = await api("/api/pgy/note-detail?note_id=" + encodeURIComponent(noteId) + "&top_liked=1");
          detailEl.innerHTML = renderNoteFull(nd, noteId);
          detailEl.dataset.loaded = "1";
        } catch (e) {
          detailEl.innerHTML = `<div class="empty" style="padding:12px">加载失败：${esc(e.message)}</div>`;
        }
      });
    });
  } catch (e) {
    $("pgy-detail-body").innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

// 渲染笔记完整详情（正文/图片/评论）
function renderNoteFull(nd, noteId) {
  const detail = nd.detail || {};
  const title = detail.title || "（无标题）";
  const content = detail.content || "";
  const images = (detail.imagesList || []).map(img => img.url || "").filter(Boolean);
  const comments = (nd.comments && nd.comments.l1Comments) || [];
  const commentTotal = (nd.comments && nd.comments.l1CommentTotal) || 0;
  const imgsHtml = images.length ? `<div class="pgy-note-imgs">${images.map(u => `<img src="${esc(u)}" referrerpolicy="no-referrer" alt="">`).join("")}</div>` : "";
  const contentHtml = content ? `<div class="pgy-note-content">${esc(content).replace(/\n/g, "<br>")}</div>` : "";
  const commentsHtml = comments.length ? `<div class="pgy-note-comments">
    <div class="pgy-nc-head">评论 ${commentTotal} 条</div>
    ${comments.map(c => {
      const cm = c.comment || {};
      const like = cm.likeCount != null && cm.likeCount > 0 ? `<span class="pgy-nc-like">👍 ${esc(fmtNum(cm.likeCount))}</span>` : "";
      const subCnt = cm.subCommentCount != null && cm.subCommentCount > 0 ? `<span class="pgy-nc-sub">${esc(fmtNum(cm.subCommentCount))} 条回复</span>` : "";
      return `<div class="pgy-nc-item">
        <div class="pgy-nc-content">${esc(cm.content || "")}</div>
        <div class="pgy-nc-meta"><span class="pgy-nc-time">${esc(cm.createTime || "")}</span>${like}${subCnt}</div>
      </div>`;
    }).join("")}
  </div>` : (nd.comments ? `<div class="pgy-note-comments"><div class="pgy-nc-head">暂无评论</div></div>` : "");
  return `
    <div class="pgy-note-full-title">${esc(title)}</div>
    ${contentHtml}
    ${imgsHtml}
    ${commentsHtml}
    <div class="pgy-note-link"><a href="https://www.xiaohongshu.com/explore/${esc(noteId)}" target="_blank" rel="noopener">在小红书打开原文 ↗</a></div>`;
}

function renderPgyDetail(d) {
  const sections = [];
  const summary = (d.summary && d.summary.data) || null;
  const fans = (d.fans && d.fans.data) || null;
  const notes = (d.notes && d.notes.data) || null;

  // 达人基本信息（从列表里的 pgyTalents 找）
  let baseInfo = "";
  const t = pgyTalents.find(x => (x.userId || x.id) === d.user_id);
  if (t) {
    baseInfo = `<div class="pgy-hero">
      <div class="pgy-hero-avatar">${t.headPhoto ? `<img src="${esc(t.headPhoto)}" referrerpolicy="no-referrer" alt="">` : esc((t.name||"客").trim()[0])}</div>
      <div>
        <div class="pgy-hero-name">${esc(t.name || "达人")}${t.gender === "女" ? '<span class="tag-chip">♀</span>' : t.gender === "男" ? '<span class="tag-chip">♂</span>' : ""}</div>
        <div class="pgy-hero-sub">@${esc(t.redId || t.userId || "")}${t.location ? " · " + esc(t.location) : ""}</div>
      </div>
    </div>`;
  }

  if (summary) {
    sections.push(`<div class="pgy-detail-sec"><h4>总体表现</h4><div class="pgy-kv">
      ${kv("阅读中位数", fmtNum(summary.readMedian), "单篇笔记平均阅读量（越高越好）")}
      ${kv("互动中位数", fmtNum(summary.interactionMedian), "单篇笔记平均点赞+评论+收藏量（越高越好）")}
      ${kv("阅读水平", summary.readMedianBeyondRate != null ? "超 " + summary.readMedianBeyondRate + "% 同类达人" : "—", "和同粉丝量级达人比，他的阅读量排在前多少")}
      ${kv("互动水平", summary.interactionBeyondRate != null ? "超 " + summary.interactionBeyondRate + "% 同类达人" : "—", "互动量超过的同类达人比例")}
      ${kv("近30天笔记", summary.noteNumber + " 篇", "最近 30 天发布的笔记数量")}
      ${kv("近7天活跃", summary.activeDayInLast7 + " 天", "最近 7 天里有几天发了内容")}
      ${kv("回复私信", summary.responseRate != null ? summary.responseRate + "%" : "—", "粉丝私信/评论被回复的比例（越高越勤快）")}
      ${kv("被邀请数", summary.inviteNum != null ? fmtNum(summary.inviteNum) : "—", "收到品牌合作邀请的次数")}
    </div></div>`);
  }

  if (fans) {
    const fansGrowth = fans.fansGrowthRate;
    sections.push(`<div class="pgy-detail-sec"><h4>粉丝情况</h4><div class="pgy-kv">
      ${kv("粉丝数", fmtNum(fans.fansNum), "当前总粉丝量")}
      ${kv("近30天涨粉", fans.fansIncreaseNum != null ? (fans.fansIncreaseNum >= 0 ? "+" : "") + fmtNum(fans.fansIncreaseNum) : "—", "负数代表这段时间在掉粉")}
      ${kv("活跃粉丝率", fans.activeFansRate != null ? fans.activeFansRate + "%" : "—", "最近 28 天还在看内容的粉丝占比（水分检测）")}
      ${kv("互动粉丝率", fans.engageFansRate != null ? fans.engageFansRate + "%" : "—", "真正会点赞评论的粉丝占比（越高越真）")}
      ${kv("付费粉丝", fans.payFansUserNum30d != null ? fmtNum(fans.payFansUserNum30d) : "—", "最近 30 天在小红书花过钱的粉丝数（消费力）")}
    </div></div>`);
  }

  if (notes && Array.isArray(notes.notes)) {
    const rows = notes.notes.slice(0, 6).map((n, ni) => {
      const title = n.title || "（无标题）";
      const isVideo = Number(n.type) === 2;
      const beyond = (v) => v == null ? "" : (v > 0 ? "超 " + (v * 100).toFixed(0) + "% 同类" : "低于平均");
      return `<div class="pgy-note-row" data-ni="${ni}" data-note-id="${esc(n.noteId || "")}">
        <div class="pgy-note-head">
          <div class="pgy-note-thumb">${n.imgUrl ? `<img src="${esc(n.imgUrl)}" referrerpolicy="no-referrer" alt="">` : ""}</div>
          <div class="pgy-note-info">
            <div class="pgy-note-title">${esc(title)}${isVideo ? '<span class="tag-chip">视频</span>' : '<span class="tag-chip">图文</span>'}</div>
            <div class="pgy-note-meta">${esc(n.publishTime || "")} · 阅读 ${fmtNum(n.readNum)} · 赞 ${fmtNum(n.likeNum)} · 藏 ${fmtNum(n.collectNum)} · 互动 ${fmtNum(n.interactionNum)}</div>
          </div>
          <span class="pgy-note-caret">▾</span>
        </div>
        <div class="pgy-note-detail" id="pgy-note-detail-${ni}">
          <div class="pgy-note-big"><img src="${esc(n.imgUrl || "")}" referrerpolicy="no-referrer" alt=""></div>
          <div class="pgy-kv" style="grid-template-columns:repeat(auto-fill,minmax(110px,1fr))">
            ${kv("阅读量", fmtNum(n.readNum), "这篇笔记被看了多少次")}
            ${kv("阅读表现", beyond(n.readBeyondRate), "和同类笔记比如何")}
            ${kv("点赞", fmtNum(n.likeNum), "这篇被点赞的次数")}
            ${kv("点赞表现", beyond(n.likeBeyondRate), "和同类笔记比如何")}
            ${kv("收藏", fmtNum(n.collectNum), "这篇被收藏的次数")}
            ${kv("互动", fmtNum(n.interactionNum), "点赞+评论+收藏总量")}
            ${kv("曝光量", fmtNum(n.impNum), "这篇被推送给多少人看到")}
          </div>
          <div class="pgy-note-link">${n.noteId ? `<a href="https://www.xiaohongshu.com/explore/${esc(n.noteId)}" target="_blank" rel="noopener">在小红书打开原文 ↗</a>` : ""}</div>
        </div>
        </div>
      </div>`;
    }).join("");
    const medianStats = `
      ${kv("阅读中位数", fmtNum(notes.readMedian), "近期单篇笔记阅读量")}
      ${kv("点赞中位数", fmtNum(notes.likeMedian), "近期单篇笔记点赞量")}
      ${kv("收藏中位数", fmtNum(notes.collectMedian), "近期单篇笔记收藏量")}
      ${kv("评论中位数", fmtNum(notes.commentMedian), "近期单篇笔记评论量")}`;
    sections.push(`<div class="pgy-detail-sec"><h4>笔记数据</h4><div class="pgy-kv">${medianStats}</div>
      <div class="pgy-notes-list" style="margin-top:10px">${rows}</div>
    </div>`);
  }

  if (!sections.length) return `<div class="empty">暂无详情数据</div>`;
  return (baseInfo || "") + sections.join("") +
    `<div class="pgy-raw-wrap"><details><summary>查看原始数据（英文字段）</summary><div class="pgy-raw">${esc(JSON.stringify({summary: d.summary, fans: d.fans, notes: d.notes}, null, 2))}</div></details></div>`;
}

// 人话版字段卡片
function kv(label, value, tip) {
  return `<div class="kv"><span>${esc(label)}</span><b>${esc(String(value ?? "—"))}</b>${tip ? `<i title="${esc(tip)}">?</i>` : ""}</div>`;
}

$("pgy-detail-close").addEventListener("click", () => { $("pgy-detail").style.display = "none"; setDrawerBackdrop(false); });

// 抽屉遮罩：打开时显示遮罩 + 锁定 body 滚动，防止滚动穿透
function setDrawerBackdrop(show) {
  const backdrop = $("detail-backdrop");
  if (show) {
    backdrop.style.display = "flex";
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
  } else {
    backdrop.style.display = "none";
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
  }
}
// 点击遮罩关闭当前抽屉
$("detail-backdrop").addEventListener("click", () => {
  const pgy = $("pgy-detail"), hist = $("history-detail");
  if (pgy.style.display === "flex") pgy.style.display = "none";
  if (hist.style.display === "flex") hist.style.display = "none";
  setDrawerBackdrop(false);
});

/* ---------- 热点分析 ---------- */
let hsTaskId = null;
let hsPollTimer = null;
let hsNotes = [];
let hsCurStep = 1;

function hsSetStep(n) {
  hsCurStep = n;
  document.querySelectorAll("#hs-steps .hs-step").forEach(s => {
    const v = +s.dataset.step;
    s.classList.toggle("done", v < n);
    s.classList.toggle("active", v === n);
  });
}
function hsScrollTo(id) {
  const el = $(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  el.classList.remove("hs-flash");
  requestAnimationFrame(() => el.classList.add("hs-flash"));
  setTimeout(() => el.classList.remove("hs-flash"), 1400);
}
function hsGoStep(n) {
  hsCurStep = n;
  // 动作驱动单页：结果块 n>=2 显示，报告块 n>=3 显示；采集块始终显示
  $("hs-block-result").style.display = (n >= 2) ? "block" : "none";
  $("hs-block-report").style.display = (n >= 3) ? "block" : "none";
  hsSetStep(n);
}

function hsCollectFields() {
  // 从互动门槛按钮组收集已开启且填了数值的指标
  const minFilters = [];
  document.querySelectorAll(".hs-metric").forEach(m => {
    const btn = m.querySelector(".hs-metric-toggle");
    const val = m.querySelector(".hs-metric-val");
    const field = m.dataset.field;
    const active = btn.classList.contains("active");
    const num = val.value.trim();
    if (active && num) minFilters.push(`${field}>=${parseInt(num, 10)}`);
  });
  return {
    query: $("hs-query").value.trim(),
    target_category: $("hs-target").value.trim(),
    lowfan: $("hs-lowfan").checked,
    count: parseInt($("hs-count").value, 10),
    sort: $("hs-sort").value,
    days: $("hs-days").value,
    note_type: $("hs-note-type").value,
    max_results: parseInt($("hs-max-results").value, 10),
    comments_count: parseInt($("hs-comments").value, 10),
    min_filters: minFilters,
    exclude_words: $("hs-exclude").value.split(",").map(s => s.trim()).filter(Boolean),
  };
}

async function hsRun() {
  const query = $("hs-query").value.trim();
  if (!query) return toast("请输入品类/关键词", true);
  hsGoStep(1);
  $("hs-task-log").style.display = "block";
  $("hs-task-log").innerHTML = `<span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span> 正在启动采集…`;
  try {
    const res = await api("/api/hotspot/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(hsCollectFields()),
    });
    hsTaskId = res.task_id;
    toast("采集已开始");
    $("hs-result-card").style.display = "none";
    hsPoll();
  } catch (e) {
    $("hs-task-log").innerHTML = `<span class="badge warn">${esc(e.message)}</span>`;
    toast(e.message, true);
  }
}

function hsPoll() {
  clearInterval(hsPollTimer);
  hsPollTimer = setInterval(async () => {
    if (!hsTaskId) return;
    try {
      const res = await api("/api/hotspot/tasks/" + hsTaskId);
      const task = res.task;
      if (task.log && task.log.length) {
        $("hs-task-log").innerHTML = `<div class="task-log-inner" style="font-size:12px;color:var(--mute);font-family:var(--mono);line-height:1.8;white-space:pre-wrap">${esc(task.log.join("\n"))}</div>`;
      }
      if (task.status === "done") {
        clearInterval(hsPollTimer);
        $("hs-task-log").innerHTML = `<span class="badge ok">✓ 采集完成</span>`;
        await hsLoadNotes();
        hsGoStep(2);
        hsScrollTo("hs-block-result");
      } else if (task.status === "error") {
        clearInterval(hsPollTimer);
        $("hs-task-log").innerHTML = `<span class="badge warn">✗ ${esc(task.error || "采集失败")}</span>`;
        toast(task.error || "采集失败", true);
      }
    } catch (e) { /* 忽略瞬时错误 */ }
  }, 1200);
}

async function hsLoadNotes() {
  if (!hsTaskId) return;
  try {
    const res = await api("/api/hotspot/tasks/" + hsTaskId + "/notes");
    hsNotes = res.notes || [];
    const q = $("hs-query").value.trim() || "";
    $("hs-result-card").style.display = "block";
    $("hs-result-title").textContent = `热点笔记（${hsNotes.length} 条）${q ? "· " + q : ""}`;
    hsGoStep(2);
    if (!hsNotes.length) {
      $("hs-notes").innerHTML = `<div class="empty">没有符合条件的结果，请放宽筛选条件</div>`;
      return;
    }
    $("hs-notes").innerHTML = hsNotes.map((n, i) => {
      const eng = (n.liked_count || 0) + (n.collected_count || 0) + (n.comment_count || 0) + (n.share_count || 0);
      return `<div class="hs-note-row" data-note-id="${esc(n.note_id)}" style="padding:12px 0;border-bottom:1px solid var(--line);cursor:pointer">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
          <div style="flex:1;min-width:0">
            ${n.viral_score != null ? `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
              <span style="font-size:12px;font-weight:800;padding:2px 9px;border-radius:99px;background:${n.viral_score >= 70 ? "#eef1fe" : n.viral_score >= 40 ? "#fef6ec" : "#f2f2f4"};color:${n.viral_score >= 70 ? "var(--brand)" : n.viral_score >= 40 ? "#c47a12" : "var(--mute)"}">爆款潜力 ${n.viral_score}</span>
              ${n.viral_breakdown ? `<span style="font-size:11px;color:var(--mute)">${esc(n.viral_breakdown.interact_rate || "")} 互动率${n.viral_breakdown.velocity ? " · " + esc(n.viral_breakdown.velocity) + " 爆发" : ""}</span>` : ""}
            </div>` : ""}
            <div style="font-weight:600;color:var(--ink);line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${i + 1}. ${esc(n.title || "（无标题）")}</div>
            <div style="font-size:12px;color:var(--mute);margin-top:4px">${esc(n.user || "")}${n.tags && n.tags.length ? " · " + esc(n.tags.slice(0, 4).join(" #")) : ""}</div>
            <div style="margin-top:5px;display:flex;flex-wrap:wrap;gap:6px">
              ${n.keyword ? `<span style="font-size:11px;padding:1px 8px;border-radius:99px;background:var(--paper);border:1px solid var(--line);color:var(--slate)">${esc(n.keyword)}</span>` : ""}
              ${n.is_lowfan ? `<span style="font-size:11px;padding:1px 8px;border-radius:99px;background:#fff3f0;border:1px solid #f7b6a8;color:var(--red);font-weight:600">低粉爆款</span>` : ""}
              ${n.ratio != null ? `<span style="font-size:11px;padding:1px 8px;border-radius:99px;background:var(--paper);border:1px solid var(--line);color:var(--slate)">互动/粉丝 ${n.ratio}${n.fans ? ` · ${fmtCount(n.fans)}粉` : ""}</span>` : ""}
            </div>
          </div>
          <div style="text-align:right;flex-shrink:0">
            <div style="color:var(--red);font-weight:700">${fmtCount(n.liked_count)} 赞</div>
            <div style="font-size:11px;color:var(--mute);margin-top:2px">${fmtCount(n.collected_count)} 藏 · ${fmtCount(n.comment_count)} 评 · ${fmtCount(n.share_count)} 享</div>
            <div style="font-size:11px;color:var(--brand);margin-top:2px">互动 ${fmtCount(eng)}</div>
          </div>
        </div>
        <div class="hint" style="margin-top:6px;font-size:12px">点击标题查看详情 →</div>
      </div>`;
    }).join("");
    document.querySelectorAll(".hs-note-row").forEach(row => {
      row.addEventListener("click", () => hsOpenNote(row.dataset.noteId, row));
    });
    // 清掉旧的分析展示
    $("hs-analysis-card").style.display = "none";
    $("hs-analyze-status").textContent = "";
  } catch (e) {
    toast("加载笔记失败：" + e.message, true);
  }
}

async function hsOpenNote(noteId, row) {
  if (!noteId) return toast("该笔记缺少 ID", true);
  $("hs-note-detail").style.display = "flex";
  setDrawerBackdrop(true);
  $("hs-note-detail-body").innerHTML = `<div class="empty"><span class="spinner" style="border-color:rgba(30,64,216,.2);border-top-color:var(--red)"></span>正在加载笔记详情…</div>`;
  try {
    const q = hsTaskId ? "&task_id=" + encodeURIComponent(hsTaskId) : "";
    const res = await api("/api/hotspot/notes/" + encodeURIComponent(noteId) + "?with_comments=1" + q);
    $("hs-note-detail-title").textContent = (res.note && (res.note.title || res.note.display_title)) ? (res.note.title || res.note.display_title).slice(0, 30) : "笔记详情";
    $("hs-note-detail-body").innerHTML = hsRenderNoteDetail(res);
  } catch (e) {
    $("hs-note-detail-body").innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

function hsRenderNoteDetail(res) {
  const note = res.note || {};
  const comments = res.comments || [];
  const nick = note.nickname || note.user || "";
  const typeLabel = note.note_type || note.type || "";
  const parts = [];

  // 作者行
  parts.push(`<div class="xhs-note">`);
  parts.push(`<div class="xhs-author">`);
  const ava = note.avatar || "";
  parts.push(ava
    ? `<img class="xhs-avatar" src="${esc(ava)}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'">`
    : `<div class="xhs-avatar-fallback" style="display:grid">${esc(nick.charAt(0) || "?")}</div>`);
  if (ava) parts.push(`<div class="xhs-avatar-fallback">${esc(nick.charAt(0) || "?")}</div>`);
  parts.push(`<div class="xhs-author-meta">`);
  parts.push(`<div class="xhs-nick">${esc(nick || "匿名")}</div>`);
  parts.push(`<div class="xhs-author-sub">${esc(note.ip_location || "")}${note.upload_time ? " · " + esc(note.upload_time) : ""}${typeLabel ? " · " + esc(typeLabel) : ""}</div>`);
  parts.push(`</div>`);
  parts.push(`<button class="xhs-follow" disabled>关注</button>`);
  parts.push(`</div>`);

  // 标题
  parts.push(`<h1 class="xhs-title">${esc(note.title || note.display_title || "（无标题）")}</h1>`);

  // 正文
  if (res.detail_unavailable) {
    parts.push(`<div class="xhs-badge-warn">正文未获取（详情被风控 ${esc(res.detail_error || "")}）</div>`);
    parts.push(`<div class="xhs-desc">${esc(note.desc || "")}</div>`);
  } else {
    parts.push(`<div class="xhs-desc">${esc(note.desc || note.title || "")}</div>`);
  }

  // 媒体：视频封面 / 图集九宫格
  if (note.video_cover) {
    parts.push(`<div class="xhs-media video"><img src="${esc(note.video_cover)}" referrerpolicy="no-referrer" alt=""><span class="xhs-play">▶</span></div>`);
  } else if (note.image_list && note.image_list.length) {
    parts.push(`<div class="xhs-media">` + note.image_list.map(img => {
      const src = typeof img === "string" ? img : (img && (img.url_default || img.url)) || "";
      return `<img src="${esc(src)}" referrerpolicy="no-referrer" alt="">`;
    }).join("") + `</div>`);
  }

  // 标签
  if (note.tags && note.tags.length) {
    parts.push(`<div class="xhs-tags">` + note.tags.map(t => `<span class="xhs-tag">#${esc(t)}</span>`).join("") + `</div>`);
  }

  // 互动条
  parts.push(`<div class="xhs-interactions">`);
  parts.push(`<span>❤️ ${fmtCount(note.liked_count)}</span>`);
  parts.push(`<span>⭐ ${fmtCount(note.collected_count)}</span>`);
  parts.push(`<span>💬 ${fmtCount(note.comment_count)}</span>`);
  parts.push(`<span>↗ ${fmtCount(note.share_count)}</span>`);
  parts.push(`</div>`);

  // 评论区
  parts.push(`<div class="xhs-cmt-title">评论（${comments.length}）</div>`);
  parts.push(`<div class="xhs-comments">`);
  if (!comments.length) {
    parts.push(`<div class="hint">${res.comment_error ? "评论加载失败：" + esc(res.comment_error) : "暂无评论"}</div>`);
  } else {
    comments.forEach(c => {
      parts.push(`<div class="xhs-cmt">`);
      parts.push(`<div class="xhs-cmt-avatar">${esc((c.nickname || "匿").charAt(0))}</div>`);
      parts.push(`<div class="xhs-cmt-body"><div class="xhs-cmt-nick">${esc(c.nickname || "匿名")}</div><div class="xhs-cmt-text">${esc(c.content || "")}</div></div>`);
      parts.push(`<div class="xhs-cmt-like">${fmtCount(c.like_count)} 赞</div>`);
      parts.push(`</div>`);
    });
  }
  parts.push(`</div>`);

  // 原文链接
  if (note.note_url) {
    parts.push(`<a class="xhs-open" href="${esc(note.note_url)}" target="_blank" rel="noopener">在浏览器打开原文 →</a>`);
  }
  parts.push(`</div>`);
  return parts.join("");
}

async function hsAnalyze() {
  if (!hsTaskId) return toast("请先采集", true);
  if (!hsNotes.length) return toast("没有可分析的笔记", true);
  $("hs-analyze-status").textContent = "AI 分析中，可能需要 1-2 分钟…";
  try {
    const res = await api("/api/hotspot/tasks/" + hsTaskId + "/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_category: $("hs-target").value.trim() }),
    });
    toast(res.message || "分析已开始");
    setTimeout(hsCheckAnalysis, 3000);
  } catch (e) {
    $("hs-analyze-status").textContent = "";
    toast(e.message, true);
  }
}

/* 把 AI 报告的 Markdown 渲染成可折叠的分区卡片 */
function inlineBold(s) { return s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
function renderHsReport(md) {
  if (!md || !md.trim()) return `<div class="empty">报告为空</div>`;
  const lines = md.split("\n");
  let html = `<div class="hs-report">`;
  let currentSec = null;
  let currentSecTitle = "";
  const metaLines = [];

  function closeSection() {
    if (currentSec !== null) {
      html += `<div class="hs-rpt-section">
        <div class="hs-rpt-head"><span class="arrow">▶</span><span class="title">${currentSecTitle}</span></div>
        <div class="hs-rpt-body">${currentSec}</div>
      </div>`;
    }
  }
  function isH2(line) { return /^#{2}\s+/.test(line); }
  function isH3(line) { return /^#{3}\s+/.test(line); }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    if (isH2(line)) { closeSection(); currentSecTitle = esc(line.replace(/^#{2}\s+/, "")); currentSec = ""; continue; }
    // 第一个 ## 之前：H1 标题 + 元信息都进 metaLines
    if (currentSec === null) {
      if (/^#\s+/.test(line)) { metaLines.push("> " + line.replace(/^#\s+/, "")); continue; }
      metaLines.push(line);
      continue;
    }
    if (isH3(line)) {
      const t = esc(line.replace(/^#{3}\s+/, ""));
      currentSec += `<div class="rpt-note"><div class="hs-rpt-note-title">${t}</div>`;
      const buf = [];
      let j = i + 1;
      while (j < lines.length && !isH3(lines[j]) && !isH2(lines[j]) && lines[j].trim()) { buf.push(lines[j].trim()); j++; }
      currentSec += renderNoteBlock(buf);
      currentSec += `</div>`;
      i = j - 1;
      continue;
    }
    currentSec += renderLine(line);
  }
  closeSection();

  if (metaLines.length) {
    const metaHtml = metaLines.map(l => {
      if (l.startsWith(">")) return `<div class="hs-rpt-meta">${inlineBold(esc(l.replace(/^>\s*/, "")))}</div>`;
      return `<div class="hs-rpt-meta">${inlineBold(esc(l))}</div>`;
    }).join("");
    html = `<div class="hs-rpt-meta-block" style="background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:10px">${metaHtml}</div>` + html;
  }
  html += `</div>`;
  return html;
}

/* 渲染报告并绑定折叠（直接操作目标容器，事件随元素保留） */
function renderHsReportInto(el, md) {
  el.innerHTML = renderHsReport(md);
  el.querySelectorAll(".hs-rpt-section").forEach((sec, idx) => {
    sec.querySelector(".hs-rpt-head").addEventListener("click", () => sec.classList.toggle("open"));
    if (idx === 0) sec.classList.add("open");
  });
}

function renderLine(line) {
  const l = esc(line);
  if (/^\|.+\|$/.test(l)) return renderTableRow(l);
  if (/^[-*•]\s+/.test(l)) return `<div class="hs-rpt-bullet">${inlineBold(l.replace(/^[-*•]\s+/, "· "))}</div>`;
  if (/^```/.test(l)) return "";
  if (/^\d+[.、]/.test(l)) return `<div class="hs-rpt-bullet">${inlineBold(l)}</div>`;
  if (l.startsWith(">")) return `<div class="hs-rpt-quote">${inlineBold(l.replace(/^>\s*/, ""))}</div>`;
  if (/^#{4,}\s+/.test(l)) return `<div class="hs-rpt-note-title" style="margin-top:6px">${l.replace(/^#{4,}\s+/, "")}</div>`;
  return `<div class="hs-rpt-para">${inlineBold(l)}</div>`;
}

let _tableBuf = [];
function renderTableRow(l) { _tableBuf.push(l); return ""; }
function flushTable() {
  if (!_tableBuf.length) return "";
  const rows = _tableBuf.map(r => r.replace(/^\||\|$/g, "").split("|").map(c => c.trim()));
  _tableBuf = [];
  if (rows.length < 2) return "";
  let t = `<table class="hs-rpt-table"><tr>${rows[0].map(h => `<th>${inlineBold(h)}</th>`).join("")}</tr>`;
  for (let i = 2; i < rows.length; i++) { t += `<tr>${rows[i].map(c => `<td>${c}</td>`).join("")}</tr>`; }
  return t + `</table>`;
}

function renderNoteBlock(lines) {
  let html = "";
  const kv = [];
  const paras = [];
  for (const line of lines) {
    const m = line.match(/^\s*[-*•]\s*\*\*([^：:]+)[：:]\*\*\s*(.+)$/) || line.match(/^\s*\*\*([^：:]+)[：:]\*\*\s*(.+)$/);
    if (m) { kv.push(`<span>${inlineBold(esc(m[1]))}：${inlineBold(esc(m[2]))}</span>`); continue; }
    const sm = line.match(/^\s*\*\*评分\*\*[：:]?\s*(.+)$/);
    if (sm) { paras.push(`<div class="rpt-score">${inlineBold(esc(sm[1]))}</div>`); continue; }
    if (line.startsWith(">")) { paras.push(`<div class="hs-rpt-quote">${inlineBold(esc(line.replace(/^>\s*/, "")))}</div>`); continue; }
    if (/^\|.+\|$/.test(line)) { _tableBuf.push(line); continue; }
    paras.push(renderLine(line));
  }
  if (kv.length) html += `<div class="hs-rpt-kv">${kv.join("")}</div>`;
  html += flushTable();
  if (paras.length) html += paras.join("");
  return html;
}

async function hsCheckAnalysis() {
  if (!hsTaskId) return;
  try {
    const res = await api("/api/hotspot/tasks/" + hsTaskId + "/analysis");
    if (res.ready) {
      $("hs-analyze-status").textContent = "";
      $("hs-analysis-card").style.display = "block";
      renderHsReportInto($("hs-analysis-content"), res.content);
      toast("AI 分析报告已生成");
      hsGoStep(3);
      hsScrollTo("hs-block-report");
    } else {
      setTimeout(hsCheckAnalysis, 4000);
    }
  } catch (e) { setTimeout(hsCheckAnalysis, 4000); }
}

/* 互动门槛按钮：点击切换开启/关闭，开启时显示数值输入框 */
document.querySelectorAll(".hs-metric-toggle").forEach(btn => {
  btn.addEventListener("click", () => {
    const metric = btn.closest(".hs-metric");
    const valInput = metric.querySelector(".hs-metric-val");
    const on = btn.classList.toggle("active");
    valInput.style.display = on ? "" : "none";
    if (!on) valInput.value = "";
    btn.classList.toggle("btn-primary", on);
    btn.classList.toggle("btn-ghost", !on);
  });
});

$("hs-run").addEventListener("click", hsRun);
$("hs-refresh").addEventListener("click", async () => { if (hsTaskId) await hsLoadNotes(); else toast("还没有采集任务", true); });
$("hs-analyze").addEventListener("click", hsAnalyze);
$("hs-note-detail-close").addEventListener("click", () => { $("hs-note-detail").style.display = "none"; setDrawerBackdrop(false); });

/* ---------- 助手 ---------- */
function appendAgentMsg(role, text, streaming) {
  const chat = $("agent-chat");
  const div = document.createElement("div");
  div.className = "agent-msg " + (role === "user" ? "agent-user" : "agent-bot");
  if (streaming) div.classList.add("streaming");
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function sendAgent() {
  const input = $("agent-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  appendAgentMsg("user", msg);
  const botMsg = appendAgentMsg("bot", "", true);
  const btn = $("agent-send");
  btn.disabled = true;
  try {
    const resp = await fetch("/api/agent/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ message: msg }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      botMsg.textContent = "出错：" + (err.error || resp.status);
      botMsg.classList.remove("streaming");
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);
        if (data === "[DONE]") continue;
        try {
          const obj = JSON.parse(data);
          if (obj.delta) {
            botMsg.textContent += obj.delta;
            botMsg.scrollIntoView({ block: "end" });
          } else if (obj.error) {
            botMsg.textContent = "出错：" + obj.error;
          }
        } catch (e) {}
      }
    }
    botMsg.classList.remove("streaming");
  } catch (e) {
    botMsg.textContent = "请求失败：" + e.message;
    botMsg.classList.remove("streaming");
  } finally {
    btn.disabled = false;
  }
}
$("agent-send").addEventListener("click", sendAgent);
$("agent-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendAgent();
  }
});

/* ---------- 数据仪表盘 ---------- */
const dashCharts = {};
function dashInit(id, option) {
  const el = $(id);
  if (!el || typeof echarts === "undefined") return;
  if (dashCharts[id]) dashCharts[id].dispose();
  const chart = echarts.init(el);
  chart.setOption(option);
  dashCharts[id] = chart;
}
function dashBarOption(xData, yData, opts = {}) {
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 60, right: 24, top: 30, bottom: 60 },
    xAxis: { type: "category", data: xData, axisLabel: { rotate: opts.rotate || 45 } },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: yData, itemStyle: { color: "#f04e37" }, barMaxWidth: 28 }]
  };
}
function dashLineOption(xData, yData) {
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 60, right: 24, top: 30, bottom: 60 },
    xAxis: { type: "category", data: xData, axisLabel: { rotate: 45 } },
    yAxis: { type: "value" },
    series: [{ type: "line", data: yData, smooth: true, itemStyle: { color: "#f04e37" }, areaStyle: { opacity: 0.12 } }]
  };
}
function dashHBarOption(names, values) {
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 140, right: 40, top: 10, bottom: 30 },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: names, inverse: true },
    series: [{ type: "bar", data: values, itemStyle: { color: "#f04e37" }, label: { show: true, position: "right" } }]
  };
}
function dashPieOption(data) {
  return {
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0 },
    series: [{ type: "pie", radius: "60%", center: ["50%", "45%"], data: data }]
  };
}
async function loadDashboard() {
  const sel = $("dashboard-collection");
  let d;
  try {
    const coll = sel && sel.value ? "?collection=" + encodeURIComponent(sel.value) : "";
    d = await api("/api/dashboard" + coll);
  } catch (e) { toast("加载仪表盘失败：" + e.message, true); return; }
  // 填充集合下拉（仅在需要时，保留用户选择）
  if (sel && sel.options.length === 0 && d.collections && d.collections.length) {
    d.collections.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name + "（" + fmtCount(c.note_count) + " 篇）";
      sel.appendChild(opt);
    });
    sel.value = d.collection || "";
  }
  const k = d.kpi || {};
  $("dashboard-kpis").innerHTML = [
    ["笔记数", k.note_count],
    ["评论数", k.comment_count],
    ["总点赞", k.total_likes],
    ["总收藏", k.total_collects]
  ].map(([l, v]) => `<div class="kpi"><div class="v">${esc(fmtCount(v))}</div><div class="l">${esc(l)}</div></div>`).join("");

  const nt = d.note_trend || [];
  const ct = d.comment_trend || [];
  dashInit("chart-note-trend", dashBarOption(nt.map(m => m.month), nt.map(m => m.count)));
  dashInit("chart-comment-trend", dashLineOption(ct.map(m => m.month), ct.map(m => m.count)));
  dashInit("chart-note-top", dashHBarOption((d.note_interact_top || []).map(n => n.title.slice(0, 16)), (d.note_interact_top || []).map(n => (n.likes || 0) + (n.comments || 0))));
  dashInit("chart-user-top", dashHBarOption((d.user_comment_top || []).map(u => u.name), (d.user_comment_top || []).map(u => u.value)));
  dashInit("chart-note-type", dashPieOption(d.note_type_dist || []));
  dashInit("chart-talent-gender", dashPieOption((d.talent && d.talent.gender) || []));
  dashInit("chart-talent-trade", dashPieOption((d.talent && d.talent.trade_types) || []));
  dashInit("chart-talent-loc", dashHBarOption((d.talent && d.talent.location_top || []).map(x => x.name), (d.talent && d.talent.location_top || []).map(x => x.value)));
  dashInit("chart-talent-fans", dashBarOption((d.talent && d.talent.fans_bands || []).map(x => x.name), (d.talent && d.talent.fans_bands || []).map(x => x.value), { rotate: 0 }));
  dashInit("chart-talent-price", dashBarOption((d.talent && d.talent.price_bands || []).map(x => x.name), (d.talent && d.talent.price_bands || []).map(x => x.value), { rotate: 0 }));
}
window.addEventListener("resize", () => { Object.values(dashCharts).forEach(c => c.resize()); });
const _dashSel = $("dashboard-collection");
if (_dashSel) _dashSel.addEventListener("change", () => loadDashboard());

/* ---------- 评论洞察 ---------- */
let caPollTimer = null;
let caTaskId = null;

function caSetRunning(running) {
  $("ca-start").disabled = running;
  $("ca-progress").style.display = running ? "block" : "none";
}

async function populateCaCollections() {
  const sel = $("ca-collection");
  if (!sel || sel.options.length) return;
  try {
    const d = await api("/api/dashboard");
    (d.collections || []).forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name + "（" + fmtCount(c.note_count) + " 篇）";
      sel.appendChild(opt);
    });
  } catch (e) { /* 忽略 */ }
}

async function loadCommentAnalysis() {
  await populateCaCollections();
  const name = $("ca-collection").value;
  if (!name) return;
  try {
    const d = await api("/api/comment-analyze/result?collection=" + encodeURIComponent(name));
    renderCommentAnalysis(d);
  } catch (e) {
    $("ca-result").innerHTML = `<div class="hint">该集合尚未分析过，点「开始分析」生成洞察。</div>`;
  }
}

function startCommentAnalysis() {
  const name = $("ca-collection").value;
  if (!name) return toast("请先选择分析对象", true);
  caSetRunning(true);
  $("ca-bar").style.width = "0%";
  $("ca-progress-text").textContent = "提交任务…";
  api("/api/tasks/comment_analyze", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ collection: name }) })
    .then(res => { caTaskId = res.task_id; caPoll(); })
    .catch(e => { caSetRunning(false); toast("启动分析失败：" + e.message, true); });
}

function caPoll() {
  caPollTimer = setInterval(async () => {
    try {
      const t = await api("/api/tasks/" + caTaskId);
      if (t.total > 0) {
        $("ca-bar").style.width = Math.round(t.progress / t.total * 100) + "%";
        $("ca-progress-text").textContent = `分析中 ${t.progress}/${t.total} 批…`;
      } else {
        $("ca-progress-text").textContent = "准备中…";
      }
      if (t.status !== "running") {
        clearInterval(caPollTimer);
        caSetRunning(false);
        if (t.status === "success" && t.result) {
          toast("评论分析完成");
          renderCommentAnalysis(t.result);
        } else if (t.status === "failed") {
          toast("分析失败：" + (t.error || "未知错误"), true);
        } else if (t.status === "cancelled") {
          toast("分析已取消", true);
        }
      }
    } catch (e) {
      clearInterval(caPollTimer); caSetRunning(false);
      toast("进度读取失败：" + e.message, true);
    }
  }, 1500);
}

function renderCommentAnalysis(d) {
  const k = d.kpi || {};
  const cat = d.category_count || {};
  const sent = d.sentiment_count || {};
  const topics = d.topic_count || [];
  const rep = d.representative || {};
  const neg = d.negative_list || [];
  const catTotal = Object.values(cat).reduce((a, b) => a + b, 0) || 1;

  const catColors = {"问题咨询":"#4a90d9","购买意向":"#7bb74a","产品评价":"#f0a04b","负面舆情":"#e05b5b","其他":"#9aa5b1"};
  const sentColors = {"正面":"#7bb74a","中性":"#9aa5b1","负面":"#e05b5b"};

  function bar(name, val, total, color) {
    const pct = Math.round(val / total * 100);
    return `<div style="display:flex;align-items:center;gap:8px;margin:5px 0">
      <div style="width:76px;flex:none;color:var(--slate);font-size:12px">${esc(name)}</div>
      <div class="bar" style="flex:1"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <div style="width:40px;flex:none;text-align:right;font-size:12px;color:var(--ink)">${val}</div>
    </div>`;
  }

  let html = `<div class="kpis">`
    + `<div class="kpi"><div class="v">${esc(fmtCount(k.analyzed))}</div><div class="l">已分析评论</div></div>`
    + `<div class="kpi"><div class="v">${esc(fmtCount(k.total))}</div><div class="l">评论总数</div></div>`
    + `<div class="kpi"><div class="v">${esc(fmtCount(neg.length))}</div><div class="l">负面舆情</div></div>`
    + `<div class="kpi"><div class="v">${esc(fmtCount(topics.length))}</div><div class="l">话题数</div></div>`
    + `</div>`;

  html += `<div class="dash-grid" style="margin-top:16px">`;
  html += `<div class="card"><div class="card-title">评论分类分布</div>`
    + Object.entries(cat).map(([kk, v]) => bar(kk, v, catTotal, catColors[kk] || "#9aa5b1")).join("") + `</div>`;
  html += `<div class="card"><div class="card-title">情绪分布</div>`
    + Object.entries(sent).map(([kk, v]) => bar(kk, v, catTotal, sentColors[kk] || "#9aa5b1")).join("") + `</div>`;
  html += `<div class="card"><div class="card-title">高频话题 Top</div>`
    + (topics.length ? topics.map(t => bar(t.name, t.value, topics[0].value, "#4a90d9")).join("") : `<div class="hint">暂无</div>`) + `</div>`;
  html += `</div>`;

  const CAT_LABELS = {"问题咨询":"问题咨询","购买意向":"购买意向","产品评价":"产品评价","负面舆情":"负面舆情","其他":"其他"};
  Object.keys(CAT_LABELS).forEach(catKey => {
    const list = rep[catKey] || [];
    if (!list.length) return;
    html += `<div class="card" style="margin-top:16px"><div class="card-title">${CAT_LABELS[catKey]} · 代表评论</div>`
      + list.map(commentCard).join("") + `</div>`;
  });

  if (neg.length) {
    html += `<div class="card" style="margin-top:16px"><div class="card-title" style="color:#e05b5b">负面舆情 · 需关注（${neg.length} 条）</div>`
      + neg.slice(0, 50).map(commentCard).join("")
      + (neg.length > 50 ? `<div class="hint">…共 ${neg.length} 条</div>` : "") + `</div>`;
  }

  $("ca-result").innerHTML = html;
}

function commentCard(c) {
  return `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
    <div style="font-size:12.5px;color:var(--ink);line-height:1.6">${esc(c.content || "")}</div>
    <div class="hint" style="margin-top:3px;font-size:11px">
      ${esc(c.username || "")} · ${esc(c.dt || "")} · ${esc((c.note_title || "").slice(0, 20))}
      ${c.topic ? ` · <span style="color:var(--red)">${esc(c.topic)}</span>` : ""}
    </div>
  </div>`;
}

$("ca-start").addEventListener("click", startCommentAnalysis);
$("ca-collection").addEventListener("change", () => {
  $("ca-result").innerHTML = "";
  loadCommentAnalysis();
});

/* ---------- 启动 ---------- */
refreshAuth();
