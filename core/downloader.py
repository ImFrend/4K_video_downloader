"""
Ядро загрузки. yt-dlp используется как БИБЛИОТЕКА (Решение 4) —
прогресс приходит через hooks, без парсинга текста.

Логика формата (Решение 2):
  • если у видео есть AAC-дорожка (m4a) → сохраняем как .m4a БЕЗ перекодирования (stream copy)
  • иначе (opus и т.п.) → конвертируем в .mp3

Обложки:
  • значок каждого видео → <трек>.jpg (масштаб до 720px, без увеличения)
  • обложка плейлиста    → folder.jpg в папке плейлиста (видят музыкальные плееры)
  • плюс обложка встраивается в сам аудиофайл (cover art)

Имена файлов — строго UTF-8 (NFC-нормализация), без ASCII-кастрации.
Анти-бан (Решение 6): случайная пауза между треками. --download-archive НЕ используем.
"""
from __future__ import annotations

import random
import re
import subprocess
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

import config


# ──────────────────────────── модели ────────────────────────────
@dataclass
class Track:
    title: str
    url: str
    id: str = ""
    duration: Optional[float] = None
    playlist_index: Optional[int] = None

    # runtime-состояние (его читает TUI)
    status: str = "queued"      # queued | downloading | converting | done | error
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    filepath: str = ""
    error: str = ""


@dataclass
class Playlist:
    tracks: list[Track] = field(default_factory=list)
    title: Optional[str] = None
    thumbnail: Optional[str] = None     # URL обложки плейлиста


ProgressCb = Callable[[Track], None]
SleepCb = Callable[[float], None]


# ──────────────────────────── менеджер ────────────────────────────
class DownloadManager:
    def __init__(self, output_dir: Optional[Path] = None, cookies: Optional[Path] = None):
        self.output_dir = Path(output_dir or config.OUTPUT_DIR)
        self._cancelled = False
        if cookies is not None:
            self.cookies: Optional[Path] = cookies
        elif config.have_cookies():
            self.cookies = config.COOKIES_FILE
        else:
            self.cookies = None

    def cancel(self) -> None:
        self._cancelled = True

    def _base_opts(self) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 30,   # не висеть вечно на сетевом запросе
            "retries": 3,
        }
        if self.cookies:
            opts["cookiefile"] = str(self.cookies)
        if config.YOUTUBE_PLAYER_CLIENTS:
            opts["extractor_args"] = {
                "youtube": {"player_client": list(config.YOUTUBE_PLAYER_CLIENTS)}
            }
        if config.REMOTE_COMPONENTS:
            # разрешить yt-dlp скачать EJS-решатель JS-challenge (n-sig)
            opts["remote_components"] = list(config.REMOTE_COMPONENTS)
        return opts

    @staticmethod
    def _resolve_url(track: Track) -> str:
        if track.id and re.fullmatch(r"[\w-]{11}", track.id):
            return f"https://www.youtube.com/watch?v={track.id}"
        return track.url

    @staticmethod
    def _is_mix(url: str) -> bool:
        """My Mix / radio: list=RD... — динамическое бесконечное радио."""
        return bool(re.search(r"[?&]list=RD", url))

    # ---- 1. разбор плейлиста/трека (лёгкий) ----
    def probe(self, url: str) -> Playlist:
        opts = self._base_opts() | {
            "skip_download": True,
            "extract_flat": "in_playlist",
        }
        # лимит: для микса — жёсткий снимок, чтобы не виснуть на бесконечном радио
        limit = config.MAX_PLAYLIST_ITEMS
        if self._is_mix(url):
            limit = min(limit or config.MIX_SNAPSHOT_LIMIT, config.MIX_SNAPSHOT_LIMIT)
        if limit:
            opts["playlistend"] = limit

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        tracks: list[Track] = []
        entries = info.get("entries") if isinstance(info, dict) else None
        if entries is not None:
            for i, e in enumerate(entries, 1):
                if not e:
                    continue
                tracks.append(Track(
                    title=e.get("title") or e.get("id") or "—",
                    url=e.get("url") or e.get("webpage_url") or e.get("id", ""),
                    id=e.get("id", ""),
                    duration=e.get("duration"),
                    playlist_index=i,
                ))
            return Playlist(tracks=tracks, title=info.get("title"),
                            thumbnail=_best_thumbnail_url(info))

        tracks.append(Track(
            title=info.get("title", "—"),
            url=info.get("webpage_url", url),
            id=info.get("id", ""),
            duration=info.get("duration"),
        ))
        return Playlist(tracks=tracks, title=None,
                        thumbnail=_best_thumbnail_url(info))

    # ---- 2. скачать один трек ----
    def download_track(self, track: Track, on_progress: ProgressCb,
                       subdir: Optional[str] = None) -> None:
        dl_url = self._resolve_url(track)

        # AAC-first: формат предпочитает m4a (140) → копия без перекодирования.
        # ОДИН запрос на трек (без отдельного probe) — главное ускорение:
        # раньше yt-dlp решал n-challenge дважды (probe + download).
        codec = config.AUDIO_PRIMARY

        last_emit = [0.0]  # троттлинг UI: не чаще ~8 раз/сек на трек

        def hook(d: dict) -> None:
            if self._cancelled:
                raise yt_dlp.utils.DownloadCancelled()
            st = d.get("status")
            if st == "downloading":
                # yt-dlp дёргает hook сотни раз/сек → без троттлинга TUI «давится».
                now = time.monotonic()
                if now - last_emit[0] < 0.12:
                    return
                last_emit[0] = now
                track.status = "downloading"
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                track.percent = (done / total * 100.0) if total else 0.0
                track.speed = _fmt_speed(d.get("speed"))
                track.eta = _fmt_eta(d.get("eta"))
                on_progress(track)
            elif st == "finished":
                track.status = "converting"
                track.percent = 100.0
                track.speed = ""
                on_progress(track)

        folder = self.output_dir / _safe(subdir) if subdir else self.output_dir
        folder.mkdir(parents=True, exist_ok=True)
        if track.playlist_index:
            name = f"{track.playlist_index:02d} - %(title)s.%(ext)s"
        else:
            name = "%(title)s.%(ext)s"
        outtmpl = str(folder / name)

        opts = self._base_opts() | {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "writethumbnail": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio",
                 "preferredcodec": codec,
                 "preferredquality": config.AUDIO_QUALITY},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail", "already_have_thumbnail": False},
            ],
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(dl_url, download=True)
            track.filepath = _final_path(res)
            if isinstance(res, dict):
                track.duration = track.duration or res.get("duration")
            # значок видео отдельным файлом (масштаб до 720px)
            if config.SAVE_THUMBNAILS and track.filepath:
                _save_thumbnail(_best_thumbnail_url(res),
                                Path(track.filepath).with_suffix(".jpg"),
                                config.THUMBNAIL_MAX_HEIGHT)
            track.status = "done"
            track.percent = 100.0
            on_progress(track)
        except yt_dlp.utils.DownloadCancelled:
            track.status, track.error = "error", "отменено"
            on_progress(track)
        except Exception as ex:  # noqa: BLE001
            track.status, track.error = "error", _short_err(ex)
            on_progress(track)

    # ---- 3. скачать список с человеческим темпом ----
    def download_all(self, tracks: list[Track], on_progress: ProgressCb,
                     subdir: Optional[str] = None,
                     on_sleep: Optional[SleepCb] = None,
                     cover_url: Optional[str] = None) -> None:
        # обложка плейлиста → folder.jpg (один раз, до треков)
        if config.SAVE_THUMBNAILS and subdir and cover_url:
            cover = self.output_dir / _safe(subdir) / "folder.jpg"
            cover.parent.mkdir(parents=True, exist_ok=True)
            _save_thumbnail(cover_url, cover, config.THUMBNAIL_MAX_HEIGHT)

        workers = max(1, int(config.CONCURRENT_DOWNLOADS))

        # ── параллельно (как 4KVD): N потоков одновременно, без пауз ──
        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [
                    ex.submit(self.download_track, t, on_progress, subdir)
                    for t in tracks
                ]
                for f in futures:
                    try:
                        f.result()
                    except Exception:  # noqa: BLE001
                        pass  # ошибка отдельного трека уже отражена в его статусе
            return

        # ── последовательно: с человеческими паузами между треками ──
        for i, t in enumerate(tracks):
            if self._cancelled:
                break
            self.download_track(t, on_progress, subdir=subdir)
            if i < len(tracks) - 1 and not self._cancelled:
                pause = random.uniform(config.SLEEP_MIN, config.SLEEP_MAX)
                if on_sleep:
                    on_sleep(pause)
                _interruptible_sleep(pause, lambda: self._cancelled)


# ──────────────────────────── обложки ────────────────────────────
def _best_thumbnail_url(info: dict) -> Optional[str]:
    """Берём самую большую доступную обложку (downscale до 720 сделаем позже)."""
    best_url, best_score = None, -1
    for t in info.get("thumbnails") or []:
        url = t.get("url")
        if not url:
            continue
        score = t.get("height") or t.get("width") or t.get("preference") or 0
        if score > best_score:
            best_url, best_score = url, score
    return best_url or info.get("thumbnail")


def _save_thumbnail(url: Optional[str], dest: Path, max_h: int = 720) -> bool:
    """Скачать обложку и масштабировать до высоты max_h (без увеличения). → JPG."""
    if not url:
        return False
    tmp = dest.with_name(dest.stem + ".orig")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            tmp.write_bytes(r.read())
    except Exception:  # noqa: BLE001
        return False

    try:
        # scale=-2:'min(max_h,ih)' — высота <= max_h, ширина кратна 2, без upscale
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
             "-vf", f"scale=-2:'min({max_h},ih)'", str(dest)],
            check=False,
        )
        ok = dest.exists() and dest.stat().st_size > 0
    except FileNotFoundError:
        # ffmpeg нет — сохраним хотя бы оригинал
        tmp.replace(dest)
        ok = dest.exists()
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return ok


# ──────────────────────────── утилиты ────────────────────────────
def _safe(name: str) -> str:
    """Безопасное имя папки: строго UTF-8 (NFC), без запрещённых символов."""
    name = unicodedata.normalize("NFC", str(name))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(" ._")  # убрать ведущие/замыкающие точки/подчёркивания/пробелы
    return name or "playlist"


def _fmt_speed(bps: Optional[float]) -> str:
    if not bps:
        return ""
    for unit in ("B", "KB", "MB"):
        if bps < 1024:
            return f"{bps:.1f} {unit}/s"
        bps /= 1024
    return f"{bps:.1f} GB/s"


def _fmt_eta(sec: Optional[float]) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _short_err(ex: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(ex))  # убрать ANSI-цвета yt-dlp
    return (msg[:120] + "…") if len(msg) > 120 else msg


def _final_path(info: dict) -> str:
    try:
        rd = info.get("requested_downloads")
        if rd:
            return rd[0].get("filepath", "")
    except Exception:  # noqa: BLE001
        pass
    return info.get("filepath", "")


def _interruptible_sleep(seconds: float, is_cancelled: Callable[[], bool]) -> None:
    import time
    waited, step = 0.0, 0.2
    while waited < seconds:
        if is_cancelled():
            return
        time.sleep(min(step, seconds - waited))
        waited += step
