"""
Конфигурация проекта. Один источник правды для путей и настроек.

Пути адаптируются под платформу:
  - Termux (S23 Ultra) → музыка в ~/storage/music (виден в галерее/плеерах телефона)
  - Windows/прочее     → ./downloads (для разработки и проверки логики)
"""
from __future__ import annotations

import json
import os
import secrets
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
# Экспортированные cookies в формате Netscape — их ест yt-dlp.
#
# Источник ровно один: браузер телефона (расширение для Kiwi либо файл-экспорт).
# Своего браузера внутри проекта нет и не будет — он давал только вес. Замер на
# устройстве: состав RD-микса определяется идентичностью сессии в cookies, и с
# cookies того браузера, где ты смотришь миксы, yt-dlp повторяет его список
# 25 из 25 — против 2 из 25 с сессией, поднятой отдельным Chromium.
COOKIES_FILE = ROOT / "cookies.txt"
# Откуда и когда приехали cookies + когда сессию последний раз проверяли живьём.
# Возраст файла — плохой признак: cookies могут быть свежими и уже мёртвыми
# (аккаунт разлогинили) или недельными и рабочими. Поэтому храним результат
# настоящей проверки, а не только время записи.
COOKIES_STATE_FILE = ROOT / ".cookies-state"

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

# Как часто перепроверять сессию у YouTube (часы). Проверка — один GET, поэтому
# интервал маленький ничего не стоит; смысл в том, чтобы не дёргать сеть на
# каждый трек.
COOKIES_MAX_AGE_HOURS = 12
# Таймаут этой проверки (сек). Нет сети — молча работаем с тем, что есть.
COOKIES_CHECK_TIMEOUT = 15

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
# RD-радио бесконечно: yt-dlp отдаёт ровно сколько попросишь (проверено на
# устройстве: 25→25, 50→50, 100→100, 200→200, все уникальные). Поэтому "сколько
# треков" — выбор пользователя (глубина снимка), а не свойство микса.
MIX_SNAPSHOT_LIMIT = 25             # дефолт, если UI не прислал лимит
MIX_HARD_CEILING = 100             # предохранитель от бесконечного радио (≈760 МБ)

# ── EJS: решатель JS-challenge YouTube ──
# YouTube шифрует ссылки на потоки через JS (n-challenge / signature). Нужен:
#   1) JS-рантайм — ставится в системе (см. JS_RUNTIMES ниже);
#   2) скрипт-решатель EJS, который yt-dlp качает с GitHub (кешируется 1 раз).
# Без этого yt-dlp видит "Only images are available". Пусто [] — отключить.
REMOTE_COMPONENTS = ["ejs:github"]

# Какие JS-рантаймы РАЗРЕШИТЬ yt-dlp. Не «какой выбрать»: приоритет задаёт сам
# yt-dlp (deno > node > quickjs > bun) и берёт первый доступный.
#
# Перечислять надо все, потому что по умолчанию yt-dlp включает ТОЛЬКО deno.
# Из-за этого установщик врал: строка `pkg install deno || pkg install nodejs`
# выглядела как запасной путь, а на деле поставленный nodejs не использовался
# вовсе — yt-dlp его не искал. Это важно на armv7: deno собран только под
# aarch64/x86_64, и там fallback — единственный рабочий вариант.
#
# Опция появилась в yt-dlp 2025.x; на более старых она просто игнорируется.
JS_RUNTIMES = ["deno", "node", "quickjs", "bun"]

# ── Токен для приёма cookies от расширения ──
# Один локальный секрет на установку. Нужен потому, что проверки «origin =
# chrome-extension://» мало: она отсекает веб-страницы, но не ЧУЖОЕ расширение,
# стоящее в том же браузере, — а на этом эндпоинте отдают доступ к аккаунту.
# Токен зашивается внутрь .zip при сборке (python main.py kiwi), поэтому чужому
# расширению его негде взять. Файл не коммитится; удалил — просто пересобери zip.
API_TOKEN_FILE = ROOT / ".api-token"


def api_token() -> str:
    """Токен установки. Создаётся при первом обращении, дальше читается."""
    try:
        tok = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    try:
        API_TOKEN_FILE.write_text(tok, encoding="utf-8")
        API_TOKEN_FILE.chmod(0o600)      # сосед по устройству его не прочитает
    except OSError:
        return ""                        # некуда записать — эндпоинт закрыт совсем
    return tok


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


# ── состояние cookies: откуда приехали и когда сессию видели живой ──
# Формат — одна строка JSON. Файл целиком служебный: пропал или побился —
# считаем, что проверок не было, и просто проверим заново.
def read_cookies_state() -> dict:
    try:
        data = json.loads(COOKIES_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cookies_state(**fields) -> None:
    state = read_cookies_state() | fields
    try:
        COOKIES_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def mark_cookies_source(source: str) -> None:
    """Запомнить, откуда приехали cookies. Проверку сбрасываем: сессия другая."""
    _write_cookies_state(source=source,
                         imported=time.strftime("%Y-%m-%d %H:%M"),
                         checked_at=0, alive=None)


def mark_cookies_checked(alive: bool) -> None:
    """Запомнить результат живой проверки сессии (см. auth/refresh.py)."""
    _write_cookies_state(checked_at=int(time.time()), alive=bool(alive))


def cookies_source() -> str:
    return str(read_cookies_state().get("source") or "")


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
# автозапуску Termux:X11 при входе); v3 — браузер-слой убран целиком, набор
# сжался до нативного Termux (python, ffmpeg, git, termux-api, JS-рантайм).
SETUP_VERSION = 3
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
