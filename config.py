"""
Конфигурация проекта. Один источник правды для путей и настроек.

Пути адаптируются под платформу:
  - Termux (S23 Ultra) → музыка в ~/storage/music (виден в галерее/плеерах телефона)
  - Windows/прочее     → ./downloads (для разработки и проверки логики)
"""
from __future__ import annotations

import os
import sys
import time
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
        _music = Path("/storage/emulated/0/Music")
    OUTPUT_DIR = _music
else:
    OUTPUT_DIR = ROOT / "downloads"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Auth / cookies ──
# Профиль браузера (persistent) — сюда сохраняется сессия после ручного входа.
BROWSER_PROFILE_DIR = ROOT / "auth" / "profile"
# Экспортированные cookies в формате Netscape — их ест yt-dlp.
COOKIES_FILE = ROOT / "cookies.txt"
# Метка «cookies принесены извне» (экспорт из браузера телефона), с датой импорта.
# Пока она стоит, cookies.txt НЕ трогает ни авто-обновление, ни браузер-слой:
# состав микса определяется идентичностью сессии, и перезапись профилем из
# Debian молча подменила бы станцию на чужую.
COOKIES_EXTERNAL_MARK = ROOT / ".cookies-external"

# Флаги Chromium для proot/Termux-X11.
# Чёрный экран в Termux:X11 = падает GL-инициализация. Лечение (проверено на S23):
# софт-рендер через SwiftShader. ВАЖНО: НЕ сочетать с --disable-gpu — он убивает
# GPU-процесс, в котором и работает SwiftShader, и экран снова чернеет.
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--use-gl=swiftshader",          # софт-рендер GL (лечит чёрный экран)
    "--enable-unsafe-swiftshader",   # новые Chromium без этого выключают SwiftShader
    "--disable-blink-features=AutomationControlled",  # скрыть navigator.webdriver → Google не блокирует вход
    "--disable-quic",                # proot режет UDP → форсим TCP-TLS (лечит SSL reset)
    "--no-first-run",
    "--no-default-browser-check",
    "--test-type",                   # без назойливых инфобаров
]

# Путь к СИСТЕМНОМУ Chromium (ARM-сборка из apt внутри Debian).
# Нужен, чтобы Playwright НЕ качал свой x86-бинарь, который не запустится на телефоне.
# Ставится setup-debian.sh; пусто на десктопе — Playwright возьмёт свой браузер.
CHROMIUM_EXECUTABLE = (
    os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    or os.environ.get("CHROMIUM_PATH")
    or ""
)

# ── Мост Termux ⇄ Debian (см. auth/bridge.py) ──
# Качалка живёт в НАТИВНОМ Termux, браузер — в proot-distro/Debian. Раньше между
# этими мирами ходил ты руками (login/cd/exit). Теперь ходит код.
PROOT_DISTRO = os.environ.get("TY_PROOT_DISTRO", "debian")
# Куда монтируется папка проекта внутри Debian. Тот же контент — другой путь,
# поэтому cookies.txt из браузера сразу виден качалке в Termux.
PROOT_MOUNT = f"/root/{ROOT.name}"
# Разрешить нативному Termux самому дёргать headless-refresh через proot.
# TY_AUTO_PROOT=0 — вернуть старое поведение (только предупреждение).
AUTO_REFRESH_VIA_PROOT = (
    os.environ.get("TY_AUTO_PROOT", "1").lower() not in ("0", "false", "no")
)
# Сколько ждать headless-обновление cookies через proot (сек). proot стартует
# медленно (~10-30с на телефоне), плюс сам заход на YouTube.
PROOT_REFRESH_TIMEOUT = 240
# Сколько ждать снимок очереди микса браузером (сек): старт proot + загрузка
# страницы YouTube + дорисовка очереди.
PROOT_MIX_TIMEOUT = 210
# Брать состав микса из БРАУЗЕРА, а не из yt-dlp.
# Проверено на устройстве: RD-микс привязан к сессии браузера, а не к аккаунту —
# при валидных cookies и любом клиенте плеера yt-dlp получает свою станцию
# (совпало 2 трека из 25). Поэтому состав спрашиваем у того, кто его показывает.
# TY_MIX_BROWSER=0 — вернуть прежнее поведение (быстрее, но список будет другим).
MIX_FROM_BROWSER = (
    os.environ.get("TY_MIX_BROWSER", "1").lower() not in ("0", "false", "no")
)
# Сколько ждать, пока ты введёшь пароль/2FA в видимом окне (сек).
LOGIN_WAIT_TIMEOUT = 900

# ── Внешний вид ──
# Nerd Font иконки в TUI. Требуют установленного Nerd Font в терминале.
# Выключить (безопасный Unicode-fallback):  TY_NERD_FONT=0
NERD_FONT = os.environ.get("TY_NERD_FONT", "1").lower() not in ("0", "false", "no")

# ── Параметры загрузки (Решение 2 + Решение 6) ──
# Приоритет AAC (m4a); если дорожка не в AAC — перекодируем в mp3.
AUDIO_PRIMARY = "m4a"      # AAC, без перекодирования когда возможно
AUDIO_FALLBACK = "mp3"     # универсальный fallback
AUDIO_QUALITY = "0"        # 0 = максимум

# Селектор потока yt-dlp (какой формат качать с YouTube). Дефолт = прежнее
# зашитое поведение → TUI/CLI НЕ меняются. Web-слой переопределяет по качеству.
AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio/best"

# Параллельные загрузки (как в 4KVD). 4 — оптимум скорость/риск.
# 1 — последовательно (тогда работают паузы SLEEP_* ниже).
CONCURRENT_DOWNLOADS = 4

# Троттл обновлений прогресса в TUI (сек на трек). Это частота ДАННЫХ, не кадров.
# Меньше (0.05) = плавнее, но больше нагрузка; больше (0.25) = легче, но «скачками».
PROGRESS_THROTTLE_SEC = 0.1

# Анти-бан: пауза между треками. Работает ТОЛЬКО при CONCURRENT_DOWNLOADS=1.
# При параллели темп задаёт сам лимит потоков. 0/0 — отключить.
SLEEP_MIN = 2              # сек, минимальная пауза между треками
SLEEP_MAX = 5              # сек, максимальная

# Авто-refresh: если cookies старше этого — обновить (в Debian) / предупредить (в Termux).
COOKIES_MAX_AGE_HOURS = 12

# ── Дедупликация ──
# Не качать один и тот же трек дважды (по video id): и внутри одного запуска,
# и при повторном (динамический My Mix повторяет песни). Архив скачанных id —
# файл .downloaded.txt в папке плейлиста (удалишь папку — сбросится).
SKIP_DUPLICATES = True

# ── Индексация медиатеки Android ──
# После скачивания Samsung Music не видит файлы до перезагрузки. Дёргаем
# termux-media-scan (нужен пакет termux-api + APK Termux:API). Только на Termux.
MEDIA_SCAN = True

# ── Обложки (thumbnails) ──
# Сохранять значок каждого видео и обложку плейлиста (folder.jpg).
SAVE_THUMBNAILS = False
# Целевая высота обложки в пикселях. Если исходник меньше — НЕ увеличиваем (берём как есть).
THUMBNAIL_MAX_HEIGHT = 720

# ── Лимит плейлиста ──
# Сколько записей плейлиста тянуть. None = все (YouTube отдаёт до ~5000).
MAX_PLAYLIST_ITEMS: int | None = None

# ── Клиенты плеера YouTube ──
# Пусто [] = выбирает сам yt-dlp. Это и есть правильный дефолт: он перебирает
# клиенты и сливает форматы, а список, прибитый гвоздями в конфиге, устаревает
# молча — и в один день начинает ломать то, что чинил.
#
# История (проверено на устройстве, yt-dlp 2026.7.4): пин ["tv","ios","web_safari"]
# ставился, чтобы обойти гейт PO-token, а сейчас сам оставляет от плейлиста одни
# сториборды — YouTube накрыл tv-клиент DRM-экспериментом (yt-dlp#12563), а ios
# требует GVS PO-token. На той же ссылке с дефолтными клиентами форматы отдаются
# полностью (m4a 130k, opus 130k). Не пинуй клиенты без свежих доказательств.
YOUTUBE_PLAYER_CLIENTS: list[str] = []

# ── Снимок динамического микса (My Mix / radio: list=RD...) ──
# Жёсткий лимит: берём ровно первые N треков (как 4KVD), не уходя в радио.
MIX_SNAPSHOT_LIMIT = 25

# ── EJS: решатель JS-challenge YouTube ──
# YouTube шифрует ссылки на потоки через JS (n-challenge / signature). Нужен:
#   1) JS-рантайм (deno или nodejs) — ставится в системе;
#   2) скрипт-решатель EJS, который yt-dlp качает с GitHub (кешируется 1 раз).
# Без этого yt-dlp видит "Only images are available". Пусто [] — отключить.
REMOTE_COMPONENTS = ["ejs:github"]

# ── Web-UI (localhost, 100% on-device) ──
# Лёгкий сервер на stdlib (без зависимостей) → отдаёт страницу, браузер телефона
# рисует. Бинд СТРОГО на 127.0.0.1 — никто из Wi-Fi не достучится.
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765
WEB_MAX_PLAYLISTS = 5          # очередь: до 5 My Mix одновременно в списке

# Параллелизм по умолчанию: 3 плейлиста × 2 трека = 6 потоков (🟡 управляемый).
# Слайдер в UI («всего потоков» 2–8) пересчитывает это: pl = round(streams/tracks).
WEB_PLAYLIST_CONCURRENCY = 3   # сколько My Mix качать одновременно (макс)
WEB_TRACKS_PER_PLAYLIST = 2    # базовый делитель бюджета: треков на плейлист при дележе
WEB_MAX_TRACKS_PER_PLAYLIST = 4  # потолок параллели ОДНОГО плейлиста (один микс = до 4, как 4KVD)

# Человеческий темп (анти-бан по оси «паттерн», не по «пику»):
START_JITTER_MAX = 1.5         # сек: случайный разброс старта треков (0 = выкл, ramp-up)
PLAYLIST_PAUSE_MIN = 2         # сек: пауза после полностью скачанного My Mix…
PLAYLIST_PAUSE_MAX = 12        # …до переиспользования слота под следующий

# Гибрид-блок ①: платформа → предпочитаемый кодек. Android/iOS/Linux = m4a
# (копия AAC, без даунгрейда). Windows = mp3 для макс. совместимости старых плееров.
WEB_PLATFORM_CODEC = {"android": "m4a", "ios": "m4a", "linux": "m4a", "windows": "mp3"}

# Качество ② → какой реальный поток брать с YouTube. Три уровня (цвета в UI:
# max=синий, standard=зелёный, economy=серый). Кодек/контейнер задаёт платформа ①.
WEB_QUALITY = {
    "max":      {"format": "bestaudio/best",
                 "sub": "Opus ~160 kbps — максимум, что отдаёт YouTube"},
    "standard": {"format": "bestaudio[ext=m4a]/bestaudio",
                 "sub": "AAC 128 kbps — универсальный, играет везде"},
    "economy":  {"format": "worstaudio[abr>=32]/worstaudio/bestaudio",
                 "sub": "~50–64 kbps — мелкие файлы, экономия места"},
}

# Шаблон имени файла: Папка плейлиста / NN - Название
OUTPUT_TEMPLATE = "%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"
# Для одиночного трека (без плейлиста)
OUTPUT_TEMPLATE_SINGLE = "%(title)s.%(ext)s"


def have_cookies() -> bool:
    return COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0


def cookies_are_external() -> bool:
    """cookies принесены из другого браузера — трогать их автоматике нельзя."""
    return COOKIES_EXTERNAL_MARK.exists() and have_cookies()


def mark_cookies_external(source: str) -> None:
    try:
        COOKIES_EXTERNAL_MARK.write_text(
            f"{source}\n{time.strftime('%Y-%m-%d %H:%M')}\n", encoding="utf-8")
    except OSError:
        pass


def unmark_cookies_external() -> None:
    """Вход через браузер-слой снова делает хозяином профиль в Debian."""
    try:
        COOKIES_EXTERNAL_MARK.unlink()
    except OSError:
        pass


# ── Версия набора зависимостей ──
# Поднимается КАЖДЫЙ раз, когда setup-termux.sh начинает ставить что-то новое
# (пакет, пакет в Debian, модуль pip). Установщик записывает это число в
# .setup-stamp.
#
# Зачем: код приезжает через `git pull`, а зависимости — нет. Человек с прошлой
# установки получает новый код поверх старого окружения и ловит невнятную ошибку
# где-то в середине работы. Теперь расхождение видно сразу и чинится повторным
# запуском установщика.
#
# История: v1 — исходный набор; v2 — termux-am и termux-x11-nightly (нужны
# автозапуску Termux:X11 при входе; раньше ставились на лету посреди входа).
SETUP_VERSION = 2
SETUP_STAMP = ROOT / ".setup-stamp"


def setup_stamp_version() -> int:
    """Какая версия зависимостей реально установлена. 0 — отметки нет."""
    try:
        return int(SETUP_STAMP.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def setup_is_current() -> tuple[bool, str]:
    """(всё ли на месте, что сказать человеку). Никогда не падает."""
    if not IS_TERMUX:
        return True, ""      # речь про пакеты телефона — на десктопе проверять нечего
    have = setup_stamp_version()
    if have >= SETUP_VERSION:
        return True, ""
    if have == 0:
        return False, ("не вижу отметки установщика — окружение могло остаться "
                       "от прошлой версии: bash scripts/setup-termux.sh")
    return False, (f"код новее окружения (зависимости v{have}, нужна v{SETUP_VERSION}) "
                   f"— обнови: bash scripts/setup-termux.sh")
