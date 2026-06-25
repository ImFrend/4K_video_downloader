"""
Конфигурация проекта. Один источник правды для путей и настроек.

Пути адаптируются под платформу:
  - Termux (S23 Ultra) → музыка в ~/storage/music (виден в галерее/плеерах телефона)
  - Windows/прочее     → ./downloads (для разработки и проверки логики)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Корень проекта ──
ROOT = Path(__file__).resolve().parent


def _is_termux() -> bool:
    """Определяем, что мы реально на телефоне в Termux."""
    return "com.termux" in os.environ.get("PREFIX", "") or "ANDROID_ROOT" in os.environ


IS_TERMUX = _is_termux()

# ── Куда сохранять музыку ──
if IS_TERMUX:
    # termux-setup-storage создаёт этот симлинк на общую память телефона
    _music = Path("/storage/emulated/0/Music")
    if not (Path.home() / "storage").exists():
        # storage ещё не настроен — падать не будем, кладём в домашнюю папку
        _music = Path.home() / "TermuxYoutube-Music"
    OUTPUT_DIR = _music
else:
    OUTPUT_DIR = ROOT / "downloads"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Auth / cookies ──
# Профиль браузера (persistent) — сюда сохраняется сессия после ручного входа.
BROWSER_PROFILE_DIR = ROOT / "auth" / "profile"
# Экспортированные cookies в формате Netscape — их ест yt-dlp.
COOKIES_FILE = ROOT / "cookies.txt"

# Флаги Chromium для proot/Termux-X11.
# Чёрный экран в Termux:X11 = аппаратный GPU недоступен. Форсим софт-рендер
# (swiftshader). Если всё ещё чёрный — попробуй раскомментировать --disable-gpu.
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",              # без GPU-процесса → нет краша GL-инициализации
    "--disable-quic",            # proot режет UDP → форсим TCP-TLS (лечит SSL reset)
    "--no-first-run",
    "--no-default-browser-check",
    "--test-type",               # без назойливых инфобаров
]

# Путь к СИСТЕМНОМУ Chromium (ARM-сборка из apt внутри Debian).
# Нужен, чтобы Playwright НЕ качал свой x86-бинарь, который не запустится на телефоне.
# Ставится setup-debian.sh; пусто на десктопе — Playwright возьмёт свой браузер.
CHROMIUM_EXECUTABLE = (
    os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    or os.environ.get("CHROMIUM_PATH")
    or ""
)

# ── Внешний вид ──
# Nerd Font иконки в TUI. Требуют установленного Nerd Font в терминале.
# Выключить (безопасный Unicode-fallback):  TY_NERD_FONT=0
NERD_FONT = os.environ.get("TY_NERD_FONT", "1").lower() not in ("0", "false", "no")

# ── Параметры загрузки (Решение 2 + Решение 6) ──
# Приоритет AAC (m4a); если дорожка не в AAC — перекодируем в mp3.
AUDIO_PRIMARY = "m4a"      # AAC, без перекодирования когда возможно
AUDIO_FALLBACK = "mp3"     # универсальный fallback
AUDIO_QUALITY = "0"        # 0 = максимум

# Параллельные загрузки (как в 4KVD). 4 — оптимум скорость/риск.
# 1 — последовательно (тогда работают паузы SLEEP_* ниже).
CONCURRENT_DOWNLOADS = 3

# Троттл обновлений прогресса в TUI (сек на трек). Это частота ДАННЫХ, не кадров.
# Меньше (0.05) = плавнее, но больше нагрузка; больше (0.25) = легче, но «скачками».
PROGRESS_THROTTLE_SEC = 0.12

# Анти-бан: пауза между треками. Работает ТОЛЬКО при CONCURRENT_DOWNLOADS=1.
# При параллели темп задаёт сам лимит потоков. 0/0 — отключить.
SLEEP_MIN = 2              # сек, минимальная пауза между треками
SLEEP_MAX = 5              # сек, максимальная

# Авто-refresh: если cookies старше этого — обновить (в Debian) / предупредить (в Termux).
COOKIES_MAX_AGE_HOURS = 12

# ── Обложки (thumbnails) ──
# Сохранять значок каждого видео и обложку плейлиста (folder.jpg).
SAVE_THUMBNAILS = True
# Целевая высота обложки в пикселях. Если исходник меньше — НЕ увеличиваем (берём как есть).
THUMBNAIL_MAX_HEIGHT = 720

# ── Лимит плейлиста ──
# Сколько записей плейлиста тянуть. None = все (YouTube отдаёт до ~5000).
MAX_PLAYLIST_ITEMS: int | None = None

# ── Обход гейта форматов YouTube (PO-token) ──
# С web-клиентом YouTube требует PO-token → "Requested format is not available".
# Пробуем клиенты плеера, которым он не нужен (по порядку). Требует свежий yt-dlp.
# Пусто [] — вернуть поведение по умолчанию.
YOUTUBE_PLAYER_CLIENTS = ["tv", "ios", "web_safari"]

# ── Снимок динамического микса (My Mix / radio: list=RD...) ──
# Жёсткий лимит: берём ровно первые N треков (как 4KVD), не уходя в радио.
MIX_SNAPSHOT_LIMIT = 25

# ── EJS: решатель JS-challenge YouTube ──
# YouTube шифрует ссылки на потоки через JS (n-challenge / signature). Нужен:
#   1) JS-рантайм (deno или nodejs) — ставится в системе;
#   2) скрипт-решатель EJS, который yt-dlp качает с GitHub (кешируется 1 раз).
# Без этого yt-dlp видит "Only images are available". Пусто [] — отключить.
REMOTE_COMPONENTS = ["ejs:github"]

# Шаблон имени файла: Папка плейлиста / NN - Название
OUTPUT_TEMPLATE = "%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"
# Для одиночного трека (без плейлиста)
OUTPUT_TEMPLATE_SINGLE = "%(title)s.%(ext)s"


def have_cookies() -> bool:
    return COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0
