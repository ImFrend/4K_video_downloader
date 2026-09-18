/* TermuxYoutube — фронт. Keyed-обновление DOM (без пересборки → плавный scaleX),
   SSE-поток состояния, пружинная навигация. Данные приходят «скачками» (throttle
   на сервере), CSS-transition доплавляет между ними → 60/120fps из редких данных. */

const E = (id) => document.getElementById(id);
const api = async (path, body) => {
  // сервер может внезапно умереть (Termux убит, wake-lock снят) — кнопки не должны
  // молча «не работать»: любой сбой сети превращаем в честный ответ с текстом
  try {
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (_) {
    return { ok: false, msg: "нет связи с сервером — запусти его заново" };
  }
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
  if (s <= 4) return { hex: "#32d74b", t: "безопасно (как 4KVD)" };
  if (s <= 6) return { hex: "#ffd60a", t: "чуть выше среднего — управляемый" };
  return { hex: "#ff453a", t: "высокий риск бана" };
}
const TRK_IC = {
  queued: "·", downloading: "▸", converting: "⟳", done: "✓", error: "✕",
};

// рамка карточки «созревает» по мере % (синий → зелёный) + растущее свечение
function tintCard(el, ratio, status) {
  if (status === "done") {
    el.style.borderColor = "var(--green)";
    el.style.boxShadow = "0 0 0 .5px var(--green), 0 6px 22px rgba(48,209,88,.20)";
  } else if (status === "error") {
    el.style.borderColor = "var(--red)";
    el.style.boxShadow = "0 0 0 .5px rgba(255,69,58,.6)";
  } else if (status === "downloading") {
    const hue = 210 - 68 * ratio;            // 210° синий → 142° зелёный
    const col = `hsl(${hue} 90% 56%)`;
    el.style.borderColor = col;
    el.style.boxShadow = `0 0 0 .5px ${col}, 0 6px 24px hsla(${hue} 90% 50% / ${0.12 + ratio * 0.26})`;
  } else {                                    // ready / queued / probing
    el.style.borderColor = "";
    el.style.boxShadow = "";
  }
}

// ─────────── settings UI ───────────
function readSettings() {
  return {
    platform: document.querySelector("#segPlatform .on").dataset.v,
    quality: document.querySelector("#segQuality .on").dataset.v,
    streams: parseInt(E("streams").value, 10),
  };
}
// тот же делёж, что на сервере: бюджет streams → (плейлистов × треков), потолок 4/плейлист
function computeSplit(s, n) {
  n = Math.max(1, n || 1);
  const plc = Math.max(1, Math.min(n, Math.round(s / 2)));
  const tpp = Math.max(1, Math.min(4, Math.floor(s / plc)));
  return { plc, tpp, total: plc * tpp };
}
function paintStreams() {
  const s = parseInt(E("streams").value, 10);
  const n = state ? (state.playlists || []).filter((p) => p.status !== "error").length : 0;
  const sp = computeSplit(s, n);
  const r = riskOf(sp.total);                 // риск по РЕАЛЬНОМУ числу потоков
  E("streamsLabel").textContent = `${sp.plc} ${plPlur(sp.plc)} × ${sp.tpp} трека = ${sp.total} потоков`;
  // точка риска: цвет + мягкое свечение того же цвета (вместо эмодзи-светофора)
  E("riskTag").style.background = r.hex;
  E("riskTag").style.boxShadow = `0 0 6px ${r.hex}66`;
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
  else r.thumb.textContent = "♪";      // текстовый глиф: одинаков на всех телефонах
  r.title.textContent = p.title || "Анализирую…";

  let sub = "", st = "", cls = "card-status";
  if (p.status === "probing") { sub = "анализирую ссылку…"; st = "⟳"; }
  else if (p.status === "ready" || p.status === "queued") { sub = `${p.total} треков`; st = p.status === "queued" ? "в очереди" : ""; }
  else if (p.status === "downloading") { sub = `${p.done} / ${p.total}`; st = "⟳"; }
  else if (p.status === "done") { sub = `готово · ${p.total}`; st = "✓"; cls += " done"; }
  else if (p.status === "cancelling") { sub = "останавливаю…"; st = "⟳"; }
  else if (p.status === "cleaning") { sub = "очистка хвостов…"; st = "⟳"; }
  else if (p.status === "cancelled") { sub = `отменён · ${p.done}/${p.total}`; st = "⊘"; }
  else if (p.status === "error") { sub = p.error || "ошибка"; st = "✕"; cls += " err"; }
  if (st === "⟳") cls += " spin";        // «шестерёнка» статуса крутится (GPU)
  r.sub.textContent = sub;
  r.status.textContent = st;
  r.status.className = cls;

  const ratio = p.total ? p.done / p.total : 0;
  const showBar = p.total > 0 && p.status !== "probing" && p.status !== "error";
  r.mini.style.display = showBar ? "" : "none";
  r.bar.style.transform = `scaleX(${ratio})`;
  tintCard(n.el, ratio, p.status);
  // классы состояния → CSS-жизнь: блик по бару при загрузке, «дыхание» при анализе
  n.el.classList.toggle("dl", p.status === "downloading");
  n.el.classList.toggle("probing", p.status === "probing");

  // убрать можно, пока не идёт общая загрузка
  r.rm.style.display = state && state.running ? "none" : "";
}

function renderQueue() {
  const ul = E("queue");
  const pls = state.playlists || [];
  if (!pls.length) {
    if (!ul.querySelector(".empty")) ul.innerHTML = `
      <div class="empty">
        <div class="empty-ic">♪</div>
        <div class="empty-t">Очередь пуста</div>
        <div class="empty-s">Вставь ссылку на плейлист, My Mix<br>или список видео</div>
      </div>`;
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
  // удалённая карточка уезжает мягко (CSS .leave), а не исчезает рывком
  for (const [id, n] of cards) if (!seen.has(id)) {
    cards.delete(id);
    const el = n.el;
    el.classList.add("leave");
    setTimeout(() => el.remove(), 240);
  }

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
  r.ic.className = "trk-ic" + (t.status === "done" ? " done" : t.status === "error" ? " err"
    : t.status === "downloading" ? " dl" : t.status === "converting" ? " cv" : "");
}
function renderDetail() {
  if (detailId == null) return;
  const p = (state.playlists || []).find((x) => x.id === detailId);
  if (!p) { closeDetail(); return; }
  E("detailTitle").textContent = p.title || "";
  const cov = E("detailCover");
  if (p.thumbnail) { cov.style.backgroundImage = `url("${p.thumbnail}")`; cov.textContent = ""; }
  else cov.textContent = "♪";
  const stLine = p.status === "done" ? "готово" : p.status === "downloading" ? "качаю…" : p.status === "queued" ? "в очереди" : "";
  E("detailStat").innerHTML = `<b>${p.done} / ${p.total}</b><br>${stLine}`;

  const ul = E("tracklist");
  for (const t of p.tracks) {
    let n = trks.get(t.i);
    if (!n) { n = makeTrack(t); trks.set(t.i, n); ul.appendChild(n.el); }
    updateTrack(n, t);
  }
}

// ─────────── go / cancel / cookies / sheet ───────────
E("goBtn").addEventListener("click", () => {
  const btn = E("goBtn");
  if (btn.classList.contains("cancelbtn")) { api("/api/cancel", {}); return; }  // отмена всей очереди
  if (!btn.disabled) api("/api/start");
});

function renderGo() {
  const btn = E("goBtn");
  const pls = state.playlists || [];
  const ready = pls.some((p) => p.status === "ready" || p.status === "queued");
  if (state.running) {
    const done = pls.filter((p) => p.status === "done").length;
    const cleaning = pls.some((p) => p.status === "cleaning");
    const stopping = pls.some((p) => p.status === "cancelling");
    if (cleaning || stopping) {                       // отмена уже идёт → блокируем
      btn.textContent = cleaning ? "Очистка…" : "Останавливаю…";
      btn.classList.add("running"); btn.classList.remove("cancelbtn"); btn.disabled = true;
    } else {                                          // идёт загрузка → кнопка = «Отменить»
      btn.textContent = `⛔ Отменить · ${done}/${pls.length}`;
      btn.classList.add("cancelbtn"); btn.classList.remove("running"); btn.disabled = false;
    }
  } else {
    btn.textContent = "▸ Скачать всё";
    btn.classList.remove("running", "cancelbtn"); btn.disabled = !ready;
  }
}

function renderCookies() {
  const c = state.cookies || {};
  E("ckDot").className = "ck-dot " + (c.status || "");
  E("ckMsg").textContent = c.msg || "—";
  // главный вопрос при разъезжающихся миксах: мы под аккаунтом или анонимно
  const ok = c.auth === true;
  E("authDot").className = "ck-dot " + (ok ? "fresh" : "none");
  E("authMsg").textContent = ok
    ? "cookies из твоего браузера" + (c.source ? ` (${c.source})` : "")
    : "аккаунт не подтверждён — микс будет случайным";
}

// ─────────── проверка сессии ───────────
// Один GET к YouTube: узнаёт он наши cookies или нет. Своего браузера у проекта
// нет — мёртвую сессию чинит повторный тап по иконке расширения в Kiwi.
E("checkBtn").addEventListener("click", async () => {
  if (E("checkBtn").disabled) return;
  const r = await api("/api/check");
  if (!r.ok) hint(r.msg || "не запустилось", "err");
});

// окружение отстало от кода (обновились через git pull, а зависимости — нет)
function renderSetup() {
  const s = state.setup || {};
  const n = E("setupNote");
  const show = s.ok === false && !!s.msg;
  n.hidden = !show;
  if (show) n.textContent = "⚠ " + s.msg;
}

function renderAuth() {
  const a = state.auth || {};
  const btn = E("checkBtn"), log = E("loginLog");
  const busy = a.state === "running";
  const dead = (state.cookies || {}).status === "dead";

  btn.disabled = busy;
  btn.textContent = busy ? "Спрашиваю YouTube…" : "Проверить сессию";

  E("authHint").textContent = dead
    ? "открой YouTube в Kiwi и тапни иконку расширения — этого достаточно"
    : "расширение не поставлено? собери его: python main.py kiwi";

  const lines = a.log || [];
  log.hidden = lines.length === 0;
  if (lines.length) {
    const text = lines.join("\n");
    if (log.textContent !== text) { log.textContent = text; log.scrollTop = log.scrollHeight; }
  }
  log.className = "log" + (a.state === "error" ? " err" : a.state === "ok" ? " ok" : "");
}

// лист: открытие/закрытие с анимацией + свайп вниз за полоску (как в iOS)
const sheetWrap = E("sheet");
const sheetEl = sheetWrap.querySelector(".sheet");
const sheetGrip = sheetWrap.querySelector(".sheet-grip");
let sheetCloseT = null;

function openSheet() {
  clearTimeout(sheetCloseT);
  sheetWrap.classList.remove("closing");
  sheetEl.style.transform = ""; E("sheetBg").style.opacity = "";
  sheetWrap.hidden = false;
}
function closeSheet() {
  if (sheetWrap.hidden) return;
  sheetWrap.classList.add("closing");            // CSS доигрывает уезд вниз
  clearTimeout(sheetCloseT);
  sheetCloseT = setTimeout(() => {
    sheetWrap.hidden = true;
    sheetWrap.classList.remove("closing");
    sheetEl.style.transform = ""; E("sheetBg").style.opacity = "";
  }, 300);
}
E("gearBtn").addEventListener("click", openSheet);
E("sheetClose").addEventListener("click", closeSheet);
E("sheetBg").addEventListener("click", closeSheet);

// drag строго за полоску (не за кнопки — иначе pointer capture съедает их клики)
let shY = null, shDy = 0, shDrag = false;
sheetGrip.addEventListener("pointerdown", (e) => {
  shDrag = true; shY = e.clientY; shDy = 0;
  sheetEl.style.transition = "none";
  try { sheetGrip.setPointerCapture(e.pointerId); } catch (_) {}
});
sheetGrip.addEventListener("pointermove", (e) => {
  if (!shDrag) return;
  shDy = Math.max(0, e.clientY - shY);           // вверх не тянем — только вниз
  sheetEl.style.transform = `translateY(${shDy}px)`;
  E("sheetBg").style.opacity = String(Math.max(0, 1 - shDy / 420));
});
const sheetDragEnd = () => {
  if (!shDrag) return;
  shDrag = false;
  sheetEl.style.transition = "";
  if (shDy > 90) { closeSheet(); }
  else { sheetEl.style.transform = ""; E("sheetBg").style.opacity = ""; }  // пружина назад
};
sheetGrip.addEventListener("pointerup", sheetDragEnd);
sheetGrip.addEventListener("pointercancel", sheetDragEnd);

// ─────────── paste ───────────
E("pasteBtn").addEventListener("click", async () => {
  let url = "";
  try { url = (await navigator.clipboard.readText() || "").trim(); } catch (_) {}
  if (!url) url = (prompt("Ссылка на плейлист / My Mix / список видео:") || "").trim();
  if (!url) return;
  const r = await api("/api/add", { url, limit: libLimit });
  if (!r.ok) hint(r.msg, "err");
  else if (r.msg && r.msg !== "ok") hint(r.msg, "warn");   // добавили, но с оговоркой
  else hint("Добавлено ✓");
});
let hintT = null;
function hint(msg, level) {
  const h = E("pasteHint");
  h.textContent = msg;
  h.className = "hint show" + (level ? " " + level : "");   // .show → плавный вход
  clearTimeout(hintT);
  hintT = setTimeout(() => { h.classList.remove("show"); },
                     level === "warn" ? 5200 : 2600);       // оговорку показываем дольше
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
  paintStreams();              // делёж/риск зависят от числа добавленных миксов
  renderGo();
  renderCookies();
  renderSetup();
  renderAuth();
  if (detailId != null) renderDetail();
}

let pending = null, scheduled = false;
function onState(s) {
  pending = s;
  if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; state = pending; applyState(); }); }
}

// ─────────── SSE ───────────
// LED в нейм-плейте показывает реальное состояние потока: зелёный — связь
// живая, тусклый — сервер молчит и идёт переподключение.
function connect() {
  const es = new EventSource("/api/events");
  es.onopen = () => { document.body.classList.add("live"); };
  es.onmessage = (e) => { try { onState(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => {
    document.body.classList.remove("live");
    es.close(); setTimeout(connect, 1500);
  };
}

// init
E("view-detail").hidden = false;        // позиционируется трансформом за экраном
fetch("/api/state").then((r) => r.json()).then(onState).catch(() => {});
connect();

// ═══════════ Библиотека (скачанное) ═══════════
// Отдельный домен от Очереди: источник — диск (GET /api/library), не SSE.
let libLimit = 25;                       // глубина снимка микса (чипы под «Вставить»)
const libState = { list: [], detail: null, key: null };

const apiGet = async (p) => { try { return await (await fetch(p)).json(); } catch (_) { return null; } };
function trkPlur(n) {
  const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return "трек";
  if (a >= 2 && a <= 4 && (b < 10 || b >= 20)) return "трека";
  return "треков";
}
function fmtSize(b) {
  if (!b) return "0 МБ";
  const mb = b / 1048576;
  return mb >= 1024 ? (mb / 1024).toFixed(1) + " ГБ" : Math.round(mb) + " МБ";
}
// обложка: глиф ♪ по умолчанию, поверх — картинка из /api/cover (если есть)
function setCover(el, url) {
  const img = new Image();
  img.onload = () => { el.textContent = ""; img.className = "cover-img"; el.appendChild(img); };
  img.src = url;                          // onerror → глиф остаётся
}
function coverEl(cls, url) {
  const el = document.createElement("div");
  el.className = cls; el.textContent = "♪";
  setCover(el, url);
  return el;
}
const covUrl = (key, file) =>
  "/api/cover?pl=" + encodeURIComponent(key) + (file ? "&file=" + encodeURIComponent(file) : "");

// ── чипы лимита ──
E("limitChips").querySelectorAll(".chip").forEach((c) => {
  c.addEventListener("click", () => {
    E("limitChips").querySelectorAll(".chip").forEach((x) => x.classList.remove("on"));
    c.classList.add("on"); libLimit = parseInt(c.dataset.n, 10);
  });
});

// ── список плейлистов ──
E("libBtn").addEventListener("click", () => { loadLibrary(); document.body.classList.add("library"); });
E("libBack").addEventListener("click", () => document.body.classList.remove("library"));

async function loadLibrary() {
  const d = await apiGet("/api/library");
  libState.list = (d && d.playlists) || [];
  renderLibrary();
}
function badgeFor(status) {
  if (status === "partially_downloaded") return { cls: "partial", tx: "частично" };
  if (status === "cancelled") return { cls: "cancelled", tx: "отменён" };
  return null;
}
function renderLibrary() {
  const ul = E("libList"); ul.innerHTML = "";
  E("libEmpty").hidden = libState.list.length > 0;
  for (const p of libState.list) {
    const li = document.createElement("li"); li.className = "card";
    li.appendChild(coverEl("thumb", covUrl(p.key)));
    const body = document.createElement("div"); body.className = "card-body";
    const title = document.createElement("div"); title.className = "card-title"; title.textContent = p.title;
    const sub = document.createElement("div"); sub.className = "card-sub";
    sub.textContent = `${p.count} ${trkPlur(p.count)} · ${fmtSize(p.size)}`;
    body.appendChild(title); body.appendChild(sub); li.appendChild(body);
    const b = badgeFor(p.status);
    if (b) { const el = document.createElement("span"); el.className = "badge " + b.cls; el.textContent = b.tx; li.appendChild(el); }
    const chev = document.createElement("span"); chev.className = "chev"; chev.textContent = "›"; li.appendChild(chev);
    li.addEventListener("click", () => openLibDetail(p.key));
    ul.appendChild(li);
  }
}

// ── детали плейлиста (обложки + удаление с перенумерацией) ──
function openLibDetail(key) { libState.key = key; loadLibDetail(); document.body.classList.add("libdetail"); }
E("libDetailBack").addEventListener("click", () => { document.body.classList.remove("libdetail"); libState.key = null; });

async function loadLibDetail() {
  const d = await apiGet("/api/library/detail?pl=" + encodeURIComponent(libState.key));
  if (!d) { document.body.classList.remove("libdetail"); return; }
  libState.detail = d; renderLibDetail();
}
function renderLibDetail() {
  const d = libState.detail; if (!d) return;
  E("libDetailTitle").textContent = d.title || "";
  const cov = E("libDetailCover"); cov.textContent = "♪"; cov.innerHTML = "♪";
  setCover(cov, covUrl(d.key));
  const b = badgeFor(d.status);
  E("libDetailStat").innerHTML = `<b>${d.count}</b> ${trkPlur(d.count)}` + (b ? ` · ${b.tx}` : "");

  const ul = E("libTrackList"); ul.innerHTML = "";
  for (const t of d.tracks) {
    const li = document.createElement("li"); li.className = "trk" + (t.status !== "done" ? " notdone" : "");
    const num = document.createElement("span"); num.className = "trk-i"; num.textContent = String(t.n).padStart(2, "0");
    li.appendChild(num);
    li.appendChild(coverEl("trk-cov", covUrl(d.key, t.file || "")));
    const body = document.createElement("div"); body.className = "trk-body";
    const title = document.createElement("div"); title.className = "trk-title"; title.textContent = t.title || t.file || "—";
    const meta = document.createElement("div"); meta.className = "trk-meta";
    const bits = [];
    if (t.status !== "done") bits.push("не скачан");
    if (t.size) bits.push(fmtSize(t.size));
    if (t.codec) bits.push(t.codec);
    meta.textContent = bits.join(" · ");
    body.appendChild(title); body.appendChild(meta); li.appendChild(body);
    const del = document.createElement("button");
    del.className = "trk-del"; del.setAttribute("data-action", "delete");
    del.setAttribute("aria-label", "Удалить"); del.textContent = "🗑";
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteTrack(t); });
    li.appendChild(del);
    ul.appendChild(li);
  }
}
async function deleteTrack(t) {
  if (!(t.id || t.file)) return;
  const r = await api("/api/library/delete", { pl: libState.key, id: t.id || "", file: t.file || "" });
  if (r && r.ok && r.detail) {
    libState.detail = r.detail;
    renderLibDetail();       // n перенумеровались сами (позиция в списке)
    loadLibrary();           // обновить счётчик/размер в списке
  }
}
