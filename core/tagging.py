"""
Теги и обложка для m4a без ffmpeg.

Зачем отдельно: ffmpeg нужен был ровно для косметики — вшить обложку, album и
track=N/всего. Само аудио мы и так берём готовым потоком AAC
(`bestaudio[ext=m4a]`), то есть перекодирования нет. А ffmpeg — самая тяжёлая
часть сборки, и в едином APK за него пришлось бы платить десятками мегабайт.
mutagen пишет те же атомы напрямую и весит килобайты.

Обложку берём сразу в jpg (`i.ytimg.com/vi/<id>/…jpg`): контейнер m4a принимает
в `covr` только jpeg/png, а YouTube в выдаче форматов часто отдаёт webp — тогда
понадобился бы конвертер.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Optional

# Атомы MPEG-4, которые читают плееры (Samsung Music, VLC, foobar).
_TITLE = "\xa9nam"
_ARTIST = "\xa9ART"
_ALBUM = "\xa9alb"
_ALBUM_ARTIST = "aART"
_TRACK = "trkn"

# Варианты обложки от самой крупной к мелкой: hq720 есть не у всех роликов.
THUMBNAIL_NAMES = ("maxresdefault", "hq720", "hqdefault", "mqdefault")


def thumbnail_urls(video_id: str) -> list[str]:
    return [f"https://i.ytimg.com/vi/{video_id}/{n}.jpg" for n in THUMBNAIL_NAMES]


def fetch_thumbnail(video_id: str, timeout: float = 15.0) -> Optional[bytes]:
    """Первая доступная обложка в jpg. None — ни одна не отдалась."""
    for url in thumbnail_urls(video_id):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
        except Exception:  # noqa: BLE001
            continue
        # YouTube на отсутствующий размер отвечает 200 и заглушкой-картинкой
        if is_jpeg(data) and len(data) > 2048:
            return data
    return None


def is_jpeg(data: bytes) -> bool:
    return len(data) > 3 and data[:3] == b"\xff\xd8\xff"


def tag_m4a(path: Path, *, title: str = "", artist: str = "", album: str = "",
            track: Optional[int] = None, track_total: Optional[int] = None,
            cover: Optional[bytes] = None) -> tuple[bool, str]:
    """
    Проставить теги готовому m4a. Возвращает (успех, что сделано/почему нет).
    Файл не трогаем, если mutagen не установлен — трек от этого не портится.
    """
    try:
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError:
        return False, "нет mutagen"

    try:
        meta = MP4(str(path))
    except Exception as ex:  # noqa: BLE001
        return False, f"не открылся: {ex}"

    if meta.tags is None:
        meta.add_tags()
    done = []
    if title:
        meta.tags[_TITLE] = [title]
        done.append("название")
    if artist:
        meta.tags[_ARTIST] = [artist]
        meta.tags[_ALBUM_ARTIST] = [artist]
        done.append("исполнитель")
    if album:
        meta.tags[_ALBUM] = [album]
        done.append("альбом")
    if track:
        # Samsung Music сортирует папку по этому тегу, а не по имени файла
        meta.tags[_TRACK] = [(int(track), int(track_total or 0))]
        done.append("номер")
    if cover and is_jpeg(cover):
        meta.tags["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
        done.append("обложка")

    try:
        meta.save()
    except Exception as ex:  # noqa: BLE001
        return False, f"не записалось: {ex}"
    return True, ", ".join(done) or "нечего писать"
