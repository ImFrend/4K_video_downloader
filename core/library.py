"""
core/library.py — модель «Библиотеки»: то, что уже скачано на диск.

Источник правды по плейлисту — per-folder манифест `.termuxyoutube.json`. Если
его нет или он устарел относительно файлов (краш до записи, легаси-папки от
прошлых версий) — реконсилим с диска: пересобираем список из реальных
`NN - *.m4a` и усыновляем папку, записав манифест.

Разделение, ради которого всё затевалось:
  • ИМЯ ФАЙЛА (`03 - Song.m4a`) — иммутабельный id трека на диске.
  • НОМЕР В UI (`n`) — позиция в списке, динамическая: удалили трек → соседи
    перенумеровались, файлы не трогаются (см. detail(): поле `n`).

Только stdlib. Модуль ОБЯЗАН импортироваться и работать без yt-dlp/ffmpeg —
чтобы гонять его в тестах и headless через adb. config сюда не тащим: корень
(OUTPUT_DIR) передаётся аргументом.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

MANIFEST_NAME = ".termuxyoutube.json"
ARCHIVE_NAME = ".downloaded.txt"        # видео-id уже скачанного (дедуп), пишет downloader
AUDIO_EXTS = (".m4a", ".mp3", ".opus", ".ogg", ".aac", ".flac", ".wav")
COVER_NAMES = ("folder.jpg", "cover.jpg")

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partially_downloaded"
STATUS_CANCELLED = "cancelled"

# "01 - Title.m4a" → (index="01", title="Title", ext="m4a")
_FNAME_RE = re.compile(r"^(\d{2,4}) - (.+)\.([A-Za-z0-9]+)$")


# ──────────────────────────── манифест ────────────────────────────
def manifest_path(folder) -> Path:
    return Path(folder) / MANIFEST_NAME


def _archive_path(folder) -> Path:
    return Path(folder) / ARCHIVE_NAME


def load_manifest(folder) -> Optional[dict]:
    try:
        return json.loads(manifest_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_manifest(folder, data) -> bool:
    """Атомарная запись (tmp + os.replace), best-effort — на диске никогда не
    остаётся полу-записанный манифест."""
    p = manifest_path(folder)
    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def derive_pl_status(tracks: list, expected: Optional[int] = None) -> str:
    """Статус плейлиста — ПРОИЗВОДНАЯ от треков, а не отдельный флаг (иначе
    рассинхрон). `expected` — сколько треков планировалось (из манифеста); без
    него ориентир = длина списка."""
    done = sum(1 for t in tracks if t.get("status") == "done")
    total = expected if expected is not None else len(tracks)
    if total <= 0 or done == 0:
        return STATUS_CANCELLED
    if done >= total:
        return STATUS_COMPLETE
    return STATUS_PARTIAL


# ──────────────────────────── диск ────────────────────────────
def _folder_ctime(folder) -> int:
    try:
        return int(os.stat(folder).st_mtime)
    except OSError:
        return 0


def _find_cover(folder) -> Optional[str]:
    for name in COVER_NAMES:
        if (Path(folder) / name).exists():
            return name
    return None


def _track_cover(folder, stem: str) -> Optional[str]:
    # отдельный значок трека (только если качали с SAVE_THUMBNAILS): "<NN - Title>.jpg"
    name = stem + ".jpg"
    return name if (Path(folder) / name).exists() else None


def _scan_disk_tracks(folder) -> list:
    """Отсортированный список треков из файлов `NN - *.ext`. Файл на диске = трек
    докачан (частичные — это `.part`, их вычищает cancel-cleanup)."""
    rows = []
    try:
        with os.scandir(folder) as it:
            entries = list(it)
    except OSError:
        return rows
    for e in entries:
        if not e.is_file():
            continue
        m = _FNAME_RE.match(e.name)
        if not m or ("." + m.group(3).lower()) not in AUDIO_EXTS:
            continue
        try:
            size = e.stat().st_size
        except OSError:
            size = 0
        rows.append({
            "file": e.name,
            "index": int(m.group(1)),
            "title": m.group(2),
            "size": size,
            "cover": _track_cover(folder, e.name.rsplit(".", 1)[0]),
            "status": "done",
        })
    rows.sort(key=lambda r: (r["index"], r["file"]))
    return rows


def _looks_like_playlist(folder) -> bool:
    """Отсекаем чужие папки в Music: наша — та, где есть манифест/архив или хотя
    бы один аудиофайл вида `NN - *.ext`."""
    if manifest_path(folder).exists() or _archive_path(folder).exists():
        return True
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.is_file():
                    m = _FNAME_RE.match(e.name)
                    if m and ("." + m.group(3).lower()) in AUDIO_EXTS:
                        return True
    except OSError:
        pass
    return False


# ──────────────────────────── реконсиляция ────────────────────────────
def _manifest_fresh(man: dict, disk: list) -> bool:
    """Манифест актуален, если файлы его «done»-треков в точности = файлам на
    диске. Иначе (файлы добавили/удалили мимо нас, краш) — пересобираем."""
    done_files = {t.get("file") for t in man.get("tracks", []) if t.get("status") == "done"}
    disk_files = {d["file"] for d in disk}
    return done_files == disk_files


def reconcile(folder, adopt: bool = True) -> dict:
    """Вернуть полный манифест папки, синхронизированный с диском. Если манифеста
    не было / он устарел и adopt=True — записать пересобранный на диск
    (усыновление легаси-папок)."""
    folder = Path(folder)
    disk = _scan_disk_tracks(folder)
    man = load_manifest(folder) or {}
    fresh = bool(man) and _manifest_fresh(man, disk)

    if fresh:
        # доверяем манифесту (id, порядок, отменённые треки), но размер/наличие
        # берём с диска — файл мог быть удалён «руками».
        disk_by_file = {d["file"]: d for d in disk}
        tracks = []
        for t in man.get("tracks", []):
            d = disk_by_file.get(t.get("file"))
            tracks.append({
                "id": t.get("id"),
                "file": t.get("file"),
                "title": t.get("title"),
                "index": t.get("index"),
                "size": d["size"] if d else t.get("size", 0),
                "duration": t.get("duration"),
                "codec": t.get("codec"),
                "cover": (d.get("cover") if d else None) or t.get("cover"),
                "status": "done" if d else "cancelled",
            })
    else:
        # rebuild из диска: id/кодек/длительность неизвестны (в .downloaded.txt
        # id есть, но порядок = порядок докачки, к файлам надёжно не мапится).
        tracks = [{
            "id": None, "file": d["file"], "title": d["title"], "index": d["index"],
            "size": d["size"], "duration": None, "codec": None,
            "cover": d["cover"], "status": "done",
        } for d in disk]

    out = {
        "title": man.get("title") or folder.name,
        "source": man.get("source"),
        "cover": _find_cover(folder) or man.get("cover"),
        "created": man.get("created") or _folder_ctime(folder),
        "expected": man.get("expected"),   # из манифеста, даже устаревшего
        "tracks": tracks,
    }
    out["status"] = derive_pl_status(tracks, out["expected"])
    if adopt and not fresh:
        save_manifest(folder, out)
    return out


# ──────────────────────────── публичное API ────────────────────────────
def scan_library(root) -> list:
    """Сводка по всем плейлистам в OUTPUT_DIR (одним уровнем вглубь), свежие
    сверху."""
    root = Path(root)
    out = []
    try:
        with os.scandir(root) as it:
            entries = list(it)
    except OSError:
        return out
    for e in entries:
        if not e.is_dir() or not _looks_like_playlist(e.path):
            continue
        man = reconcile(e.path)
        done = [t for t in man["tracks"] if t["status"] == "done"]
        out.append({
            "key": e.name,
            "title": man["title"],
            "cover": man["cover"],
            "count": len(done),
            "expected": man["expected"],
            "size": sum(t.get("size") or 0 for t in done),
            "status": man["status"],
            "created": man["created"],
        })
    out.sort(key=lambda p: p.get("created") or 0, reverse=True)
    return out


def all_tracks(root) -> list:
    """Плоский список всех СКАЧАННЫХ треков по всем плейлистам (для экрана
    «Скачанные»). Новые плейлисты — сверху, внутри — в порядке трека."""
    out = []
    for pl in scan_library(root):
        d = detail(root, pl["key"])
        if not d:
            continue
        for t in d["tracks"]:
            if t.get("status") == "done":
                out.append({"pl": pl["key"], "pl_title": pl["title"], **t})
    return out


def resolve_folder(root, key: str) -> Optional[Path]:
    """Папка плейлиста по ключу с защитой от path-traversal (ключ приходит из
    сети). None — если вне OUTPUT_DIR или не папка."""
    if not key:
        return None
    root = Path(root).resolve()
    target = (root / key).resolve()
    if target != root and root not in target.parents:
        return None
    return target if target.is_dir() else None


def _remove_done_id(folder: Path, vid: Optional[str]) -> None:
    """Убрать video-id из `.downloaded.txt` — иначе повторная закачка сочтёт трек
    дублем и пропустит его."""
    if not vid:
        return
    p = _archive_path(folder)
    try:
        ids = [x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return
    kept = [x for x in ids if x != vid]
    if len(kept) != len(ids):
        try:
            p.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except OSError:
            pass


def delete_track(root, key: str, ident: str) -> Optional[dict]:
    """Удалить один трек: файл + id из архива + из манифеста. `ident` — имя файла
    или video-id. Возвращает {ok, deleted: <абсолютный путь>} (путь нужен серверу
    для termux-media-scan, чтобы MediaStore не держал «призрак»), либо None если
    папка/трек не найдены. Файлы соседей НЕ переименовываем — номер в UI и так
    динамический (detail(): `n`)."""
    folder = resolve_folder(root, key)
    if folder is None:
        return None
    man = reconcile(folder)
    hit = next((t for t in man["tracks"] if t.get("file") == ident or t.get("id") == ident), None)
    if hit is None:
        return None
    deleted = None
    if hit.get("file"):
        fpath = folder / hit["file"]
        try:
            if fpath.exists():
                fpath.unlink()
            deleted = str(fpath)   # ПОСЛЕ unlink: сервер скажет MediaStore «файла нет»
        except OSError:
            return {"ok": False, "deleted": None}
    _remove_done_id(folder, hit.get("id"))
    man["tracks"] = [t for t in man["tracks"] if t is not hit]
    # осознанное удаление уменьшает и «сколько хотели» → полный плейлист остаётся
    # complete после курирования, а не превращается в partially_downloaded.
    exp = man.get("expected")
    if isinstance(exp, int) and exp > 0:
        man["expected"] = exp - 1
    man["status"] = derive_pl_status(man["tracks"], man.get("expected"))
    save_manifest(folder, man)
    return {"ok": True, "deleted": deleted}


def detail(root, key: str) -> Optional[dict]:
    """Полная карточка плейлиста: треки с ДИНАМИЧЕСКИМ номером `n` (позиция в
    списке — это и есть «трек 1, 2, 3…», независимо от имён файлов)."""
    folder = resolve_folder(root, key)
    if folder is None:
        return None
    man = reconcile(folder)
    tracks = [{"n": i, **t} for i, t in enumerate(man["tracks"], 1)]
    return {
        "key": key,
        "title": man["title"],
        "source": man["source"],
        "cover": man["cover"],
        "created": man["created"],
        "expected": man["expected"],
        "status": man["status"],
        "count": sum(1 for t in man["tracks"] if t["status"] == "done"),
        "tracks": tracks,
    }
