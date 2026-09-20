/* TermuxYoutube — фронт (1:1 YouTube Mobile).
   Нижний бар: Главная / Очередь / + (Настройки — по шестерёнке в шапке).
   Данные библиотеки — REST (/api/library|tracks|detail|cover), очередь — SSE. */

const E = (id) => document.getElementById(id);
const api = async (path, body) => {
  try {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    return await r.json();
  } catch (_) { return { ok: false, msg: "нет связи с сервером — запусти его заново" }; }
};
const apiGet = async (p) => { try { return await (await fetch(p)).json(); } catch (_) { return null; } };

let state = null, inited = false, sliderDrag = false;
const cards = new Map();
let libLimit = 25, libFilter = "recent", flatTracks = null;
const libState = { list: [], detail: null, key: null };

// ─────────── helpers ───────────
function plur(n, one, few, many) { const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return one; if (a >= 2 && a <= 4 && (b < 10 || b >= 20)) return few; return many; }
const trkPlur = (n) => plur(n, "трек", "трека", "треков");
function fmtSize(b) { if (!b) return "0 МБ"; const mb = b / 1048576; return mb >= 1024 ? (mb / 1024).toFixed(1) + " ГБ" : Math.round(mb) + " МБ"; }
function fmtDur(s) { if (!s) return ""; s = Math.round(s); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
function deriveAuthor(t) { const p = (t || "").split(/\s[-–—]\s/); return p.length >= 2 ? p[0].trim() : ""; }
const covUrl = (key, file) => "/api/cover?pl=" + encodeURIComponent(key) + (file ? "&file=" + encodeURIComponent(file) : "");
function setCover(el, url) { const img = new Image(); img.className = "cover-img"; img.onload = () => { el.textContent = ""; el.appendChild(img); }; img.src = url; }
function t169(key, file, dur) {
  const d = document.createElement("div"); d.className = "t169"; d.textContent = "♪";
  setCover(d, covUrl(key, file));
  if (dur) { const s = document.createElement("span"); s.className = "dur"; s.textContent = fmtDur(dur); d.appendChild(s); }
  return d;
}
function badge(status) { if (status === "partially_downloaded") return { c: "part", t: "частично" };
  if (status === "cancelled") return { c: "canc", t: "отменён" }; return null; }
const SVG_TRASH = '<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>';
const SVG_DLDONE = '<svg viewBox="0 0 24 24" width="21" height="21" fill="currentColor"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm-1.2 14.2L6.5 12l1.4-1.4 2.9 2.9 5.3-5.3L17.5 9.6l-6.7 6.6z"/></svg>';

// ─────────── навигация (табы) ───────────
function showTab(name) {
  document.body.dataset.tab = name;
  ["home", "queue", "settings"].forEach((t) => { E("s-" + t).hidden = (t !== name); });
  E("s-detail").hidden = true;
  document.querySelectorAll(".tab[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  if (name === "home") loadLibrary();
}
document.querySelectorAll(".tab[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
E("gearBtn").addEventListener("click", () => showTab("settings"));
E("setBack").addEventListener("click", () => showTab("home"));

// ─────────── + / вставка ───────────
E("addBtn").addEventListener("click", () => { showTab("queue"); doPaste(); });
E("pasteBtn").addEventListener("click", doPaste);
async function doPaste() {
  let url = ""; try { url = (await navigator.clipboard.readText() || "").trim(); } catch (_) {}
  if (!url) url = (prompt("Ссылка на плейлист / My Mix / список видео:") || "").trim();
  if (!url) return;
  const r = await api("/api/add", { url, limit: libLimit });
  if (!r.ok) hint(r.msg, "err"); else if (r.msg && r.msg !== "ok") hint(r.msg, "warn"); else hint("Добавлено ✓");
}
let hintT = null;
function hint(msg, level) { const h = E("pasteHint"); h.textContent = msg; h.className = "hint show" + (level ? " " + level : "");
  clearTimeout(hintT); hintT = setTimeout(() => h.classList.remove("show"), level === "warn" ? 5200 : 2600); }

// лимит-чипы — выбор запоминается (не сбрасывается на 25)
try { const v = +localStorage.getItem("ty-limit"); if (v) libLimit = v; } catch (_) {}
E("limitChips").querySelectorAll(".chip").forEach((c) => {
  c.classList.toggle("on", +c.dataset.n === libLimit);
  c.addEventListener("click", () => {
    E("limitChips").querySelectorAll(".chip").forEach((x) => x.classList.remove("on"));
    c.classList.add("on"); libLimit = +c.dataset.n;
    try { localStorage.setItem("ty-limit", libLimit); } catch (_) {}
  });
});

// ═════════ БИБЛИОТЕКА ═════════
E("libChips").addEventListener("click", (e) => {
  const c = e.target.closest("[data-f]"); if (!c) return;
  libFilter = c.dataset.f; E("libChips").querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === c));
  if (libFilter === "music" && flatTracks === null) loadTracks(); else renderLibrary();
});
async function loadLibrary() { const d = await apiGet("/api/library"); libState.list = (d && d.playlists) || []; renderLibrary(); }
async function loadTracks() { const d = await apiGet("/api/tracks"); flatTracks = (d && d.tracks) || []; renderLibrary(); }

function renderLibrary() {
  const music = libFilter === "music";
  E("histSec").hidden = music || libFilter === "playlists" || libState.list.length === 0;
  E("plList").hidden = music;
  E("trFlat").hidden = !music;
  E("libEmpty").hidden = libState.list.length > 0;

  if (!E("histSec").hidden) {
    const hs = E("histStrip"); hs.innerHTML = "";
    libState.list.filter((p) => p.count > 0).slice(0, 10).forEach((p) => {
      const c = document.createElement("div"); c.className = "hcard";
      c.appendChild(t169(p.key, null, null));
      const t = document.createElement("div"); t.className = "hc-title"; t.textContent = p.title;
      const s = document.createElement("div"); s.className = "hc-sub"; s.textContent = `${p.count} ${trkPlur(p.count)}`;
      c.append(t, s); c.addEventListener("click", () => openDetail(p.key)); hs.appendChild(c);
    });
  }

  if (music) { renderFlat(); return; }
  const ul = E("plList"); ul.innerHTML = "";
  for (const p of libState.list) {
    const li = document.createElement("li"); li.className = "pl-row";
    li.appendChild(t169(p.key, null, null));
    const m = document.createElement("div"); m.className = "pl-meta";
    const t = document.createElement("div"); t.className = "pl-title"; t.textContent = p.title;
    const s = document.createElement("div"); s.className = "pl-sub"; s.textContent = `${p.count} ${trkPlur(p.count)} · ${fmtSize(p.size)}`;
    m.append(t, s);
    const b = badge(p.status); if (b) { const el = document.createElement("span"); el.className = "badge " + b.c; el.textContent = b.t; m.appendChild(el); }
    li.appendChild(m);
    const menu = document.createElement("button"); menu.className = "pl-menu"; menu.textContent = "⋮"; li.appendChild(menu);
    li.addEventListener("click", () => openDetail(p.key));
    ul.appendChild(li);
  }
}
function renderFlat() {
  const ul = E("trFlat"); ul.innerHTML = "";
  if (!flatTracks) return;
  for (const t of flatTracks) {
    const li = document.createElement("li"); li.className = "tr";
    li.appendChild(t169(t.pl, t.file, t.duration));
    const m = document.createElement("div"); m.className = "tr-meta";
    const ti = document.createElement("div"); ti.className = "tr-title"; ti.textContent = t.title || t.file; m.appendChild(ti);
    const a = document.createElement("div"); a.className = "tr-author"; a.textContent = deriveAuthor(t.title || "") || t.pl_title; m.appendChild(a);
    const inf = document.createElement("div"); inf.className = "tr-info"; inf.textContent = fmtSize(t.size); m.appendChild(inf);
    li.appendChild(m);
    const act = document.createElement("span"); act.className = "tr-act dl-done"; act.innerHTML = SVG_DLDONE; act.title = "Скачано"; li.appendChild(act);
    ul.appendChild(li);
  }
}

// ═════════ ДЕТАЛИ ПЛЕЙЛИСТА ═════════
function openDetail(key) { libState.key = key; E("s-detail").hidden = false; loadDetail(); }
E("detBack").addEventListener("click", () => { E("s-detail").hidden = true; libState.key = null; });
async function loadDetail() {
  const d = await apiGet("/api/library/detail?pl=" + encodeURIComponent(libState.key));
  if (!d) { E("s-detail").hidden = true; return; }
  libState.detail = d; renderDetail();
}
function doneSize(d) { return d.tracks.reduce((a, t) => a + (t.status === "done" ? (t.size || 0) : 0), 0); }
function renderDetail() {
  const d = libState.detail; if (!d) return;
  E("detTop").textContent = d.title || "";
  E("detTitle").textContent = d.title || "";
  const b = badge(d.status);
  E("detStat").textContent = `${d.count} ${trkPlur(d.count)} · ${fmtSize(doneSize(d))}` + (b ? ` · ${b.t}` : "");
  const ul = E("detTracks"); ul.innerHTML = "";
  d.tracks.forEach((t) => ul.appendChild(makeTrackRow(d, t)));
}
function makeTrackRow(d, t) {
  const li = document.createElement("li"); li.className = "tr" + (t.status !== "done" ? " tr--off" : "");
  li.dataset.size = (t.status === "done" ? (t.size || 0) : 0);
  li.appendChild(t169(d.key, t.file, t.duration));
  const m = document.createElement("div"); m.className = "tr-meta";
  const ti = document.createElement("div"); ti.className = "tr-title"; ti.textContent = t.title || t.file || "—"; m.appendChild(ti);
  const au = deriveAuthor(t.title || ""); if (au) { const a = document.createElement("div"); a.className = "tr-author"; a.textContent = au; m.appendChild(a); }
  const inf = document.createElement("div"); inf.className = "tr-info"; const bits = [];
  if (t.status !== "done") bits.push("не скачан"); if (t.size) bits.push(fmtSize(t.size));
  inf.textContent = bits.join(" · "); m.appendChild(inf);
  li.appendChild(m);
  const act = document.createElement("button"); act.className = "tr-act del"; act.innerHTML = SVG_TRASH; act.setAttribute("aria-label", "Удалить");
  act.addEventListener("click", (e) => { e.stopPropagation(); delTrack(t, li); });
  li.appendChild(act);
  return li;
}
// Удаление: карточка плавно уезжает и схлопывается, счётчик пересчитывается сразу.
async function delTrack(t, li) {
  if (!(t.id || t.file) || li.classList.contains("tr--removing")) return;
  li.style.height = li.offsetHeight + "px"; void li.offsetHeight; li.classList.add("tr--removing");
  let done = false; const fin = () => { if (done) return; done = true; li.remove(); renumber(); };
  li.addEventListener("transitionend", (e) => { if (e.propertyName === "height") fin(); }); setTimeout(fin, 420);
  const r = await api("/api/library/delete", { pl: libState.key, id: t.id || "", file: t.file || "" });
  if (r && r.ok && r.detail) { libState.detail = r.detail; flatTracks = null; loadLibrary(); }
}
function renumber() {
  const rows = E("detTracks").querySelectorAll(".tr:not(.tr--removing)");
  let bytes = 0; rows.forEach((li) => { bytes += +li.dataset.size || 0; });
  E("detStat").textContent = `${rows.length} ${trkPlur(rows.length)} · ${fmtSize(bytes)}`;
}

// ═════════ ОЧЕРЕДЬ (SSE) ═════════
const TRK_IC = { queued: "·", downloading: "▸", converting: "⟳", done: "✓", error: "✕", cancelled: "⊘" };
function tintCard(el, ratio, status) {
  if (status === "done") { el.style.borderColor = "var(--green)"; el.style.boxShadow = "0 0 0 .5px var(--green)"; }
  else if (status === "error") { el.style.borderColor = "var(--red)"; el.style.boxShadow = "0 0 0 .5px var(--red)"; }
  else if (status === "downloading") { el.style.borderColor = "var(--accent)"; el.style.boxShadow = "0 0 0 .5px var(--accent)"; }
  else { el.style.borderColor = ""; el.style.boxShadow = ""; }
}
function makeCard(p) {
  const li = document.createElement("li"); li.className = "card";
  li.innerHTML = `<div class="thumb">♪</div><div class="card-body"><div class="card-title"></div><div class="card-sub"></div><div class="mini"><i></i></div></div><span class="card-status"></span><span class="chev">›</span><button class="rm" title="Убрать">✕</button>`;
  const r = { thumb: li.querySelector(".thumb"), title: li.querySelector(".card-title"), sub: li.querySelector(".card-sub"),
    mini: li.querySelector(".mini"), bar: li.querySelector(".mini > i"), status: li.querySelector(".card-status"), rm: li.querySelector(".rm") };
  r.rm.addEventListener("click", (e) => { e.stopPropagation(); api("/api/remove", { id: p.id }); });
  return { el: li, r };
}
function updateCard(n, p) {
  const r = n.r;
  if (p.thumbnail) { setCover(r.thumb, p.thumbnail); } else r.thumb.textContent = "♪";
  r.title.textContent = p.title || "Анализирую…";
  let sub = "", st = "", cls = "card-status";
  if (p.status === "probing") { sub = "анализирую ссылку…"; st = "⟳"; }
  else if (p.status === "ready" || p.status === "queued") { sub = `${p.total} треков`; st = p.status === "queued" ? "в очереди" : ""; }
  else if (p.status === "downloading") { sub = `${p.done} / ${p.total}`; st = "⟳"; }
  else if (p.status === "done") { sub = `готово · ${p.total}`; st = "✓"; cls += " done"; }
  else if (p.status === "cancelling") { sub = "останавливаю…"; st = "⟳"; }
  else if (p.status === "cleaning") { sub = "очистка…"; st = "⟳"; }
  else if (p.status === "cancelled") { sub = `отменён · ${p.done}/${p.total}`; st = "⊘"; }
  else if (p.status === "error") { sub = p.error || "ошибка"; st = "✕"; cls += " err"; }
  if (st === "⟳") cls += " spin";
  r.sub.textContent = sub; r.status.textContent = st; r.status.className = cls;
  const ratio = p.total ? p.done / p.total : 0;
  const showBar = p.total > 0 && p.status !== "probing" && p.status !== "error";
  r.mini.style.display = showBar ? "" : "none"; r.bar.style.transform = `scaleX(${ratio})`;
  tintCard(n.el, ratio, p.status);
  r.rm.style.display = state && state.running ? "none" : "";
}
function renderQueue() {
  const ul = E("queue"); const pls = state.playlists || [];
  E("qEmpty").hidden = pls.length > 0;
  const seen = new Set();
  for (const p of pls) {
    seen.add(p.id);
    let n = cards.get(p.id);
    if (!n) { n = makeCard(p); cards.set(p.id, n); n.el.addEventListener("click", () => { if (p.total) openQueueDetail(p.id); }); ul.appendChild(n.el); }
    updateCard(n, p);
  }
  for (const [id, n] of cards) if (!seen.has(id)) { n.el.remove(); cards.delete(id); }
}
function openQueueDetail(id) {
  const p = (state.playlists || []).find((x) => x.id === id); if (!p || !p.total) return;
  // показываем как оверлей плейлиста, но данные из очереди (без удаления)
  E("s-detail").hidden = false;
  E("detTop").textContent = p.title || ""; E("detTitle").textContent = p.title || "";
  E("detStat").textContent = `${p.done} / ${p.total}`;
  const ul = E("detTracks"); ul.innerHTML = "";
  for (const t of p.tracks) {
    const li = document.createElement("li"); li.className = "tr";
    const cov = document.createElement("div"); cov.className = "t169"; cov.textContent = "♪"; li.appendChild(cov);
    const m = document.createElement("div"); m.className = "tr-meta";
    const ti = document.createElement("div"); ti.className = "tr-title"; ti.textContent = t.title; m.appendChild(ti);
    const inf = document.createElement("div"); inf.className = "tr-info";
    inf.textContent = t.status === "downloading" ? `${t.percent}% · ${t.speed || ""}` : (t.status === "done" ? "готово" : t.status);
    m.appendChild(inf); li.appendChild(m); ul.appendChild(li);
  }
}

// go / cancel
E("goBtn").addEventListener("click", () => {
  const btn = E("goBtn");
  if (btn.classList.contains("cancelbtn")) { api("/api/cancel", {}); return; }
  if (!btn.disabled) api("/api/start");
});
function renderGo() {
  const btn = E("goBtn"); const pls = state.playlists || [];
  const ready = pls.some((p) => p.status === "ready" || p.status === "queued");
  if (state.running) {
    const done = pls.filter((p) => p.status === "done").length;
    const busy = pls.some((p) => p.status === "cleaning" || p.status === "cancelling");
    if (busy) { btn.textContent = "Останавливаю…"; btn.classList.add("running"); btn.classList.remove("cancelbtn"); btn.disabled = true; }
    else { btn.textContent = `Отменить · ${done}/${pls.length}`; btn.classList.add("cancelbtn"); btn.classList.remove("running"); btn.disabled = false; }
  } else { btn.textContent = "Скачать всё"; btn.classList.remove("running", "cancelbtn"); btn.disabled = !ready; }
}

// ═════════ НАСТРОЙКИ (сегменты/слайдер/куки) ═════════
const PLATFORM_SUB = { android: "формат: без ограничений (Best)", ios: "формат: m4a / AAC (Apple)", windows: "формат: mp3 (макс. совместимость)", linux: "формат: m4a / opus" };
const QUALITY_SUB = { max: "Opus ~160 kbps — максимум, что отдаёт YouTube", standard: "AAC 128 kbps — универсальный, играет везде", economy: "~50–64 kbps — мелкие файлы, экономия места" };
function readSettings() { return { platform: document.querySelector("#segPlatform .on").dataset.v, quality: document.querySelector("#segQuality .on").dataset.v, streams: parseInt(E("streams").value, 10) }; }
function computeSplit(s, n) { n = Math.max(1, n || 1); const plc = Math.max(1, Math.min(n, Math.round(s / 2))); const tpp = Math.max(1, Math.min(4, Math.floor(s / plc))); return { plc, tpp, total: plc * tpp }; }
function riskOf(s) { if (s <= 4) return { hex: "var(--green)", t: "безопасно (как 4KVD)" }; if (s <= 6) return { hex: "var(--yellow)", t: "чуть выше среднего — управляемый" }; return { hex: "var(--red)", t: "высокий риск бана" }; }
function paintStreams() {
  const s = parseInt(E("streams").value, 10);
  const n = state ? (state.playlists || []).filter((p) => p.status !== "error").length : 0;
  const sp = computeSplit(s, n); const r = riskOf(sp.total);
  E("streamsLabel").textContent = `${sp.plc} ${plur(sp.plc, "плейлист", "плейлиста", "плейлистов")} × ${sp.tpp} трека = ${sp.total} потоков`;
  E("riskTag").style.background = r.hex; E("riskSub").textContent = r.t;
}
function paintSubs() { E("platformSub").textContent = PLATFORM_SUB[document.querySelector("#segPlatform .on").dataset.v]; E("qualitySub").textContent = QUALITY_SUB[document.querySelector("#segQuality .on").dataset.v]; }
function makeSegmented(seg, onChange) {
  const btns = [...seg.querySelectorAll("button")];
  const thumb = document.createElement("span"); thumb.className = "seg-thumb"; seg.insertBefore(thumb, seg.firstChild);
  let active = Math.max(0, btns.findIndex((b) => b.classList.contains("on")));
  const snap = (animate = true) => { const b = btns[active]; if (!animate) thumb.style.transition = "none";
    thumb.style.transform = `translateX(${b.offsetLeft - 4}px)`; thumb.style.width = b.offsetWidth + "px";
    if (!animate) { void thumb.offsetWidth; thumb.style.transition = ""; }
    btns.forEach((x, k) => x.classList.toggle("on", k === active)); };
  btns.forEach((b, i) => b.addEventListener("click", () => { active = i; snap(); paintSubs(); onChange(); api("/api/settings", readSettings()); }));
  snap(false);
  return { setValue(v) { const i = btns.findIndex((b) => b.dataset.v === v); if (i >= 0) { active = i; snap(); } }, reflow() { snap(false); } };
}
const segP = makeSegmented(E("segPlatform"), paintSubs);
const segQ = makeSegmented(E("segQuality"), paintSubs);
window.addEventListener("resize", () => { segP.reflow(); segQ.reflow(); });
let sTimer = null;
E("streams").addEventListener("input", () => { paintStreams(); clearTimeout(sTimer); sTimer = setTimeout(() => api("/api/settings", readSettings()), 180); });
E("streams").addEventListener("pointerdown", () => (sliderDrag = true));
E("streams").addEventListener("pointerup", () => (sliderDrag = false));
E("checkBtn").addEventListener("click", async () => { if (E("checkBtn").disabled) return; const r = await api("/api/check"); if (!r.ok) hint(r.msg || "не запустилось", "err"); });

function renderCookies() {
  const c = state.cookies || {};
  E("ckDot").className = "ck-dot " + (c.status || ""); E("ckMsg").textContent = c.msg || "—";
  const ok = c.auth === true; E("authDot").className = "ck-dot " + (ok ? "fresh" : "none");
  E("authMsg").textContent = ok ? "cookies из твоего браузера" + (c.source ? ` (${c.source})` : "") : "аккаунт не подтверждён — микс будет случайным";
}
function renderSetup() { const s = state.setup || {}; const n = E("setupNote"); const show = s.ok === false && !!s.msg; n.hidden = !show; if (show) n.textContent = "⚠ " + s.msg; }
function renderAuth() {
  const a = state.auth || {}; const btn = E("checkBtn"), log = E("loginLog");
  const busy = a.state === "running"; const dead = (state.cookies || {}).status === "dead";
  btn.disabled = busy; btn.textContent = busy ? "Спрашиваю YouTube…" : "Проверить сессию";
  E("authHint").textContent = dead ? "открой YouTube в Kiwi и тапни иконку расширения" : "нет расширения? собери: python main.py kiwi";
  const lines = a.log || []; log.hidden = lines.length === 0;
  if (lines.length) { const text = lines.join("\n"); if (log.textContent !== text) { log.textContent = text; log.scrollTop = log.scrollHeight; } }
  log.className = "log" + (a.state === "error" ? " err" : a.state === "ok" ? " ok" : "");
}

// ═════════ state / SSE ═════════
function applyState() {
  if (!inited) {
    const s = state.settings || {};
    if (s.platform) segP.setValue(s.platform);
    if (s.quality) segQ.setValue(s.quality);
    if (s.streams) E("streams").value = s.streams;
    paintStreams(); paintSubs();
    requestAnimationFrame(() => { segP.reflow(); segQ.reflow(); });
    inited = true;
  } else if (!sliderDrag && state.settings && state.settings.streams && +E("streams").value !== state.settings.streams) {
    E("streams").value = state.settings.streams; paintStreams();
  }
  renderQueue(); renderGo(); renderCookies(); renderSetup(); renderAuth();
}
let pending = null, scheduled = false;
function onState(s) { pending = s; if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; state = pending; applyState(); }); } }
function connect() {
  const es = new EventSource("/api/events");
  es.onopen = () => document.body.classList.add("live");
  es.onmessage = (e) => { try { onState(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => { document.body.classList.remove("live"); es.close(); setTimeout(connect, 1500); };
}

// init
showTab("home");
fetch("/api/state").then((r) => r.json()).then(onState).catch(() => {});
connect();
