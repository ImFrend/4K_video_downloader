"""
Локальный web-UI (localhost) поверх готового движома загрузки.

Принципы (зафиксированы с пользователем):
  • 100% on-device. Бинд СТРОГО на 127.0.0.1 — никакого облака/сети.
  • Самый лёгкий стек: stdlib http.server (ноль зависимостей) → работает на любом,
    даже самом слабом/старом телефоне. Рисует браузер телефона, не сервер.
  • Очередь до 5 My Mix. Параллелизм: N плейлистов × M треков (по умолчанию 3×2=6),
    человеческий темп: ramp-up/джиттер старта + пауза между плейлистами.
  • Вход не через нас: cookies присылает расширение браузера (POST /api/cookies).
    Сервер только проверяет, жива ли сессия, и говорит об этом прямо — своего
    браузера у проекта нет (см. auth/refresh.py, там же почему).

Запуск:  python main.py web     (или тап по виджету TermuxYoutube)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import config
from core import library
from core.downloader import (DownloadManager, Track, _cleanup_partials,
                             _media_scan, _reap_orphans, _safe)
from auth.cookies_export import (cookies_to_netscape, netscape_has_auth,
                                 validate_netscape)
from auth.refresh import ensure_fresh_cookies, probe_session
from auth.refresh import status as cookie_status

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Заголовок с токеном для /api/cookies. Само его наличие делает запрос
# «непростым» → браузер обязан сперва спросить preflight, а его получает только
# расширение. Имя знают обе стороны: сервер здесь, расширение — из main.py kiwi.
TOKEN_HEADER = "X-TermuxYoutube-Token"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


def _short(ex: Exception) -> str:
    s = str(ex)
    return (s[:140] + "…") if len(s) > 140 else s


_CODEC_BY_EXT = {".m4a": "aac", ".mp3": "mp3", ".opus": "opus", ".ogg": "vorbis"}


def _codec_of(fname: Optional[str]) -> Optional[str]:
    if not fname:
        return None
    return _CODEC_BY_EXT.get(os.path.splitext(fname)[1].lower())


_COVER_CACHE = config.ROOT / ".cache" / "covers"


def _cover_file(folder: Path, file: Optional[str]) -> Optional[Path]:
    """Путь к обложке для отдачи. Сначала готовый sidecar-jpg (SAVE_THUMBNAILS),
    иначе извлекаем встроенную обложку из m4a через ffmpeg и кешируем ВНЕ Music
    (в ROOT/.cache), чтобы не мусорить в фонотеке."""
    if file and ("/" in file or "\\" in file or ".." in file):
        return None                                   # не выпускаем за папку
    if file:
        side = folder / (os.path.splitext(file)[0] + ".jpg")
        if side.exists():
            return side
        audio = folder / file
        if not audio.is_file():
            return None
    else:
        side = library._find_cover(folder)
        if side:
            return folder / side
        m = sorted(folder.glob("[0-9][0-9] - *.m4a"))   # обложка папки = обложка 1-го трека
        if not m:
            return None
        audio = m[0]
    try:
        st = audio.stat()
        key = hashlib.sha1(f"{audio}:{int(st.st_mtime)}".encode()).hexdigest()[:20]
        dest = _COVER_CACHE / (key + ".jpg")
        if dest.exists():
            return dest
        _COVER_CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio),
                        "-an", "-frames:v", "1", "-c:v", "mjpeg", str(dest)],
                       capture_output=True, timeout=20)
        return dest if dest.exists() and dest.stat().st_size > 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# ──────────────────────────── модель очереди ────────────────────────────
class Job:
    """Одна карточка плейлиста в очереди."""

    def __init__(self, jid: int, url: str):
        self.id = jid
        self.url = url
        self.title: Optional[str] = None
        self.thumbnail: Optional[str] = None
        # probing|ready|queued|downloading|cancelling|cleaning|done|cancelled|error
        self.status = "probing"
        self.error = ""
        self.tracks: list[Track] = []
        self.dm: Optional[DownloadManager] = None   # свой на джоб → cancel скоупится
        self.cancel_requested = False
        self.limit: Optional[int] = None            # глубина снимка микса (из UI)


class JobManager:
    """Единое состояние: очередь, настройки, оркестрация загрузки.

    Реюзает существующий DownloadManager.download_all (вся проверенная логика —
    обложки, дедуп, медиаскан, теги — остаётся нетронутой). Параллелизм
    плейлистов задаём здесь через семафор; параллелизм треков — через workers.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.jobs: list[Job] = []
        self._counter = 0
        self.running = False
        self.version = 0          # дёргается при любом изменении → триггер SSE
        self.dm = DownloadManager()
        self.cookies = {"status": "", "msg": ""}
        # состояние проверки сессии: idle | running | ok | error (+ текст для UI)
        self.auth = {"state": "idle", "msg": "", "log": []}
        # окружение против версии кода (после git pull зависимости могут отстать)
        _setup_ok, _setup_msg = config.setup_is_current()
        self.setup = {"ok": _setup_ok, "msg": _setup_msg}
        default_streams = config.WEB_PLAYLIST_CONCURRENCY * config.WEB_TRACKS_PER_PLAYLIST
        self.settings = {"platform": "android", "quality": "max", "streams": default_streams}
        self._refresh_cookie_status()

    # ---- служебное ----
    def _bump(self) -> None:
        self.version += 1

    def _refresh_cookie_status(self) -> None:
        # Не «сколько файлу часов», а результат живой проверки: свежий файл с
        # мёртвой сессией — обычное дело, и раньше индикатор в этом случае врал
        # зелёным. Сеть здесь не дёргаем, читаем уже известное.
        self.cookies = cookie_status()

    # ---- cookies из браузера (расширение для Kiwi) ----
    def accept_cookies(self, raw: list) -> tuple[bool, str]:
        """
        Принять cookies, присланные расширением браузера.

        Состав микса определяется идентичностью сессии, поэтому cookies того
        браузера, где ты смотришь миксы, — это и есть «правильная» станция.
        Пишем через ту же проверку, что и ручной импорт: кривой набор не должен
        подменить рабочий файл.
        """
        cookies = []
        for c in raw if isinstance(raw, list) else []:
            if not isinstance(c, dict) or not c.get("name") or not c.get("domain"):
                continue
            cookies.append(c)
        if not cookies:
            return False, "пустой набор cookies"

        tmp = config.COOKIES_FILE.with_name("cookies.incoming")
        try:
            tmp.write_text(cookies_to_netscape(cookies), encoding="utf-8")
            ok, msg = validate_netscape(tmp)
            if not ok:
                return False, msg
            os.replace(tmp, config.COOKIES_FILE)
        except OSError as ex:
            return False, f"не удалось записать: {ex}"
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

        config.mark_cookies_source("расширение браузера")
        with self.lock:
            self._refresh_cookie_status()
            self._bump()
        # сессия новая — сразу спросим YouTube, узнаёт ли он её. Так человек
        # видит результат тапа по расширению, а не «файл записан».
        self.start_check()
        return True, msg

    # ---- проверить, жива ли сессия ----
    def start_check(self) -> tuple[bool, str]:
        """
        Спросить YouTube, узнаёт ли он наши cookies. Один GET, без браузера.

        Кнопки «войти» здесь нет намеренно: вход живёт в браузере телефона, а
        мёртвую сессию чинит повторный тап по иконке расширения. Держать ради
        этого свой Chromium (proot + Debian, ~2 ГБ) было незачем.
        """
        with self.lock:
            if self.auth.get("state") == "running":
                return False, "уже идёт"
            self.auth = {"state": "running", "msg": "спрашиваю YouTube…", "log": []}
            self._bump()
        threading.Thread(target=self._check_worker, daemon=True).start()
        return True, "ok"

    def _check_worker(self) -> None:
        try:
            code, msg = probe_session()
        except Exception as ex:  # noqa: BLE001
            code, msg = "offline", _short(ex)
        with self.lock:
            self.auth["state"] = "ok" if code == "alive" else "error"
            self.auth["msg"] = msg
            self.auth["log"] = [msg]
            self._refresh_cookie_status()
            self._bump()

    # ---- очередь ----
    def add_url(self, url: str, limit: Optional[int] = None) -> tuple[Optional[int], str]:
        url = (url or "").strip()
        # принимаем и ссылку, и вставленный список видео (снимок очереди с ПК)
        if not url.startswith("http") and not DownloadManager._parse_id_list(url):
            return None, "это не ссылка и не список видео"
        with self.lock:
            active = [j for j in self.jobs if j.status != "error"]
            if len(active) >= config.WEB_MAX_PLAYLISTS:
                return None, f"очередь полна (макс {config.WEB_MAX_PLAYLISTS})"
            if any(j.url == url for j in self.jobs):
                return None, "уже в очереди"
            self._counter += 1
            job = Job(self._counter, url)
            job.limit = limit
            self.jobs.append(job)
            self._bump()
        threading.Thread(target=self._probe, args=(job,), daemon=True).start()
        # предупреждаем ровно там, где это важно: анонимный микс = случайная
        # выдача, и она не совпадёт с тем, что видно в приложении YouTube
        if DownloadManager._is_mix(url) and not netscape_has_auth(config.COOKIES_FILE):
            return job.id, "добавлено — но без входа микс будет случайным"
        return job.id, "ok"

    def _probe(self, job: Job) -> None:
        try:
            pl = self.dm.probe(job.url, limit=job.limit)
            with self.lock:
                job.tracks = pl.tracks
                job.title = pl.title or (pl.tracks[0].title if pl.tracks else "Плейлист")
                job.thumbnail = pl.thumbnail
                job.status = "ready"
                self._bump()
        except Exception as ex:  # noqa: BLE001
            with self.lock:
                job.status, job.error = "error", _short(ex)
                self._bump()

    def remove(self, jid: int) -> None:
        with self.lock:
            if self.running:
                return  # во время загрузки не трогаем очередь
            self.jobs = [j for j in self.jobs if j.id != jid]
            self._bump()

    def cancel(self, jid: Optional[int] = None) -> bool:
        """Кооперативная отмена (jid=None → вся очередь). Ставим флаг на джоб и
        дёргаем его личный dm.cancel(); воркеры встают на следующем hook-тике, а
        зачистка .part и запись статуса — в finally _run_one (там гарантированно
        после остановки воркеров). kill процесса НЕ используем: он не даёт
        отработать cleanup."""
        with self.lock:
            targets = [j for j in self.jobs
                       if jid in (None, j.id)
                       and j.status in ("queued", "downloading", "cancelling")]
            for j in targets:
                j.cancel_requested = True
                j.status = "cancelling"       # мгновенная обратная связь в UI
            self._bump()
        for j in targets:
            if j.dm is not None:      # уже качается → тормозим воркеры
                j.dm.cancel()
        return bool(targets)

    def set_settings(self, data: dict) -> None:
        with self.lock:
            for k in ("platform", "quality", "streams"):
                if k in data:
                    self.settings[k] = data[k]
            try:
                self.settings["streams"] = max(2, min(8, int(self.settings["streams"])))
            except (TypeError, ValueError):
                self.settings["streams"] = 6
            self._bump()

    # ---- запуск ----
    def start(self) -> bool:
        with self.lock:
            if self.running:
                return False
            ready = [j for j in self.jobs if j.status in ("ready", "queued")]
            if not ready:
                return False
            self.running = True
            for j in ready:
                j.status = "queued"
            self._bump()
        threading.Thread(target=self._run_queue, args=(ready,), daemon=True).start()
        return True

    def _run_queue(self, jobs: list[Job]) -> None:
        s = dict(self.settings)
        # ② качество = какой поток брать с YouTube; ① платформа = в какой кодек класть.
        # Меняем глобальный config в рантайме — download_track читает его при вызове,
        # сигнатуры проверенного движка не трогаем.
        qd = config.WEB_QUALITY.get(s["quality"], config.WEB_QUALITY["max"])
        config.AUDIO_FORMAT = qd["format"]
        config.AUDIO_PRIMARY = config.WEB_PLATFORM_CODEC.get(s["platform"], "m4a")
        config.AUDIO_QUALITY = "0"

        # адаптивный делёж бюджета потоков по реально добавленным миксам:
        #   1 микс  → 1 плейлист × min(4, streams)  (один My Mix = до 4 потоков)
        #   3 микса → 3 плейлиста × 2  = 6
        streams = int(s["streams"])
        nactive = max(1, len(jobs))
        pl_conc = max(1, min(nactive, round(streams / config.WEB_TRACKS_PER_PLAYLIST)))
        # floor → суммарно потоков не больше слайдера (он = потолок риска)
        tracks_per = max(1, min(config.WEB_MAX_TRACKS_PER_PLAYLIST, streams // pl_conc))

        # cookies: тихая проверка сессии один раз перед стартом — чтобы «микс
        # приехал случайный» выяснялось до загрузки, а не после.
        try:
            if self.auth.get("state") != "running":
                code, msg = ensure_fresh_cookies()
                with self.lock:
                    self.cookies = cookie_status() | {"status": code, "msg": msg}
                    self._bump()
        except Exception:  # noqa: BLE001
            pass

        sem = threading.Semaphore(pl_conc)
        threads: list[threading.Thread] = []
        for j in jobs:
            sem.acquire()
            t = threading.Thread(target=self._run_one, args=(j, sem, tracks_per), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        with self.lock:
            self.running = False
            self._refresh_cookie_status()
            self._bump()

    def _run_one(self, job: Job, sem: threading.Semaphore, tracks_per: int) -> None:
        job.dm = DownloadManager()             # свой на джоб → отмена не заденет соседей
        if job.cancel_requested:               # отменили ещё в очереди → стартуем отменённым
            job.dm.cancel()
        pl_dir = config.OUTPUT_DIR / _safe(job.title or "playlist")
        try:
            with self.lock:
                if not job.cancel_requested:
                    job.status = "downloading"
                self._bump()

            def on_prog(_tr: Track) -> None:
                with self.lock:
                    self._bump()

            job.dm.download_all(
                job.tracks, on_prog,
                subdir=job.title, cover_url=job.thumbnail,
                workers=tracks_per, start_jitter=config.START_JITTER_MAX,
            )
        except Exception as ex:  # noqa: BLE001
            with self.lock:
                job.status, job.error = "error", _short(ex)
                self._bump()
        finally:
            cancelled = job.cancel_requested or (job.dm is not None and job.dm._cancelled)
            if cancelled:                       # ── подмести .part/.ytdl ──
                with self.lock:
                    job.status = "cleaning"
                    self._bump()
                _cleanup_partials(pl_dir)
            with self.lock:
                if job.status != "error":
                    job.status = "cancelled" if cancelled else "done"
                self._bump()
            # манифест пишем В ЛЮБОМ исходе (complete/partial/cancelled) — источник
            # правды Библиотеки; статус выводится из фактических статусов треков.
            self._write_manifest(job, pl_dir)
            # человеческая пауза «пересел на новый альбом» перед освобождением слота
            time.sleep(random.uniform(config.PLAYLIST_PAUSE_MIN, config.PLAYLIST_PAUSE_MAX))
            sem.release()

    def _write_manifest(self, job: Job, pl_dir) -> None:
        tracks = []
        for t in job.tracks:
            done = t.status == "done"
            fpath = t.filepath if done else ""
            fname = os.path.basename(fpath) if fpath else None
            size = 0
            if fpath:
                try:
                    size = os.path.getsize(fpath)
                except OSError:
                    size = 0
            tracks.append({
                "id": t.id or None,
                "file": fname,
                "title": t.title,
                "index": t.playlist_index,
                "size": size,
                "duration": t.duration,
                "codec": _codec_of(fname),
                "status": "done" if done else ("error" if t.status == "error" else "cancelled"),
            })
        prev = library.load_manifest(pl_dir) or {}
        man = {
            "title": job.title or "playlist",
            "source": job.url,
            "cover": library._find_cover(pl_dir),
            "created": prev.get("created") or int(time.time()),
            "expected": len(job.tracks),   # сколько планировали → база для partial
            "tracks": tracks,
        }
        man["status"] = library.derive_pl_status(tracks, man["expected"])
        library.save_manifest(pl_dir, man)

    # ---- снимок для фронта ----
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "settings": dict(self.settings),
                "cookies": dict(self.cookies),
                # list() — снимок хвоста лога: json.dumps идёт уже без блокировки
                "auth": {**self.auth, "log": list(self.auth.get("log", []))},
                "setup": dict(self.setup),
                "max": config.WEB_MAX_PLAYLISTS,
                "playlists": [self._job_json(j) for j in self.jobs],
            }

    @staticmethod
    def _job_json(j: Job) -> dict:
        done = sum(1 for t in j.tracks if t.status == "done")
        return {
            "id": j.id, "title": j.title, "thumbnail": j.thumbnail,
            "status": j.status, "error": j.error,
            "total": len(j.tracks), "done": done,
            "tracks": [
                {"i": t.playlist_index or k + 1, "title": t.title,
                 "status": t.status, "percent": round(t.percent, 1),
                 "speed": t.speed, "eta": t.eta, "error": t.error}
                for k, t in enumerate(j.tracks)
            ],
        }


MANAGER = JobManager()


# ──────────────────────────── HTTP ────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "TermuxYoutube"

    def log_message(self, *_args) -> None:  # тишина в консоли
        pass

    # --- guard от DNS-rebinding: пускаем только localhost ---
    # Сервер слушает 127.0.0.1, но браузер отдаёт заголовок Host таким, какой
    # набрали в адресной строке. Домен, у которого A-запись указывает на
    # 127.0.0.1, обошёл бы бинд — не обойдёт этот guard.
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "")

    # --- свои же страницы: единственный источник команд очереди ---
    # Без этой проверки любой сайт, открытый в браузере телефона, мог бы дёрнуть
    # POST /api/add или /api/start: Content-Type text/plain делает запрос
    # «простым», preflight не запрашивается, и запрос доходит — ответ CORS
    # спрячет, но действие уже произошло. Читать он ничего не может, а вот
    # ставить в очередь и запускать загрузки мог бы.
    _SELF_ORIGINS = (f"http://{config.WEB_HOST}:{config.WEB_PORT}",
                     f"http://localhost:{config.WEB_PORT}")

    def _same_origin(self) -> bool:
        """Запрос пришёл от нашей же страницы (или не из браузера вообще)."""
        origin = self.headers.get("Origin") or ""
        if origin:
            return origin in self._SELF_ORIGINS
        # Origin нет — это не кросс-сайтовый браузерный запрос: современные
        # браузеры ставят его на любой POST, включая формы. Значит curl/CLI.
        # Sec-Fetch-Site, если браузер его прислал, обязан быть same-origin.
        site = self.headers.get("Sec-Fetch-Site")
        return site in (None, "same-origin", "none")

    # --- cookies принимаем ТОЛЬКО от НАШЕГО расширения ---
    # Три замка, потому что тут отдают доступ к аккаунту:
    #   1) origin обязан быть chrome-extension:// (у страниц он http/https);
    #   2) Content-Type: application/json и заголовок с токеном — оба делают
    #      запрос «непростым», то есть требуют preflight, а его мы даём только
    #      расширению. Формой или simple-запросом такое не подделать;
    #   3) токен из .api-token — его знает только расширение, собранное этой
    #      установкой (python main.py kiwi зашивает его внутрь). Без него чужое
    #      расширение, стоящее в том же браузере, могло бы подсунуть свои cookies.
    def _ext_origin(self) -> Optional[str]:
        origin = self.headers.get("Origin") or ""
        if not origin:
            return ""
        return origin if origin.startswith("chrome-extension://") else None

    def _token_ok(self) -> bool:
        want = config.api_token()
        got = self.headers.get(TOKEN_HEADER) or ""
        # сравнение постоянного времени: токен локальный, но привычка дешёвая
        return bool(want) and hmac.compare_digest(got, want)

    def _cors(self, origin: str) -> None:
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Headers",
                         f"Content-Type, {TOKEN_HEADER}")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self) -> None:      # preflight от расширения
        origin = self._ext_origin()
        if not self._host_ok() or origin is None \
                or self.path.split("?")[0] != "/api/cookies":
            self._send(403, b"forbidden", "text/plain")
            return
        self.send_response(204)
        self._cors(origin)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, json.JSONDecodeError):
            return {}

    # --- GET ---
    def do_GET(self) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden", "text/plain")
            return
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_static("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/state":
            self._json(MANAGER.snapshot())
        elif path == "/api/events":
            self._sse()
        elif path == "/api/library":
            self._json({"root": str(config.OUTPUT_DIR),
                        "playlists": library.scan_library(config.OUTPUT_DIR)})
        elif path == "/api/tracks":
            self._json({"tracks": library.all_tracks(config.OUTPUT_DIR)})
        elif path == "/api/library/detail":
            key = (parse_qs(urlparse(self.path).query).get("pl") or [""])[0]
            d = library.detail(config.OUTPUT_DIR, key)
            if d is None:
                self._send(404, b"not found", "text/plain")
            else:
                self._json(d)
        elif path == "/api/cover":
            qs = parse_qs(urlparse(self.path).query)
            folder = library.resolve_folder(config.OUTPUT_DIR, (qs.get("pl") or [""])[0])
            cf = _cover_file(folder, (qs.get("file") or [None])[0]) if folder else None
            if cf and cf.is_file():
                self._send(200, cf.read_bytes(), "image/jpeg")
            else:
                self._send(404, b"no cover", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def _serve_static(self, rel: str) -> None:
        rel = rel.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR or not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = _MIME.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = -1
        try:
            while True:
                v = MANAGER.version
                if v != last:
                    last = v
                    data = json.dumps(MANAGER.snapshot(), ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                else:
                    # пинг-комментарий держит соединение и ловит обрыв вкладки
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    # --- POST ---
    def do_POST(self) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden", "text/plain")
            return
        path = self.path.split("?")[0]

        if path == "/api/cookies":
            origin = self._ext_origin()
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if origin is None or ctype != "application/json" or not self._token_ok():
                self._send(403, b"forbidden", "text/plain")
                return
            ok, msg = MANAGER.accept_cookies(self._read_json().get("cookies"))
            body_b = json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self._cors(origin)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body_b)))
            self.end_headers()
            try:
                self.wfile.write(body_b)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        # всё остальное — команды очереди, и их отдаёт только наша страница
        if not self._same_origin():
            self._send(403, b"forbidden", "text/plain")
            return

        body = self._read_json()

        if path == "/api/add":
            lim = body.get("limit")
            try:
                lim = int(lim) if lim else None
            except (TypeError, ValueError):
                lim = None
            jid, msg = MANAGER.add_url(body.get("url", ""), limit=lim)
            self._json({"ok": jid is not None, "id": jid, "msg": msg})
        elif path == "/api/settings":
            MANAGER.set_settings(body)
            self._json({"ok": True})
        elif path == "/api/start":
            ok = MANAGER.start()
            self._json({"ok": ok})
        elif path == "/api/remove":
            MANAGER.remove(int(body.get("id", 0)))
            self._json({"ok": True})
        elif path == "/api/cancel":
            jid = body.get("id")
            ok = MANAGER.cancel(int(jid) if jid is not None else None)
            self._json({"ok": ok})
        elif path == "/api/library/delete":
            ident = str(body.get("id") or body.get("file") or "")
            res = library.delete_track(config.OUTPUT_DIR, str(body.get("pl") or ""), ident)
            if res is None:
                self._send(404, b"not found", "text/plain")
            else:
                if res.get("deleted"):
                    _media_scan(res["deleted"])   # дропнуть «призрак» из MediaStore
                # свежая карточка с уже перенумерованными n
                d = library.detail(config.OUTPUT_DIR, str(body.get("pl") or ""))
                self._json({"ok": res["ok"], "detail": d})
        elif path == "/api/check":
            ok, msg = MANAGER.start_check()
            self._json({"ok": ok, "msg": msg})
        else:
            self._send(404, b"not found", "text/plain")


# ──────────────────────────── запуск ────────────────────────────
def _open_browser(url: str) -> None:
    """Открыть UI в браузере телефона (termux-open-url) или десктопа."""
    if config.IS_TERMUX:
        try:
            subprocess.Popen(["termux-open-url", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (FileNotFoundError, OSError):
            pass
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def serve(open_browser: bool = True) -> int:
    addr = (config.WEB_HOST, config.WEB_PORT)
    httpd = ThreadingHTTPServer(addr, Handler)
    httpd.daemon_threads = True
    reaped = _reap_orphans(config.OUTPUT_DIR)   # подмести .part/.ytdl от прошлого краха
    if reaped:
        print(f"  подметено хвостов прошлой загрузки: {reaped}")
    url = f"http://{config.WEB_HOST}:{config.WEB_PORT}"
    print(f"  TermuxYoutube web -> {url}")
    print("  (Ctrl+C to stop)")
    if open_browser:
        _open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  остановлено")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    serve()
