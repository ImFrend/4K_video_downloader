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
    _music = Path.home() / "storage" / "music" / "TermuxYoutube"
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

# Анти-бан: человеческий темп (Решение 6 — sleep оставляем, archive убрали).
SLEEP_MIN = 5              # сек, минимальная пауза между треками
SLEEP_MAX = 15             # сек, максимальная

# Авто-refresh: если cookies старше этого — обновить (в Debian) / предупредить (в Termux).
COOKIES_MAX_AGE_HOURS = 12

# Шаблон имени файла: Папка плейлиста / NN - Название
OUTPUT_TEMPLATE = "%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"
# Для одиночного трека (без плейлиста)
OUTPUT_TEMPLATE_SINGLE = "%(title)s.%(ext)s"


def have_cookies() -> bool:
    return COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0
