const $ = (id) => document.getElementById(id);

const state = {
  snap: null,
  view: "home",
  filter: "feeling",
  query: "",
  starredOnly: false,
  day: null,
  openIds: new Set(),
  stars: {},
  sig: "",
  loading: false,
  limit: 0,
  selected: null,
  detailId: null,
  timer: null,
  refreshSeconds: 30,
};

const KIND_LABEL = {
  self: "自己写的",
  dialogue: "聊天时写的",
  read: "读了会儿书",
  message: "主动找你",
  autocapture: "自动补记",
};

// 他自己的分类（2026-10-29 起插件写入 kind 字段）
const OWN_KIND_LABEL = {
  fact: "事实",
  feeling: "感受",
  event: "事件",
  moment: "重要时刻",
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function highlight(text, query) {
  const safe = esc(text);
  if (!query) return safe;
  const q = esc(query).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (!q) return safe;
  try {
    return safe.replace(new RegExp(q, "gi"), (m) => `<mark>${m}</mark>`);
  } catch (e) {
    return safe;
  }
}

async function getSnapshot() {
  const r = await fetch("/api/snapshot", { cache: "no-store" });
  return r.json();
}

async function getDiag() {
  const r = await fetch("/api/diag", { cache: "no-store" });
  return r.json();
}

async function postStar(payload) {
  const r = await fetch("/api/star", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return r.json();
}

/* ---------------- 数据 ---------------- */

async function load(manual = false) {
  if (state.loading) return;
  state.loading = true;
  try {
    const snap = await getSnapshot();
    if (!snap || !snap.ok) {
      $("refreshInfo").textContent = "读取失败：" + ((snap && snap.error) || "未知错误");
      return;
    }
    state.snap = snap;
    state.stars = snap.stars || {};
    const conf = snap.settings || {};
    if (conf.page_size && !state.limit) state.limit = conf.page_size;
    if (conf.page_size) state.pageSize = conf.page_size;
    state.refreshSeconds = conf.refresh_seconds || 30;
    if (!state.themeInit && conf.theme) {
      applyTheme(conf.theme, conf.transparent !== false);
      state.themeInit = true;
    }

    const sig = JSON.stringify([snap.journal.map((e) => e.id), Object.keys(state.stars).sort()]);
    const changed = sig !== state.sig;
    state.sig = sig;
    renderShell();
    if (state.view === "home") renderHome();
    else if (state.view === "memory") renderMemory();
    else if (state.view === "books") renderBooks();
    if (state.view === "journal" && (changed || manual)) renderJournal();
    $("refreshInfo").textContent = "更新于 " + new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } catch (e) {
    console.error("[zz] load failed:", e && e.stack ? e.stack : e);
    $("refreshInfo").textContent = "连接不上程序";
  } finally {
    state.loading = false;
  }
}

function scheduleRefresh() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => load(false), Math.max(5, state.refreshSeconds) * 1000);
}

/* ---------------- 主题 ---------------- */
const THEMES = ["xuantan", "black", "white"];

function currentTheme() {
  return document.documentElement.dataset.theme || "xuantan";
}

function applyTheme(theme, transparent) {
  if (!THEMES.includes(theme)) theme = "xuantan";
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.transparent = transparent ? "on" : "off";
  try {
    localStorage.setItem("theme", theme);
    localStorage.setItem("transparent", transparent ? "on" : "off");
  } catch (e) {}
  document.querySelectorAll("#themeGrid .theme-card").forEach((b) => {
    b.classList.toggle("active", b.dataset.pick === theme);
  });
  const sw = $("switchTransparent");
  if (sw) sw.classList.toggle("on", !!transparent);
  state.theme = theme;
  state.transparent = !!transparent;
}

async function saveTheme(theme, transparent) {
  applyTheme(theme, transparent);
  try {
    await fetch("/api/theme", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: theme, transparent: transparent }),
    });
  } catch (e) {}
}

/* ---------------- 外壳 ---------------- */

function renderShell() {
  const s = state.snap;
  if (!s) return;
  const b = s.bot;

  $("runDot").className = "dot " + (b.running ? "on" : "off");
  $("runText").textContent = b.running ? "正在运行" : "没在运行";
  $("sideState").textContent = b.state;

  const warns = s.warnings || [];
  for (const id of ["warnHome", "warnJournal"]) {
    const box = $(id);
    if (warns.length) {
      box.innerHTML = warns.map((w) => `<div>⚠ ${esc(w)}</div>`).join("");
      box.classList.remove("hidden");
    } else {
      box.innerHTML = "";
      box.classList.add("hidden");
    }
  }

  // 机器人名字（用户自己填的 ID）
  const botName = (s.bot_name || "").trim() || "大肥鱼";
  if ($("bname")) $("bname").textContent = botName;
  const av = $("brandAvatar");
  if (av) av.textContent = botName.slice(-1);
  if ($("nameInput") && document.activeElement !== $("nameInput")) $("nameInput").value = s.bot_name || "";
  const conf2 = s.settings || {};
  if ($("switchTray")) $("switchTray").classList.toggle("on", !!conf2.close_to_tray);

  const jn = s.journal.length;
  $("jcount").textContent = jn ? jn : "";
  $("srcInfo").textContent = "日记文件 " + (s.source.journal_mtime || "—");

  // 还没指定监测目录：直接引导去设置
  const setup = s.setup || {};
  const needSetup = setup.needed || setup.name_needed;
  if (needSetup) {
    $("setupOverlay").classList.remove("hidden");
    $("pathBlock").classList.toggle("hidden", !setup.needed);
    if (!$("setupPath").value && setup.bot_root && setup.source === "settings") {
      $("setupPath").value = setup.bot_root;
    }
    if (!$("setupName").value && s.bot_name) $("setupName").value = s.bot_name;
  } else {
    $("setupOverlay").classList.add("hidden");
  }

  $("viewTitle").textContent =
    state.view === "home" ? "他现在在干什么" : state.view === "memory" ? "记忆档案" : state.view === "books" ? "它读的书" : "它写的日记";
  if (state.view === "home") {
    $("viewSub").textContent = "从它留下的痕迹推断，不是实时状态";
  } else if (state.view === "memory") {
    $("viewSub").textContent = "只读 · 它自己整理的那份记录";
  } else if (state.view === "books") {
    $("viewSub").textContent = "只读 · 书架进度与它写的读书笔记";
  } else {
    const n = filtered().length;
    if (state.query) $("viewSub").textContent = `找到 ${n} 条含「${state.query}」的记录`;
    else $("viewSub").textContent = `只读展示，不修改它的任何记录 · 共 ${n} 条`;
  }
}

/* ---------------- 概览 ---------------- */

function renderHome() {
  const s = state.snap;
  const b = s.bot;
  $("heroState").textContent = b.state;
  $("heroHint").textContent = b.state_hint;
  $("quietVal").textContent = b.quiet_text || "—";
  $("lastMarkVal").textContent = b.last_mark ? b.last_mark.slice(11) : "—";

  $("stJournal").textContent = s.today.journals;
  $("stRead").textContent = s.today.reads;
  $("stMsg").textContent = s.today.messages;

  const r = s.reading || {};
  const books = s.books || [];
  if (r.book) {
    $("bookName").textContent = r.book.replace(/\.(txt|md)$/i, "");
    $("bookPos").textContent = `${Number(r.pos).toLocaleString()} / ${Number(r.total).toLocaleString()} 字`;
    $("bookPct").textContent = r.percent + "%";
    $("bookTime").textContent = "上次翻页 " + (r.updated_at || "").slice(0, 16);
    $("bookBar").style.width = Math.max(1.5, r.percent) + "%";
  } else {
    $("bookName").textContent = "书架上还没有书";
    $("bookPos").textContent = "—";
    $("bookPct").textContent = "0%";
    $("bookTime").textContent = "";
    $("bookBar").style.width = "0%";
  }

  // 阅读总览（合并到书架卡片顶部）
  const stats = s.reading_stats || {};
  $("rsSessions").textContent = stats.sessions || 0;
  $("rsChars").textContent = Number(stats.chars || 0).toLocaleString();
  $("rsBooks").textContent = stats.books || 0;
  $("rsNote").textContent = stats.last_book
    ? `最近在读《${stats.last_book.replace(/\.(txt|md)$/i, "")}》 · ${(stats.last_time || "").slice(5, 16)}`
    : "";

  // 每本书分开记录
  const rows = $("bookRows");
  rows.innerHTML = books
    .map((x) => {
      const name = x.book.replace(/\.(txt|md)$/i, "");
      const cnt = x.sessions || 0;
      const charsNum = (x.total || 0) > 0 ? (x.pos || 0) : (x.chars_read || 0);
      const chars = Number(charsNum).toLocaleString();
      const pct = x.percent || 0;
      const cls = x.book === r.book ? "bookrow active" : "bookrow";
      return (
        `<div class="${cls}">` +
        `<span class="bname2">《${esc(name)}》</span>` +
        `<span class="bpct">${pct}%</span>` +
        `<span class="bmeta">${cnt ? `读了 ${cnt} 次 · ${chars} 字` : "还没开始读"}</span>` +
        `<span class="btime">${esc((x.last_session || x.updated_at || "").slice(5, 16))}</span>` +
        `</div>`
      );
    })
    .join("");

  const tl = $("timeline");
  const thisYear = String(new Date().getFullYear());
  tl.innerHTML = s.events
    .map(
      (e) => `
      <div class="tlitem" data-kind="${e.kind}">
        <div class="tltime"><span>${esc(e.date.slice(0, 4) === thisYear ? e.date.slice(5) : e.date)}</span><span>${esc(e.clock)}</span></div>
        <div class="tlbody">
          <div class="tlttl">${esc(e.title)}</div>
          <div class="tldet">${esc(e.detail)}</div>
        </div>
      </div>`
    )
    .join("");
  if (!s.events.length) tl.innerHTML = `<div class="empty">它还没留下任何记录。</div>`;

  // 往年今天
  const hist = s.history || [];
  const hc = $("historyCard");
  if (hist.length) {
    hc.classList.remove("hidden");
    $("historyList").innerHTML = hist
      .map(
        (e) => `<div class="hitem">
          <div class="hdate">${esc(e.date.replace(/-/g, "."))}</div>
          <div class="htext">${esc(e.content.slice(0, 90))}</div>
        </div>`
      )
      .join("");
  } else {
    hc.classList.add("hidden");
    $("historyList").innerHTML = "";
  }

  // 常提到的
  const tp = s.topics || [];
  const tc = $("topicCard");
  if (tp.length) {
    tc.classList.remove("hidden");
    $("topicList").innerHTML = tp
      .map((t) => `<button class="topic" data-word="${esc(t.word)}">${esc(t.word)}<i>${t.count}</i></button>`)
      .join("");
  } else {
    tc.classList.add("hidden");
    $("topicList").innerHTML = "";
  }
}

/* ---------------- 记忆档案 ---------------- */

function renderMemory() {
  const m = (state.snap && state.snap.memory) || {};
  const box = $("memSections");
  if (!m.exists) {
    $("memHint").textContent = "找不到记忆档案文件（它还没整理过，或路径变了）。";
    $("memMeta").textContent = "";
    box.innerHTML = "";
    return;
  }
  $("memHint").textContent = "这是它自己整理的记忆，只读展示，不是备忘录。";
  $("memMeta").innerHTML = `${m.chars} 字<br>更新于 ${esc(m.updated_at || "—")}`;

  const parts = [];
  const card = (inner) => `<div class="card memsec">${inner}</div>`;

  // 0) 记忆健康
  const h = m.health || {};
  if (h.curation) {
    const rows = [];
    const push = (ok, label, value) => rows.push(`<div class="health-row"><span class="h-dot ${ok ? "ok" : "warn"}"></span><span class="h-label">${label}</span><span class="h-value">${value}</span></div>`);
    push(!h.curation.missed, "每晚整理", esc(h.curation.note || "—"));
    push(!h.recent.stale, "最近几天档案", h.recent.age_hours == null ? "还没有" : `${h.recent.age_hours} 小时前`);
    push(!h.profile.stale, "长期底色", h.profile.age_days == null ? "还没有" : `${h.profile.age_days} 天前`);
    push(!h.short.crowded, "短期池", `${h.short.pool} 条 · 暂存 ${h.short.temp} 条（最久 ${h.short.oldest_days} 天）`);
    push(!h.short.trash_stuck, "回收站", `${h.short.trash} 条`);
    push(true, "长期记忆", `${h.long.total} 条 · 最新 ${esc(h.long.newest || "—")}`);
    parts.push(card(`<div class="memtitle2">记忆健康</div><div class="health">${rows.join("")}</div>`));
  }

  // 1) 最近几天
  const recent = m.recent || {};
  if (recent.exists && (recent.lines || []).length) {
    parts.push(
      card(
        `<div class="memtitle2">最近几天<span class="mem-sub">${esc(recent.updated_day || recent.updated_at || "")}</span></div>` +
          recent.lines.map((l) => `<div class="memline">${esc(l)}</div>`).join("")
      )
    );
  }

  // 2) 短期记忆
  const short = m.short || {};
  if (short.exists) {
    const c = short.counts || {};
    const all = short.items || [];
    const rows = all.slice(0, 20);
    const label = { pool: "池", temp: "暂存", trash: "回收站" };
    const items = rows
      .map((it) => {
        const meta = [
          `活过 ${it.hits || 0} 次`,
          it.created || "",
          it.status === "temp" && it.days_left != null ? `还剩 ${it.days_left} 天` : "",
          it.status === "trash" ? "已进回收站" : "",
        ]
          .filter(Boolean)
          .join(" · ");
        return `<div class="mem-item s-${esc(it.status)}">
          <div class="m-text">${esc(it.content)}</div>
          ${it.reply ? `<div class="m-reply">${esc(it.reply)}</div>` : ""}
          <div class="m-meta">${esc(meta)}</div>
        </div>`;
      })
      .join("");
    parts.push(
      card(
        `<div class="memtitle2">短期记忆<span class="mem-sub">${short.total} 条</span></div>` +
          `<div class="mem-chips">
             <span class="mem-chip">${label.pool} ${c.pool || 0}</span>
             <span class="mem-chip">${label.temp} ${c.temp || 0}</span>
             <span class="mem-chip">${label.trash} ${c.trash || 0}</span>
           </div>` +
          items +
          (all.length > rows.length ? `<div class="mem-more">还有 ${all.length - rows.length} 条</div>` : "")
      )
    );
  }

  // 3) 长期底色
  (m.sections || []).forEach((sec) => {
    parts.push(
      card(
        `<div class="memtitle2">${esc(sec.title)}</div>` +
          sec.lines.map((l) => `<div class="memline">${esc(l)}</div>`).join("")
      )
    );
  });

  // 4) 长期记忆条目
  const long = m.long || {};
  if (long.exists && long.total) {
    const kinds = Object.entries(long.kinds || {})
      .map(([k, n]) => `<span class="mem-chip">${esc(k)} ${n}</span>`)
      .join("");
    const recentRows = (long.recent || []).slice(0, 12);
    const topRows = (long.top || []).filter((r) => r.hits > 0).slice(0, 5);
    parts.push(
      card(
        `<div class="memtitle2">长期记忆<span class="mem-sub">${long.total} 条</span></div>` +
          `<div class="mem-chips">${kinds}</div>` +
          recentRows
            .map(
              (it) =>
                `<div class="mem-item"><div class="m-text">${esc(it.content)}</div>
                 <div class="m-meta">${esc(it.kind || "chat")}${it.created ? " · " + esc(it.created) : ""}</div></div>`
            )
            .join("") +
          (topRows.length
            ? `<div class="mem-sub2">被想起最多的</div>` +
              topRows
                .map(
                  (it) =>
                    `<div class="mem-item"><div class="m-text">${esc(it.content)}</div>
                     <div class="m-meta">想起 ${it.hits} 次</div></div>`
                )
                .join("")
            : "")
      )
    );
  }

  box.innerHTML = parts.join("");
}

/* ---------------- 书库 ---------------- */

function renderBooks() {
  const s = state.snap || {};
  const notes = s.notes || [];
  const books = s.books || [];
  const box = $("bookList");
  if (!box) return;
  const noteCount = notes.reduce((a, b) => a + (b.count || 0), 0);
  $("booksHint").textContent = noteCount
    ? "笔记是它想写才写的，独立存放，不进入对话记忆。"
    : "它还没写过读书笔记——不写也正常。";
  $("booksMeta").innerHTML = `${books.length} 本<br>${noteCount} 条笔记`;

  const rows = books
    .map(
      (b) =>
        `<div class="memline">《${esc(b.book)}》 ${b.percent || 0}%${
          b.total ? `（${b.pos || 0}/${b.total} 字）` : ""
        }</div>`
    )
    .join("");

  const noteBox = notes
    .map(
      (n) => `<div class="card memsec">
        <div class="memtitle2">《${esc(n.book)}》 · ${n.count} 条笔记</div>
        ${n.items
          .slice()
          .reverse()
          .map((it) => `<div class="memline"><span class="tiny">${esc(it.time)}</span> ${esc(it.content)}</div>`)
          .join("")}
      </div>`
    )
    .join("");

  box.innerHTML =
    `<div class="card memsec"><div class="memtitle2">阅读进度</div>${rows || '<div class="memline">书架是空的</div>'}</div>` +
    noteBox;
}

/* ---------------- 日记 ---------------- */

function filtered() {
  const s = state.snap;
  if (!s) return [];
  let list = s.journal;
  if (state.filter === "feeling") list = list.filter((e) => e.kind === "self" || e.kind === "dialogue");
  else if (state.filter === "self") list = list.filter((e) => e.kind === "self");
  else if (state.filter === "dialogue") list = list.filter((e) => e.kind === "dialogue");
  if (state.starredOnly) list = list.filter((e) => state.stars[e.id]);
  if (state.day) list = list.filter((e) => e.date === state.day);
  const q = state.query.trim().toLowerCase();
  if (q) list = list.filter((e) => e.content.toLowerCase().includes(q));
  return list;
}

function dayTitle(date) {
  const today = new Date();
  const ymd = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  const rel = date === ymd(today) ? "今天" : date === ymd(y) ? "昨天" : "";
  const dt = new Date(date + "T00:00:00");
  const week = "日一二三四五六"[dt.getDay()];
  return { main: date.replace(/-/g, "."), rel: rel || `周${week}` };
}

function renderJournal() {
  const all = filtered();
  const limit = state.limit || all.length;
  const list = all.slice(0, limit);
  const box = $("jlist");
  const now = Date.now() / 1000;

  if (!all.length) {
    box.innerHTML = "";
    $("jempty").classList.remove("hidden");
    $("jempty").textContent = state.starredOnly
      ? "还没有标星的日记。点日记右下角的 ★ 就能留下。"
      : state.query
      ? "没有找到包含这几个字的日记。"
      : "这里还没有符合条件的内容。";
    return;
  }
  $("jempty").classList.add("hidden");

  const moments = ((state.snap && state.snap.moments) || []).slice(0, 6);
  const showMoments = moments.length && !state.day && !state.query;
  const groups = new Map();
  for (const e of list) {
    if (showMoments && e.own_kind === "moment") continue;
    if (!groups.has(e.date)) groups.set(e.date, []);
    groups.get(e.date).push(e);
  }

  let html = "";
  if (showMoments) {
    html += `<div class="card moments"><div class="memtitle2">重要时刻<span class="mem-sub">共 ${moments.length} 条</span></div>` +
      moments.map((e) => {
        const span = e.span_start ? `${e.span_start}${e.span_end && e.span_end !== e.span_start ? " → " + e.span_end : ""}` : e.date;
        return `<div class="moment-item"><div class="m-span">${esc(span)}</div><div class="m-body">${esc(e.content)}</div></div>`;
      }).join("") + `</div>`;
  }
  for (const [date, items] of groups) {
    const t = dayTitle(date);
    html += `<div class="daygroup">
      <div class="dayhead">
        <span class="daydate">${esc(t.main)}</span>
        <span class="dayrel">${esc(t.rel)}</span>
        <span class="daycount">${items.length} 条</span>
      </div>`;
    for (const e of items) {
      const fresh = now - e.ts < 600 ? " fresh" : "";
      const open = state.openIds.has(e.id) ? " open" : "";
      const starred = state.stars[e.id] ? " on" : "";
      const sel = state.selected === e.id ? " selected" : "";
      const longEnough = e.chars > 110;
      html += `<article class="entry${fresh}${open}${sel}" data-id="${e.id}">
        <div class="ehead">
          <span class="etime">${esc(e.clock)}</span>
          <span class="tag ${e.own_kind || e.kind}">${OWN_KIND_LABEL[e.own_kind] || KIND_LABEL[e.kind] || "记录"}</span>          ${e.importance >= 3 ? `<span class="imp">重要</span>` : ""}
          ${e.duplicates > 1 ? `<span class="emore">原文里有 ${e.duplicates} 条相同</span>` : ""}
          <button class="starbtn${starred}" data-star="${e.id}" title="标星（只存在本程序里）">★</button>
        </div>
        <div class="econtent" data-open="${e.id}">${highlight(e.content, state.query)}</div>
        <div class="efoot">
          <span class="emore">${e.chars} 字</span>
          ${longEnough ? `<button class="ghost" data-expand="${e.id}">${state.openIds.has(e.id) ? "收起" : "展开全文"}</button>` : ""}
        </div>
      </article>`;
    }
    html += `</div>`;
  }

  if (all.length > limit) {
    html += `<div class="morewrap"><button class="ghost" id="btnMore">再显示 ${Math.min(
      state.pageSize || 60,
      all.length - limit
    )} 条（还有 ${all.length - limit} 条）</button></div>`;
  }
  box.innerHTML = html;
  renderShell();

  const more = $("btnMore");
  if (more) {
    more.addEventListener("click", () => {
      state.limit = limit + (state.pageSize || 60);
      renderJournal();
    });
  }
}

/* ---------------- 交互 ---------------- */

function showDetail(id) {
  const e = state.snap.journal.find((x) => x.id === id);
  if (!e) return;
  state.detailId = id;
  $("dTime").textContent = e.time;
  $("dKind").textContent = (KIND_LABEL[e.kind] || "记录") + (e.duplicates > 1 ? ` · 原文里出现 ${e.duplicates} 次` : "");
  $("dBody").textContent = e.content;
  $("dFoot").textContent = `${e.chars} 字 · 来源：journal.jsonl（只读）`;
  const btn = $("dStar");
  btn.textContent = state.stars[id] ? "★ 已标星" : "★ 标星";
  btn.classList.toggle("on", !!state.stars[id]);

  const st = state.stars[id];
  const noteBox = $("dNoteBox");
  if (st) {
    noteBox.classList.remove("hidden");
    $("dNote").value = st.note || "";
    $("dNoteHint").textContent = st.starred_at ? `标星于 ${st.starred_at}` : "";
  } else {
    noteBox.classList.add("hidden");
  }
  $("overlay").classList.remove("hidden");
}

async function saveNote() {
  if (!state.detailId) return;
  const id = state.detailId;
  try {
    const r = await fetch("/api/note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, note: $("dNote").value }),
    });
    const data = await r.json();
    if (data.ok) {
      state.stars = data.stars || {};
      $("dNoteHint").textContent = "已保存 " + new Date().toLocaleTimeString("zh-CN", { hour12: false });
      renderJournal();
    } else {
      $("dNoteHint").textContent = data.error || "保存失败";
    }
  } catch (e) {
    $("dNoteHint").textContent = "保存失败：" + e.message;
  }
}

async function toggleStar(id) {
  const e = state.snap.journal.find((x) => x.id === id);
  if (!e) return;
  try {
    const r = await postStar({ id, time: e.time, preview: e.content.slice(0, 60) });
    if (r && r.ok) {
      state.stars = r.stars || {};
      document.querySelectorAll(`[data-star="${id}"]`).forEach((b) => b.classList.toggle("on", !!state.stars[id]));
      if (!$("overlay").classList.contains("hidden")) showDetail(id);
      renderJournal();
    }
  } catch (e2) {}
}

function setView(v) {
  state.view = v;
  document.querySelectorAll(".navitem").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("viewHome").classList.toggle("hidden", v !== "home");
  $("viewJournal").classList.toggle("hidden", v !== "journal");
  $("viewMemory").classList.toggle("hidden", v !== "memory");
  $("viewBooks").classList.toggle("hidden", v !== "books");
  renderShell();
  if (v === "home") renderHome();
  else if (v === "memory") renderMemory();
  else if (v === "books") renderBooks();
  else renderJournal();
}

/* 日历 */
const cal = { month: new Date() };

function renderCal() {
  const days = new Map();
  (state.snap ? state.snap.journal : []).forEach((e) => days.set(e.date, (days.get(e.date) || 0) + 1));
  const y = cal.month.getFullYear();
  const m = cal.month.getMonth();
  $("calTitle").textContent = `${y} 年 ${m + 1} 月`;
  const first = new Date(y, m, 1);
  const offset = (first.getDay() + 6) % 7;
  const total = new Date(y, m + 1, 0).getDate();
  const todayStr = new Date().toLocaleDateString("sv-SE");

  let html = "";
  for (let i = 0; i < offset; i++) html += `<div class="calday blank"></div>`;
  for (let d = 1; d <= total; d++) {
    const ds = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const cls = ["calday"];
    if (days.has(ds)) cls.push("has");
    if (state.day === ds) cls.push("sel");
    if (ds === todayStr) cls.push("today");
    html += `<div class="${cls.join(" ")}" ${days.has(ds) ? `data-day="${ds}"` : ""} title="${days.get(ds) || 0} 条">${d}</div>`;
  }
  $("calgrid").innerHTML = html;
}

function openCal(anchor) {
  const pop = $("calpop");
  const rect = anchor.getBoundingClientRect();
  pop.classList.remove("hidden");
  renderCal();
  const w = 268;
  pop.style.left = Math.min(window.innerWidth - w - 14, Math.max(14, rect.right - w)) + "px";
  pop.style.top = rect.bottom + 8 + "px";
}

/* 诊断面板 */
async function openDiag() {
  $("diagOverlay").classList.remove("hidden");
  $("diagBody").innerHTML = `<div class="dimg">读取中…</div>`;
  try {
    const d = await getDiag();
    const rows = d.paths
      .map(
        (p) =>
          `<tr><td>${esc(p.label)}</td><td class="${p.exists ? "ok" : "bad"}">${
            p.exists ? "存在" : "缺失"
          }</td><td class="mono">${esc(p.mtime || "—")}</td><td class="mono small">${esc(p.path)}</td></tr>`
      )
      .join("");
    const log = (d.log || []).map((l) => `<div>${esc(l)}</div>`).join("") || "<div>（暂无日志）</div>";
    $("diagBody").innerHTML = `
      <div class="dsec">
        <div class="dhead">概况</div>
        <div class="dgrid">
          <span>版本</span><b>${esc(d.version)}</b>
          <span>启动于</span><b>${esc(d.started_at)}（已运行 ${d.uptime_sec}s）</b>
          <span>Python</span><b>${esc(d.python)}</b>
          <span>程序目录</span><b class="mono small">${esc(d.base)}</b>
          <span>监测目标</span><b class="mono small">${esc(d.bot_root)}</b>
          <span>请求次数</span><b>${d.hits}</b>
        </div>
      </div>
      <div class="dsec">
        <div class="dhead">数据文件</div>
        <table class="dtable"><tbody>${rows}</tbody></table>
      </div>
      <div class="dsec">
        <div class="dhead">当前设置</div>
        <div class="dgrid">${Object.entries(d.settings || {})
          .filter(([k]) => !k.startsWith("_"))
          .map(([k, v]) => `<span>${esc(k)}</span><b>${esc(v)}</b>`)
          .join("")}</div>
      </div>
      <div class="dsec">
        <div class="dhead">监测目录</div>
        <div class="dgrid">
          <span>当前</span><b class="mono small">${esc(d.bot_root || "—")}</b>
          <span>来源</span><b>${esc(d.root_source === "settings" ? "自己设置的" : d.root_source === "env" ? "环境变量" : "默认值")}</b>
          <span>可用</span><b class="${d.root_usable ? "ok" : "bad"}">${d.root_usable ? "正常" : "找不到数据"}</b>
        </div>
        <button class="ghost" id="btnChangeRoot" style="margin-top:10px">更改路径</button>
      </div>
      <div class="dsec">
        <div class="dhead">最近日志</div>
        <div class="dlog">${log}</div>
      </div>
      <div class="dsec">
        <div class="dhead">界面自检</div>
        <button class="ghost" id="btnUiTest">运行界面自检</button>
        <div id="uiTestResult" style="margin-top:10px"></div>
      </div>`;
    $("btnUiTest").addEventListener("click", renderUiTest);
    const changer = $("btnChangeRoot");
    if (changer) {
      changer.addEventListener("click", () => {
        $("diagOverlay").classList.add("hidden");
        $("setupPath").value = (state.snap.setup || {}).bot_root || "";
        $("setupMsg").textContent = "";
        $("setupOverlay").classList.remove("hidden");
        $("setupPath").focus();
      });
    }
  } catch (e) {
    $("diagBody").innerHTML = `<div class="dimg">读取失败：${esc(e.message)}</div>`;
  }
}

/* 界面自检：真的派发按键/点击，检查结果 */
async function uiSelfTest() {
  const results = [];
  const t = (name, fn) => {
    try {
      const detail = fn();
      results.push({ name, ok: true, detail: detail || "" });
    } catch (e) {
      results.push({ name, ok: false, detail: String(e.message || e) });
    }
  };
  const key = (k) => document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));

  const prevView = state.view;
  const prevQuery = state.query;

  setView("journal");
  state.selected = null;
  state.query = "";
  state.limit = state.pageSize || 60;
  renderJournal();

  t("列表已渲染", () => {
    const n = document.querySelectorAll(".entry").length;
    if (!n) throw new Error("没有渲染出任何条目");
    return `${n} 条`;
  });

  t("记忆健康面板", () => {
    const h = (state.snap && state.snap.memory && state.snap.memory.health) || null;
    if (!h) return "本机没有健康数据，跳过";
    setView("memory");
    const rows = document.querySelectorAll(".health-row").length;
    const text = document.querySelector(".health") ? document.querySelector(".health").textContent : "";
    setView("journal");
    if (rows < 4) throw new Error("健康行太少：" + rows);
    if (!text.includes("每晚整理")) throw new Error("缺少整理状态");
    return rows + " 行";
  });

  t("重要时刻置顶", () => {
    const m = (state.snap && state.snap.moments) || [];
    const card = document.querySelector(".moments");
    if (!m.length) return "本机暂无重要时刻，跳过";
    if (!card) throw new Error("有重要时刻但没有置顶块");
    if (!card.textContent.includes("重要时刻")) throw new Error("置顶块标题不对");
    return `${m.length} 条`;
  });

  t("标签用他自己的分类", () => {
    const labels = Array.from(document.querySelectorAll(".entry .tag")).map((x) => x.textContent.trim());
    const own = labels.filter((x) => ["事实", "感受", "事件", "重要时刻"].includes(x));
    if (!own.length) return "本机暂无新字段，跳过";
    return own.slice(0, 3).join(" / ");
  });

  t("正文字体清晰", () => {
    const el = document.querySelector(".econtent");
    if (!el) throw new Error("找不到日记正文");
    const cs = getComputedStyle(el);
    const fam = cs.fontFamily || "";
    if (/SimSun|Songti|STSong/i.test(fam)) throw new Error("仍是衬线字体：" + fam);
    if (!/YaHei|Segoe/i.test(fam)) throw new Error("字体不符合预期：" + fam);
    const fs = parseFloat(cs.fontSize);
    if (!(fs >= 15)) throw new Error("正文字号偏小：" + fs + "px");
    const lh = parseFloat(cs.lineHeight);
    if (!lh || lh / fs < 1.7) throw new Error("行高偏紧：" + lh);
    return fs + "px / " + Math.round(lh) + "px";
  });

  t("J 选中下一条", () => {
    key("j");
    if (!state.selected) throw new Error("按下 J 后没有选中项");
    if (!document.querySelector(".entry.selected")) throw new Error("没有 .selected 样式");
    return state.selected;
  });

  t("K 回到上一条", () => {
    const first = state.selected;
    key("j");
    key("k");
    if (state.selected !== first) throw new Error("K 没有回到上一条");
    return state.selected;
  });

  t("Enter 打开详情", () => {
    key("Enter");
    if ($("overlay").classList.contains("hidden")) throw new Error("详情没有打开");
    const body = $("dBody").textContent;
    if (!body) throw new Error("详情内容为空");
    return body.slice(0, 18) + "…";
  });

  $("overlay").classList.add("hidden");

  t("搜索高亮", () => {
    const visible = filtered();
    if (!visible.length) return "当前筛选下没有条目，跳过";
    const sample = visible[0].content;
    const start = Math.max(0, Math.floor(sample.length / 2) - 1);
    const word = sample.slice(start, start + 2);
    state.query = word;
    renderJournal();
    const marks = document.querySelectorAll("#jlist mark").length;
    const shown = document.querySelectorAll(".entry").length;
    state.query = "";
    renderJournal();
    if (!shown) throw new Error(`搜索「${word}」后列表为空`);
    if (!marks) throw new Error(`搜索「${word}」没有高亮`);
    return `${marks} 处`;
  });

  t("分页按钮", () => {
    if (state.snap.journal.length < 3) return "数据太少，无法验证分页";
    const savedLimit = state.limit;
    const savedSize = state.pageSize;
    const savedFilter = state.filter;
    state.filter = "all";
    state.limit = 2;
    state.pageSize = 2;
    renderJournal();
    const before = document.querySelectorAll(".entry").length;
    const btn = $("btnMore");
    if (!btn) throw new Error("应有「加载更多」按钮但没有");
    btn.click();
    const after = document.querySelectorAll(".entry").length;
    if (after <= before) throw new Error(`点击后条数没有增加（${before} → ${after}）`);
    state.filter = savedFilter;
    state.limit = savedLimit;
    state.pageSize = savedSize;
    renderJournal();
    return `${before} → ${after}`;
  });

  let starResult = null;
  t("S 标星", () => {
    const id = state.selected;
    if (!id) throw new Error("没有选中项");
    key("s");
    return "已派发";
  });
  // 等待异步写入完成
  await new Promise((r) => setTimeout(r, 400));
  t("标星状态已回写", () => {
    const id = state.selected;
    if (!state.stars[id]) throw new Error("星标没有写入");
    starResult = id;
    return "已标星";
  });
  t("再按 S 取消", () => {
    key("s");
    return "已派发";
  });
  await new Promise((r) => setTimeout(r, 400));
  t("星标已撤销", () => {
    if (state.stars[starResult]) throw new Error("星标没有取消");
    return "已恢复原状";
  });

  t("关窗说明可见", () => {
    const hint = $("trayHint");
    if (!hint) throw new Error("设置里没有关窗行为说明");
    if (!hint.textContent.includes("重启")) throw new Error("说明里没提重启生效");
    return hint.textContent.trim();
  });

  t("名字相关文案不提机器人", () => {
    const s = document.querySelector("#settingsPop").textContent || "";
    const u = document.querySelector("#setupOverlay").textContent || "";
    if (s.includes("机器人")) throw new Error("设置面板里还有“机器人”");
    if (u.includes("机器人")) throw new Error("首次设置里还有“机器人”");
    if (!s.includes("他的名字")) throw new Error("设置面板没写“他的名字”");
    return "文案干净";
  });

  t("机器人名字生效", () => {
    if (!$("setupName")) throw new Error("首次设置里没有名字输入框");
    if (!$("nameInput")) throw new Error("设置面板里没有名字输入框");
    const old = state.snap.bot_name;
    state.snap.bot_name = "测试名字";
    renderShell();
    const shown = $("bname").textContent;
    state.snap.bot_name = old;
    renderShell();
    if (shown !== "测试名字") throw new Error("侧栏没跟着变：" + shown);
    return shown;
  });

  t("阅读总览渲染", () => {
    const rows = document.querySelectorAll("#bookRows .bookrow").length;
    const sessions = $("rsSessions").textContent.trim();
    const chars = $("rsChars").textContent.trim();
    if (!rows) throw new Error("没有按书分开的行");
    if (!sessions || sessions === "0") throw new Error("累计次数为 0");
    if (!chars || chars === "0") throw new Error("累计字数为 0");
    return rows + " 本 · " + sessions + " 次 · " + chars + " 字";
  });

  t("设置面板可打开", () => {
    $("btnSettings").click();
    if ($("settingsPop").classList.contains("hidden")) throw new Error("点了设置没打开");
    const cards = document.querySelectorAll("#themeGrid .theme-card").length;
    if (cards !== 3) throw new Error("主题选项数量不对：" + cards);
    $("btnSettings").click();
    return cards + " 个主题";
  });

  t("切换到纯白生效", () => {
    applyTheme("white", true);
    const canvas = getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim();
    if (document.documentElement.dataset.theme !== "white") throw new Error("主题属性没变");
    const m = canvas.match(/^#([0-9a-f]{6})$/i);
    if (!m) throw new Error("浅色底不是实色：" + canvas);
    const r = parseInt(m[1].slice(0, 2), 16);
    const g = parseInt(m[1].slice(2, 4), 16);
    const b = parseInt(m[1].slice(4, 6), 16);
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    if (lum < 0.8) throw new Error("浅色底太暗：" + canvas);
    if (lum > 0.95) throw new Error("浅色底太刺眼：" + canvas);
    return canvas + " · 亮度 " + lum.toFixed(2);
  });

  t("三套主题彼此不同", () => {
    const read = (name) => {
      applyTheme(name, true);
      return getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim();
    };
    const a = read("xuantan");
    const b = read("black");
    const c = read("white");
    applyTheme("xuantan", true);
    if (a === b || b === c || a === c) throw new Error("主题底色重复：" + [a, b, c].join(" / "));
    return [a, b, c].join(" / ");
  });

  t("切回玄潭黑生效", () => {
    applyTheme("xuantan", true);
    const canvas = getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim();
    if (!document.documentElement.dataset.theme.startsWith("xuantan")) throw new Error("没切回玄潭黑");
    if (!canvas.includes("rgba")) throw new Error("透明底不是 rgba：" + canvas);
    return canvas;
  });

  t("透明质感（半透明 + 模糊）", () => {
    const root = getComputedStyle(document.documentElement);
    const glass = root.getPropertyValue("--glass-2").trim();
    const m = glass.match(/rgba?\(([^)]+)\)/);
    const parts = m ? m[1].split(",").map((x) => parseFloat(x)) : [];
    const alpha = parts.length === 4 ? parts[3] : 1;
    if (!(alpha > 0 && alpha < 1)) throw new Error("面板不是半透明：" + glass);
    const card = document.querySelector(".card");
    if (!card) throw new Error("找不到卡片");
    const cs = getComputedStyle(card);
    const bf = cs.backdropFilter || cs.webkitBackdropFilter;
    if (!bf || bf === "none") throw new Error("没有背景模糊");
    if (!/blur\(/.test(bf)) throw new Error("模糊值异常：" + bf);
    return "alpha=" + alpha + " · " + bf;
  });

  state.query = prevQuery;
  $("search").value = prevQuery;
  setView(prevView);
  return results;
}

async function renderUiTest() {
  const box = $("uiTestResult");
  box.innerHTML = `<div class="dimg">正在自检…</div>`;
  const results = await uiSelfTest();
  const failed = results.filter((r) => !r.ok).length;
  box.innerHTML =
    `<div class="dhead">界面自检 · ${failed ? `<span class="bad">${failed} 项失败</span>` : `<span class="ok">全部通过</span>`}</div>` +
    `<table class="dtable"><tbody>` +
    results
      .map(
        (r) =>
          `<tr><td class="${r.ok ? "ok" : "bad"}">${r.ok ? "通过" : "失败"}</td><td>${esc(r.name)}</td>` +
          `<td class="mono small">${esc(r.detail)}</td></tr>`
      )
      .join("") +
    `</tbody></table>`;

  // 把结果落盘，方便不开窗口也能核对
  try {
    await fetch("/api/uitest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ results }),
    });
  } catch (e) {}
}

/* 复制 */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  }
}

/* ---------------- 事件绑定 ---------------- */

function bind() {
  document.querySelectorAll(".navitem").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  $("btnRefresh").addEventListener("click", () => load(true));

  $("chips").addEventListener("click", (ev) => {
    const b = ev.target.closest(".chip");
    if (!b) return;
    state.filter = b.dataset.filter;
    state.limit = state.pageSize || 60;
    document.querySelectorAll("#chips .chip").forEach((x) => x.classList.toggle("active", x === b));
    renderJournal();
  });

  $("search").addEventListener("input", (ev) => {
    state.query = ev.target.value;
    state.limit = state.pageSize || 60;
    renderJournal();
  });

  $("btnStarred").addEventListener("click", () => {
    state.starredOnly = !state.starredOnly;
    state.limit = state.pageSize || 60;
    $("btnStarred").classList.toggle("on", state.starredOnly);
    renderJournal();
  });

  $("btnCal").addEventListener("click", (ev) => {
    if ($("calpop").classList.contains("hidden")) openCal(ev.currentTarget);
    else $("calpop").classList.add("hidden");
  });

  $("calPrev").addEventListener("click", () => {
    cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() - 1, 1);
    renderCal();
  });
  $("calNext").addEventListener("click", () => {
    cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() + 1, 1);
    renderCal();
  });
  $("calgrid").addEventListener("click", (ev) => {
    const d = ev.target.closest("[data-day]");
    if (!d) return;
    state.day = d.dataset.day;
    state.limit = state.pageSize || 60;
    $("dayFilterText").textContent = "只看 " + state.day.replace(/-/g, ".");
    $("dayFilter").classList.remove("hidden");
    $("calpop").classList.add("hidden");
    renderJournal();
  });
  $("btnClearDay").addEventListener("click", () => {
    state.day = null;
    $("dayFilter").classList.add("hidden");
    renderJournal();
  });

  $("jlist").addEventListener("click", (ev) => {
    const star = ev.target.closest("[data-star]");
    if (star) {
      toggleStar(star.dataset.star);
      return;
    }
    const exp = ev.target.closest("[data-expand]");
    if (exp) {
      const id = exp.dataset.expand;
      if (state.openIds.has(id)) state.openIds.delete(id);
      else state.openIds.add(id);
      renderJournal();
      return;
    }
    const open = ev.target.closest("[data-open]");
    if (open) showDetail(open.dataset.open);
  });

  $("dClose").addEventListener("click", () => $("overlay").classList.add("hidden"));
  $("overlay").addEventListener("click", (ev) => {
    if (ev.target === $("overlay")) $("overlay").classList.add("hidden");
  });
  $("dStar").addEventListener("click", () => state.detailId && toggleStar(state.detailId));
  $("dNoteSave").addEventListener("click", saveNote);

  $("topicList").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-word]");
    if (!b) return;
    state.query = b.dataset.word;
    state.limit = state.pageSize || 60;
    $("search").value = state.query;
    setView("journal");
  });
  $("dCopy").addEventListener("click", async () => {
    const ok = await copyText($("dBody").textContent);
    $("dCopy").textContent = ok ? "已复制" : "复制失败";
    setTimeout(() => ($("dCopy").textContent = "复制"), 1400);
  });

  $("diagClose").addEventListener("click", () => $("diagOverlay").classList.add("hidden"));

  // 左下角设置：主题与透明
  const closeSettings = () => {
    $("settingsPop").classList.add("hidden");
    $("btnSettings").classList.remove("open");
  };
  $("btnSettings").addEventListener("click", (ev) => {
    ev.stopPropagation();
    const willOpen = $("settingsPop").classList.contains("hidden");
    $("settingsPop").classList.toggle("hidden", !willOpen);
    $("btnSettings").classList.toggle("open", willOpen);
  });
  $("themeGrid").addEventListener("click", (ev) => {
    const card = ev.target.closest("[data-pick]");
    if (!card) return;
    saveTheme(card.dataset.pick, $("switchTransparent").classList.contains("on"));
  });
  const saveName = async () => {
    const name = $("nameInput").value.trim();
    if (!name) return;
    try {
      const r = await fetch("/api/name", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name }),
      });
      const d = await r.json();
      if (d.ok) {
        state.snap.bot_name = d.bot_name;
        renderShell();
      }
    } catch (e) {}
  };
  $("switchTray").addEventListener("click", async (ev) => {
    ev.stopPropagation();
    const next = !$("switchTray").classList.contains("on");
    $("switchTray").classList.toggle("on", next);
    try {
      await fetch("/api/prefs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ close_to_tray: next }),
      });
    } catch (e) {}
  });

  $("nameInput").addEventListener("change", saveName);
  $("nameInput").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); saveName(); }
  });

  $("switchTransparent").addEventListener("click", (ev) => {
    ev.stopPropagation();
    saveTheme(currentTheme(), !$("switchTransparent").classList.contains("on"));
  });
  document.addEventListener("click", (ev) => {
    if ($("settingsPop").classList.contains("hidden")) return;
    if (ev.target.closest("#settingsPop") || ev.target.closest("#btnSettings")) return;
    closeSettings();
  });

  // 首次运行：设置监测目录
  const doSetup = async () => {
    const name = $("setupName").value.trim();
    const pathVal = $("setupPath").value.trim();
    const needPath = !$("pathBlock").classList.contains("hidden");
    if (!name) {
      $("setupMsg").textContent = "先给他起个名字";
      return;
    }
    if (needPath && !pathVal) {
      $("setupMsg").textContent = "请先填一个数据目录";
      return;
    }
    $("setupMsg").textContent = "保存中…";
    try {
      const rn = await fetch("/api/name", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name }),
      });
      const dn = await rn.json();
      if (!dn.ok) {
        $("setupMsg").textContent = dn.error || "名字没保存成功";
        return;
      }
      if (needPath) {
        const r = await fetch("/api/setup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: pathVal }),
        });
        const d = await r.json();
        if (!d.ok) {
          $("setupMsg").textContent = d.error || "没认出来这个路径";
          return;
        }
      }
      $("setupMsg").textContent = "";
      $("setupOverlay").classList.add("hidden");
      state.limit = 0;
      await load(true);
    } catch (e) {
      $("setupMsg").textContent = "请求失败：" + e.message;
    }
  };
  $("setupSave").addEventListener("click", doSetup);
  $("setupPath").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") doSetup();
  });
  $("diagOverlay").addEventListener("click", (ev) => {
    if (ev.target === $("diagOverlay")) $("diagOverlay").classList.add("hidden");
  });

  // 连点头像 5 次打开诊断面板
  let taps = 0;
  let tapTimer = null;
  $("brandAvatar").addEventListener("click", () => {
    taps += 1;
    if (tapTimer) clearTimeout(tapTimer);
    tapTimer = setTimeout(() => (taps = 0), 1200);
    if (taps >= 5) {
      taps = 0;
      openDiag();
    }
  });

  document.addEventListener("click", (ev) => {
    if (!$("calpop").classList.contains("hidden") && !ev.target.closest("#calpop") && !ev.target.closest("#btnCal")) {
      $("calpop").classList.add("hidden");
    }
  });

  document.addEventListener("keydown", (ev) => {
    const typing = ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA");

    if (ev.key === "Escape") {
      $("settingsPop").classList.add("hidden");
      $("btnSettings").classList.remove("open");
      $("overlay").classList.add("hidden");
      $("diagOverlay").classList.add("hidden");
      $("calpop").classList.add("hidden");
      if (typing) ev.target.blur();
      return;
    }

    if ((ev.ctrlKey || ev.metaKey) && ev.key === "f") {
      ev.preventDefault();
      if (state.view !== "journal") setView("journal");
      $("search").focus();
      return;
    }

    if (typing) return;

    if (ev.key === "g" || ev.key === "G") {
      const view = state.view === "home" ? $("viewHome") : $("viewJournal");
      view.scrollTop = 0;
      return;
    }

    if (state.view !== "journal") return;

    const pinnedMoments = ((state.snap && state.snap.moments) || []).length > 0 && !state.day && !state.query;
    const list = filtered()
      .filter((e) => !(pinnedMoments && e.own_kind === "moment"))
      .slice(0, state.limit || 9999);
    if (!list.length) return;
    const idx = list.findIndex((e) => e.id === state.selected);

    if (ev.key === "j" || ev.key === "J" || ev.key === "ArrowDown") {
      ev.preventDefault();
      const next = list[Math.min(list.length - 1, idx < 0 ? 0 : idx + 1)];
      state.selected = next.id;
      renderJournal();
      const el = document.querySelector(`.entry[data-id="${next.id}"]`);
      if (el) el.scrollIntoView({ block: "nearest" });
      return;
    }
    if (ev.key === "k" || ev.key === "K" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const prev = list[Math.max(0, idx < 0 ? 0 : idx - 1)];
      state.selected = prev.id;
      renderJournal();
      const el = document.querySelector(`.entry[data-id="${prev.id}"]`);
      if (el) el.scrollIntoView({ block: "nearest" });
      return;
    }
    if (ev.key === "Enter" && state.selected) {
      ev.preventDefault();
      showDetail(state.selected);
      return;
    }
    if ((ev.key === "s" || ev.key === "S") && state.selected) {
      ev.preventDefault();
      toggleStar(state.selected);
    }
  });

  window.addEventListener("resize", () => $("calpop").classList.add("hidden"));
}

function boot() {
  bind();
  const raw = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  const [view, qs] = raw.split("?");
  const params = new URLSearchParams(qs || "");
  if (view === "journal" || view === "memory") setView(view);
  if (params.get("q")) {
    state.query = params.get("q");
    $("search").value = state.query;
  }
  if (view === "diag") setTimeout(openDiag, 600);

  scheduleRefresh();
  load(true).then(() => {
    scheduleRefresh();
    if (state.query) renderJournal();
    if (view === "diag" && params.get("selftest")) {
      setTimeout(async () => {
        await openDiag();
        // 自检模式只留结果，方便一眼看完
        $("diagBody").innerHTML =
          `<div class="dsec"><div class="dhead">界面自检</div><div id="uiTestResult"></div></div>`;
        renderUiTest();
      }, 900);
    }
  });
}

boot();
