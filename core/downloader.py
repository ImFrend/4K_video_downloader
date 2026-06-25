"""
Ядро загрузки. yt-dlp используется как БИБЛИОТЕКА (Решение 4) —
прогресс приходит через hooks, без парсинга текста.

Логика формата (Решение 2):
  • если у видео есть AAC-дорожка (m4a) → сохраняем как .m4a БЕЗ перекодирования (stream copy)
  • иначе (opus и т.п.) → конвертируем в .mp3

Анти-бан (Решение 6): случайная пауза между треками. --download-archive НЕ используем.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

import config


# ──────────────────────────── модель трека ────────────────────────────
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


ProgressCb = Callable[[Track], None]
SleepCb = Callable[[float], None]  # уведомить UI о паузе между треками (необязательно)


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

    # ---- общие опции ----
    def _base_opts(self) -> dict:
        opts = {"quiet": True, "no_warnings": True, "noprogress": True}
        if self.cookies:
            opts["cookiefile"] = str(self.cookies)
        return opts

    @staticmethod
    def _resolve_url(track: Track) -> str:
        """Строим надёжный URL: из id — канонический watch-URL, иначе берём как есть."""
        if track.id and re.fullmatch(r"[\w-]{11}", track.id):
            return f"https://www.youtube.com/watch?v={track.id}"
        return track.url

    # ---- 1. разбор плейлиста/трека (лёгкий, минимум запросов) ----
    def probe(self, url: str) -> list[Track]:
        opts = self._base_opts() | {
            "skip_download": True,
            "extract_flat": "in_playlist",
        }
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
        else:
            tracks.append(Track(
                title=info.get("title", "—"),
                url=info.get("webpage_url", url),
                id=info.get("id", ""),
                duration=info.get("duration"),
            ))
        return tracks, (info.get("title") if entries is not None else None)

    # ---- решаем кодек: AAC доступен → m4a (копия), иначе mp3 ----
    @staticmethod
    def _pick_codec(info: dict) -> str:
        for f in info.get("formats", []):
            is_audio_only = f.get("vcodec") in (None, "none")
            if not is_audio_only:
                continue
            ac = (f.get("acodec") or "").lower()
            if f.get("ext") == "m4a" or "mp4a" in ac or "aac" in ac:
                return config.AUDIO_PRIMARY  # m4a
        return config.AUDIO_FALLBACK         # mp3

    # ---- 2. скачать один трек ----
    def download_track(self, track: Track, on_progress: ProgressCb,
                       subdir: Optional[str] = None) -> None:
        dl_url = self._resolve_url(track)

        # 2a. полный probe — узнать кодек (без скачивания медиа)
        try:
            with yt_dlp.YoutubeDL(self._base_opts() | {"skip_download": True}) as ydl:
                info = ydl.extract_info(dl_url, download=False)
        except Exception as ex:  # noqa: BLE001
            track.status, track.error = "error", _short_err(ex)
            on_progress(track)
            return

        codec = self._pick_codec(info)
        track.duration = track.duration or info.get("duration")

        # 2b. progress hook → обновляем модель → дёргаем UI
        def hook(d: dict) -> None:
            if self._cancelled:
                raise yt_dlp.utils.DownloadCancelled()
            st = d.get("status")
            if st == "downloading":
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

        # 2c. куда писать (плейлист → подпапка)
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
            track.status = "done"
            track.percent = 100.0
            on_progress(track)
        except yt_dlp.utils.DownloadCancelled:
            track.status = "error"
            track.error = "отменено"
            on_progress(track)
        except Exception as ex:  # noqa: BLE001
            track.status, track.error = "error", _short_err(ex)
            on_progress(track)

    # ---- 3. скачать список с человеческим темпом (Решение 6) ----
    def download_all(self, tracks: list[Track], on_progress: ProgressCb,
                     subdir: Optional[str] = None,
                     on_sleep: Optional[SleepCb] = None) -> None:
        for i, t in enumerate(tracks):
            if self._cancelled:
                break
            self.download_track(t, on_progress, subdir=subdir)
            # пауза между треками — кроме последнего
            if i < len(tracks) - 1 and not self._cancelled:
                pause = random.uniform(config.SLEEP_MIN, config.SLEEP_MAX)
                if on_sleep:
                    on_sleep(pause)
                _interruptible_sleep(pause, lambda: self._cancelled)


# ──────────────────────────── утилиты ────────────────────────────
def _safe(name: str) -> str:
    """Безопасное имя папки."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "playlist"


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
    msg = str(ex)
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)  # убрать ANSI-цвета yt-dlp
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
    end = seconds
    step = 0.2
    waited = 0.0
    while waited < end:
        if is_cancelled():
            return
        time.sleep(min(step, end - waited))
        waited += step
