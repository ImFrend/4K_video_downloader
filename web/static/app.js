/* TermuxYoutube — фронт. Keyed-обновление DOM (без пересборки → плавный scaleX),
   SSE-поток состояния, пружинная навигация. Данные приходят «скачками» (throttle
   на сервере), CSS-transition доплавляет между ними → 60/120fps из редких данных. */

const E = (id) => document.getElementById(id);
const api = async (path, body) => {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
};

let state = null;
let detailId = null;
let inited = false;
let sliderDrag = false;
const cards = new Map();    // jobId -> {el, r}
const trks = new Map();     // trackIndex -> {el, r}

// ─────────── helpers ───────────
const PLATFORM_SUB = {
  android: "формат: без ограничений (Best)",
  ios: "формат: m4a / AAC (Apple)",
  windows: "формат: mp3 (макс. совместимость)",
  linux: "формат: m4a / opus",
};
const QUALITY_SUB = {
  max: "Opus ~160 kbps — максимум, что отдаёт YouTube",
  standard: "AAC 128 kbps — универсальный, играет везде",
  economy: "~50–64 kbps — мелкие файлы, экономия места",
};
function plPlur(n) {
  const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return "плейлист";
  if (a >= 2 && a <= 4 && (b < 10 || b >= 20)) return "плейлиста";
  return "плейлистов";
}
function riskOf(s) {
  if (s <= 4) return { hex: "#30d158", e: "🟢", t: "безопасно (как 4KVD)" };
  if (s <= 6) return { hex: "#ffd60a", e: "🟡", t: "чуть выше среднего — управляемый" };
  return { hex: "#ff453a", e: "🔴", t: "высокий риск бана ⚠" };
}
const TRK_IC = {
  queued: "·", downloading: "▸", converting: "⟳", done: "✓", error: "✕",
};

// ─────────── settings UI ───────────
function readSettings() {
  return {
    platform: document.querySelector("#segPlatform .on").dataset.v,
    quality: document.querySelector("#segQuality .on").dataset.v,
    streams: parseInt(E("streams").value, 10),
  };
}
function paintStreams() {
  const s = parseInt(E("streams").value, 10);
  const pl = Math.round(s / 2);
  const r = riskOf(s);
  E("streamsLabel").textContent = `${pl} ${plPlur(pl)} × 2 трека = ${s} потоков`;
  E("riskTag").textContent = r.e;
  E("riskSub").textContent = r.t;
  const pos = ((s - 2) / 6) * 100;
  E("streams").style.background =
    `linear-gradient(90deg, ${r.hex} ${pos}%, var(--card-2) ${pos}%)`;
}
function paintSubs() {
  E("platformSub").textContent =
    PLATFORM_SUB[document.querySelector("#segPlatform .on").dataset.v];
  E("qualitySub").textContent =
    QUALITY_SUB[document.querySelector("#segQuality .on").dataset.v];
}

// iOS UISegmentedControl: сдвижной thumb тянется ПРЯМО за пальцем, с резиной
// (rubber-band) на краях, и пружиной встаёт на выбранный сегмент при отпускании.
const RUBBER = 0.28;     // жёсткость резины за краем (меньше = упруже сопротивляется)
function makeSegmented(seg, onChange) {
  const btns = [...seg.querySelectorAll("button")];
  const thumb = document.createElement("span");
  thumb.className = "seg-thumb";
  seg.insertBefore(thumb, seg.firstChild);
  let active = Math.max(0, btns.findIndex((b) => b.classList.contains("on")));

  const setSel = (i) => {
    if (i === active) return;
    active = i;
    thumb.dataset.v = btns[i].dataset.v;
    btns.forEach((x, k) => x.classList.toggle("on", k === i));
    paintSubs();
  };
  // встать ровно на выбранный сегмент (пружиной, если animate)
  const snap = (animate = true) => {
    const b = btns[active];
    if (!animate) thumb.style.transition = "none";
    thumb.style.transform = `translateX(${b.offsetLeft}px)`;
    thumb.style.width = b.offsetWidth + "px";
    thumb.dataset.v = b.dataset.v;
    if (!animate) { void thumb.offsetWidth; thumb.style.transition = ""; }
    btns.forEach((x, k) => x.classList.toggle("on", k === active));
  };
  const nearest = (px) => {
    let best = 0, bd = Infinity;
    btns.forEach((b, i) => { const c = b.offsetLeft + b.offsetWidth / 2, d = Math.abs(c - px); if (d < bd) { bd = d; best = i; } });
    return best;
  };
  // thumb едет за пальцем; за краями — резина
  const follow = (clientX) => {
    const x = clientX - seg.getBoundingClientRect().left;
    const w = btns[0].offsetWidth;
    const minL = btns[0].offsetLeft, maxL = btns[btns.length - 1].offsetLeft;
    let left = x - w / 2;
    if (left < minL) left = minL + (left - minL) * RUBBER;       // резина слева
    else if (left > maxL) left = maxL + (left - maxL) * RUBBER;  // резина справа
    thumb.style.transform = `translateX(${left}px)`;
    thumb.style.width = w + "px";
    setSel(nearest(x));
  };

  let dragging = false;
  seg.addEventListener("pointerdown", (e) => {
    dragging = true; seg.classList.add("dragging");
    try { seg.setPointerCapture(e.pointerId); } catch (_) {}
    follow(e.clientX);
  });
  seg.addEventListener("pointermove", (e) => { if (dragging) follow(e.clientX); });
  const end = () => {
    if (!dragging) return;
    dragging = false; seg.classList.remove("dragging");
    snap();                       // резина отыгрывает назад, thumb пружиной на сегмент
    onChange();
    api("/api/settings", readSettings());
  };
  seg.addEventListener("pointerup", end);
  seg.addEventListener("pointercancel", end);

  snap(false);
  return {
    setValue(v) { const i = btns.findIndex((b) => b.dataset.v === v); if (i >= 0) { active = i; snap(); } },
    getValue() { return btns[active].dataset.v; },
    reflow() { snap(false); },
  };
}
const segP = makeSegmented(E("segPlatform"), paintSubs);
const segQ = makeSegmented(E("segQuality"), paintSubs);
window.addEventListener("resize", () => { segP.reflow(); segQ.reflow(); });

let sTimer = null;
const streams = E("streams");
streams.addEventListener("input", () => {
  paintStreams();
  clearTimeout(sTimer);
  sTimer = setTimeout(() => api("/api/settings", readSettings()), 180);
});
streams.addEventListener("pointerdown", () => (sliderDrag = true));
streams.addEventListener("pointerup", () => (sliderDrag = false));
streams.addEventListener("pointercancel", () => (sliderDrag = false));

// ─────────── queue cards ───────────
function makeCard(p) {
  const li = document.createElement("li");
  li.className = "card";
  li.innerHTML = `
    <div class="thumb"></div>
    <div class="card-body">
      <div class="card-title"></div>
      <div class="card-sub"></div>
      <div class="mini"><i></i></div>
    </div>
    <span class="card-status"></span>
    <span class="chev">›</span>
    <button class="rm" title="Убрать">✕</button>`;
  const r = {
    thumb: li.querySelector(".thumb"),
    title: li.querySelector(".card-title"),
    sub: li.querySelector(".card-sub"),
    mini: li.querySelector(".mini"),
    bar: li.querySelector(".mini > i"),
    status: li.querySelector(".card-status"),
    rm: li.querySelector(".rm"),
  };
  r.rm.addEventListener("click", (e) => { e.stopPropagation(); api("/api/remove", { id: p.id }); });
  li.addEventListener("click", () => openDetail(p.id));
  return { el: li, r };
}

function updateCard(n, p) {
  const r = n.r;
  if (p.thumbnail) { r.thumb.style.backgroundImage = `url("${p.thumbnail}")`; r.thumb.textContent = ""; }
  else r.thumb.textContent = "🎵";
  r.title.textContent = p.title || "Анализирую…";

  let sub = "", st = "", cls = "card-status";
  if (p.status === "probing") { sub = "анализирую ссылку…"; st = "⟳"; }
  else if (p.status === "ready" || p.status === "queued") { sub = `${p.total} треков`; st = p.status === "queued" ? "в очереди" : ""; }
  else if (p.status === "downloading") { sub = `${p.done} / ${p.total}`; st = "⟳"; }
  else if (p.status === "done") { sub = `готово · ${p.total}`; st = "✓"; cls += " done"; }
  else if (p.status === "error") { sub = p.error || "ошибка"; st = "✕"; cls += " err"; }
  r.sub.textContent = sub;
  r.status.textContent = st;
  r.status.className = cls;

  const showBar = p.total > 0 && p.status !== "probing" && p.status !== "error";
  r.mini.style.display = showBar ? "" : "none";
  r.bar.style.transform = `scaleX(${p.total ? p.done / p.total : 0})`;

  // убрать можно, пока не идёт общая загрузка
  r.rm.style.display = state && state.running ? "none" : "";
}

function renderQueue() {
  const ul = E("queue");
  const pls = state.playlists || [];
  if (!pls.length) {
    if (!ul.querySelector(".empty")) ul.innerHTML = `<div class="empty">Пусто — вставь ссылку на плейлист сверху</div>`;
    cards.clear();
    E("queueCount").textContent = "";
    return;
  }
  if (ul.querySelector(".empty")) ul.innerHTML = "";
  const seen = new Set();
  for (const p of pls) {
    seen.add(p.id);
    let n = cards.get(p.id);
    if (!n) { n = makeCard(p); cards.set(p.id, n); ul.appendChild(n.el); }
    updateCard(n, p);
  }
  for (const [id, n] of cards) if (!seen.has(id)) { n.el.remove(); cards.delete(id); }

  const active = pls.filter((p) => p.status !== "error").length;
  E("queueCount").textContent = `${active}/${state.max}`;
}

// ─────────── detail ───────────
function openDetail(id) {
  const p = (state.playlists || []).find((x) => x.id === id);
  if (!p || !p.total) return;          // не открываем «анализирую» пустышку
  detailId = id;
  E("tracklist").innerHTML = "";
  trks.clear();
  renderDetail();
  document.body.classList.add("detail");
}
function closeDetail() {
  document.body.classList.remove("detail");
  detailId = null;
}
E("backBtn").addEventListener("click", closeDetail);

function makeTrack(t) {
  const li = document.createElement("li");
  li.className = "trk";
  li.innerHTML = `
    <span class="trk-i"></span>
    <div class="trk-body">
      <div class="trk-title"></div>
      <div class="trk-bar"><i></i></div>
      <div class="trk-meta"></div>
    </div>
    <span class="trk-ic"></span>`;
  return {
    el: li,
    r: {
      i: li.querySelector(".trk-i"), title: li.querySelector(".trk-title"),
      bar: li.querySelector(".trk-bar > i"), meta: li.querySelector(".trk-meta"),
      ic: li.querySelector(".trk-ic"),
    },
  };
}
function updateTrack(n, t) {
  const r = n.r;
  r.i.textContent = String(t.i).padStart(2, "0");
  r.title.textContent = t.title;
  r.bar.style.transform = `scaleX(${(t.percent || 0) / 100})`;
  r.bar.parentElement.style.opacity = (t.status === "downloading" || t.status === "converting") ? 1 : 0.0;
  let meta = "";
  if (t.status === "downloading") meta = `${t.percent}%${t.speed ? " · " + t.speed : ""}${t.eta ? " · " + t.eta : ""}`;
  else if (t.status === "converting") meta = "конвертация…";
  else if (t.status === "error") meta = t.error || "ошибка";
  else if (t.status === "queued") meta = "в очереди";
  r.meta.textContent = meta;
  r.ic.textContent = TRK_IC[t.status] || "·";
  r.ic.className = "trk-ic" + (t.status === "done" ? " done" : t.status === "error" ? " err" : t.status === "downloading" ? " dl" : "");
}
function renderDetail() {
  if (detailId == null) return;
  const p = (state.playlists || []).find((x) => x.id === detailId);
  if (!p) { closeDetail(); return; }
  E("detailTitle").textContent = p.title || "";
  const cov = E("detailCover");
  if (p.thumbnail) { cov.style.backgroundImage = `url("${p.thumbnail}")`; cov.textContent = ""; }
  else cov.textContent = "🎵";
  const stLine = p.status === "done" ? "готово" : p.status === "downloading" ? "качаю…" : p.status === "queued" ? "в очереди" : "";
  E("detailStat").innerHTML = `<b>${p.done} / ${p.total}</b><br>${stLine}`;

  const ul = E("tracklist");
  for (const t of p.tracks) {
    let n = trks.get(t.i);
    if (!n) { n = makeTrack(t); trks.set(t.i, n); ul.appendChild(n.el); }
    updateTrack(n, t);
  }
}

// ─────────── go / cookies / sheet ───────────
E("goBtn").addEventListener("click", () => { if (!E("goBtn").disabled) api("/api/start"); });

function renderGo() {
  const btn = E("goBtn");
  const pls = state.playlists || [];
  const ready = pls.some((p) => p.status === "ready" || p.status === "queued");
  if (state.running) {
    const done = pls.filter((p) => p.status === "done").length;
    btn.textContent = `Качаю… ${done}/${pls.length}`;
    btn.classList.add("running"); btn.disabled = true;
  } else {
    btn.textContent = "▸ Скачать всё";
    btn.classList.remove("running"); btn.disabled = !ready;
  }
}

function renderCookies() {
  const c = state.cookies || {};
  E("ckDot").className = "ck-dot " + (c.status || "");
  E("ckMsg").textContent = c.msg || "—";
}

E("gearBtn").addEventListener("click", () => { E("sheet").hidden = false; });
const closeSheet = () => { E("sheet").hidden = true; };
E("sheetClose").addEventListener("click", closeSheet);
E("sheetBg").addEventListener("click", closeSheet);

// ─────────── paste ───────────
E("pasteBtn").addEventListener("click", async () => {
  let url = "";
  try { url = (await navigator.clipboard.readText() || "").trim(); } catch (_) {}
  if (!url) url = (prompt("Ссылка на плейлист / My Mix:") || "").trim();
  if (!url) return;
  const r = await api("/api/add", { url });
  hint(r.ok ? "Добавлено ✓" : r.msg, !r.ok);
});
let hintT = null;
function hint(msg, err) {
  const h = E("pasteHint");
  h.textContent = msg; h.className = "hint" + (err ? " err" : "");
  clearTimeout(hintT);
  hintT = setTimeout(() => { h.textContent = ""; }, 2600);
}

// ─────────── apply state (coalesced via rAF) ───────────
function applyState() {
  if (!inited) {
    const s = state.settings || {};
    if (s.platform) segP.setValue(s.platform);
    if (s.quality) segQ.setValue(s.quality);
    if (s.streams) E("streams").value = s.streams;
    paintStreams(); paintSubs();
    requestAnimationFrame(() => { segP.reflow(); segQ.reflow(); });   // точная посадка thumb
    inited = true;
  } else if (!sliderDrag && state.settings && state.settings.streams && +E("streams").value !== state.settings.streams) {
    E("streams").value = state.settings.streams; paintStreams();
  }
  renderQueue();
  renderGo();
  renderCookies();
  if (detailId != null) renderDetail();
}

let pending = null, scheduled = false;
function onState(s) {
  pending = s;
  if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; state = pending; applyState(); }); }
}

// ─────────── SSE ───────────
function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => { try { onState(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => { es.close(); setTimeout(connect, 1500); };
}

// init
E("view-detail").hidden = false;        // позиционируется трансформом за экраном
fetch("/api/state").then((r) => r.json()).then(onState).catch(() => {});
connect();
