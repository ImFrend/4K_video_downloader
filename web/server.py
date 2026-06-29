"""
Локальный web-UI (localhost) поверх готового движома загрузки.

Принципы (зафиксированы с пользователем):
  • 100% on-device. Бинд СТРОГО на 127.0.0.1 — никакого облака/сети.
  • Самый лёгкий стек: stdlib http.server (ноль зависимостей) → работает на любом,
    даже самом слабом/старом телефоне. Рисует браузер телефона, не сервер.
  • Очередь до 5 My Mix. Параллелизм: N плейлистов × M треков (по умолчанию 3×2=6),
    человеческий темп: ramp-up/джиттер старта + пауза между плейлистами.
  • Никакой кнопки refresh: cookies обновляются сами, по времени, невидимо.

Запуск:  python main.py web     (или ~/.shortcuts/start.sh на телефоне)
"""
from __future__ import annotations

import json
import random
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import config
from core.downloader import DownloadManager, Track
from auth.refresh import cookies_age_hours, ensure_fresh_cookies

STATIC_DIR = Path(__file__).resolve().parent / "static"

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


# ──────────────────────────── модель очереди ────────────────────────────
class Job:
    """Одна карточка плейлиста в очереди."""

    def __init__(self, jid: int, url: str):
        self.id = jid
        self.url = url
        self.title: Optional[str] = None
        self.thumbnail: Optional[str] = None
        self.status = "probing"   # probing|ready|queued|downloading|done|error
        self.error = ""
        self.tracks: list[Track] = []


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
        default_streams = config.WEB_PLAYLIST_CONCURRENCY * config.WEB_TRACKS_PER_PLAYLIST
        self.settings = {"platform": "android", "quality": "max", "streams": default_streams}
        self._refresh_cookie_status()

    # ---- служебное ----
    def _bump(self) -> None:
        self.version += 1

    def _refresh_cookie_status(self) -> None:
        age = cookies_age_hours()
        if age is None:
            self.cookies = {"status": "none", "msg": "вход не выполнен"}
        elif age > config.COOKIES_MAX_AGE_HOURS:
            self.cookies = {"status": "stale", "msg": f"устарели ({age:.0f}ч)"}
        else:
            self.cookies = {"status": "fresh", "msg": f"свежие ({age:.1f}ч)"}

    # ---- очередь ----
    def add_url(self, url: str) -> tuple[Optional[int], str]:
        url = (url or "").strip()
        if not url.startswith("http"):
            return None, "это не ссылка"
        with self.lock:
            active = [j for j in self.jobs if j.status != "error"]
            if len(active) >= config.WEB_MAX_PLAYLISTS:
                return None, f"очередь полна (макс {config.WEB_MAX_PLAYLISTS})"
            if any(j.url == url for j in self.jobs):
                return None, "уже в очереди"
            self._counter += 1
            job = Job(self._counter, url)
            self.jobs.append(job)
            self._bump()
        threading.Thread(target=self._probe, args=(job,), daemon=True).start()
        return job.id, "ok"

    def _probe(self, job: Job) -> None:
        try:
            pl = self.dm.probe(job.url)
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

        streams = int(s["streams"])
        tracks_per = max(1, config.WEB_TRACKS_PER_PLAYLIST)
        pl_conc = max(1, round(streams / tracks_per))   # 6→3 плейлиста, 4→2, 8→4

        # cookies: тихий авто-refresh по времени (без кнопки), один раз перед стартом
        try:
            code, msg = ensure_fresh_cookies()
            with self.lock:
                self.cookies = {"status": code, "msg": msg}
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
        try:
            with self.lock:
                job.status = "downloading"
                self._bump()

            def on_prog(_tr: Track) -> None:
                with self.lock:
                    self._bump()

            self.dm.download_all(
                job.tracks, on_prog,
                subdir=job.title, cover_url=job.thumbnail,
                workers=tracks_per, start_jitter=config.START_JITTER_MAX,
            )
            with self.lock:
                job.status = "done"
                self._bump()
        except Exception as ex:  # noqa: BLE001
            with self.lock:
                job.status, job.error = "error", _short(ex)
                self._bump()
        finally:
            # человеческая пауза «пересел на новый альбом» перед освобождением слота
            time.sleep(random.uniform(config.PLAYLIST_PAUSE_MIN, config.PLAYLIST_PAUSE_MAX))
            sem.release()

    # ---- снимок для фронта ----
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "settings": dict(self.settings),
                "cookies": dict(self.cookies),
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
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "")

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
        body = self._read_json()

        if path == "/api/add":
            jid, msg = MANAGER.add_url(body.get("url", ""))
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
