"""
ШАГ 2 (повторяется автоматически — HEADLESS, без окна).

Поднимает Chromium с уже залогиненным профилем (из login.py), заходит на YouTube,
браузер сам обновляет токены/cookies сессии, после чего экспортируем свежий
cookies.txt для yt-dlp. Это закрывает проблему «протухающих cookies и динамичных
плейлистов».

  python -m auth.refresh        — обновить сейчас (выход 0 ок / 1 нужен повторный login)

Также отсюда берётся ensure_fresh_cookies() — её зовёт TUI/Web/CLI ПЕРЕД скачиванием:
  • в Debian (браузер под рукой) → обновляет headless напрямую;
  • в нативном Termux (браузера нет) → САМ идёт в браузер-слой через proot
    (auth/bridge.py). Раньше тут была тупиковая ветка «обнови в Debian вручную»:
    обещанного «cookies обновляются сами, без кнопки» на телефоне не было.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Tuple

import config
from auth import bridge
from auth.cookies_export import (has_auth_cookies, netscape_to_cookies,
                                 write_cookies_file)

# один поток обновления на процесс: web-UI может дёрнуть ensure_fresh_cookies()
# из нескольких мест, а поднимать два Chromium в proot одновременно незачем
_LOCK = threading.RLock()

YOUTUBE = "https://www.youtube.com/account"


# ──────────────────── вспомогательное ────────────────────
def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def cookies_age_hours() -> float | None:
    """Возраст cookies.txt в часах, или None если файла нет."""
    if not config.COOKIES_FILE.exists():
        return None
    return (time.time() - config.COOKIES_FILE.stat().st_mtime) / 3600.0


def _has_browser_layer() -> bool:
    """Здесь ли реально доступен браузер-слой (т.е. мы в Debian с профилем)."""
    return _playwright_available() and config.BROWSER_PROFILE_DIR.exists()


def _fresh_msg(age: float) -> Tuple[str, str]:
    return "fresh", f"cookies свежие ({age:.1f}ч)"


# ──────────────────── собственно refresh ────────────────────
def _refresh_once() -> Tuple[str, str]:
    """Один headless-проход обновления. Возвращает (code, message)."""
    if not config.BROWSER_PROFILE_DIR.exists():
        return "no_profile", "вход ещё не выполнен — bash scripts/login.sh"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "no_playwright", "playwright не установлен (нужен Debian-слой)"

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=True,
        args=list(config.CHROMIUM_ARGS),
        ignore_default_args=["--enable-automation"],  # не палить автоматизацию
    )
    if config.CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(YOUTUBE, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)  # дать браузеру обновить токены
            except Exception as ex:  # noqa: BLE001
                ctx.close()
                return "error", f"проблема при заходе на YouTube: {ex}"
            cookies = ctx.cookies()
            ctx.close()
    except Exception as ex:  # noqa: BLE001
        return "error", f"не удалось запустить Chromium: {ex}"

    if not has_auth_cookies(cookies):
        return "expired", "сессия истекла — нужен вход: bash scripts/login.sh"

    n = write_cookies_file(cookies, config.COOKIES_FILE)
    return "ok", f"cookies.txt обновлён ({n} cookies)"


def _refresh_external_once() -> Tuple[str, str]:
    """
    Продлить ПРИНЕСЁННЫЕ извне cookies, не меняя личность сессии.

    Профиля того браузера у нас нет и быть не может (чужой app-каталог Android
    недоступен без root). Но личность сессии живёт в самих cookies — это и
    показал замер «25 из 25». Поэтому грузим их в ЧИСТЫЙ контекст (не в профиль
    Debian, иначе подмешается его личность и станция уедет), заходим на YouTube,
    даём Google прокрутить токены и пишем обратно.
    """
    seed = netscape_to_cookies(config.COOKIES_FILE)
    if not seed:
        return "error", "не смог разобрать cookies.txt"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "no_playwright", "нет браузер-слоя — продлить не могу"

    launch_kwargs = dict(headless=True, args=list(config.CHROMIUM_ARGS),
                         ignore_default_args=["--enable-automation"])
    if config.CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            ctx = browser.new_context()      # без user_data_dir — чистая личность
            try:
                ctx.add_cookies(seed)
                page = ctx.new_page()
                page.goto(YOUTUBE, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)  # дать браузеру обновить токены
                cookies = ctx.cookies()
            finally:
                ctx.close()
                browser.close()
    except Exception as ex:  # noqa: BLE001
        return "error", f"не удалось продлить: {ex}"

    if not has_auth_cookies(cookies):
        return "expired", ("сессия браузера истекла — выгрузи cookies заново: "
                           "python main.py cookies")
    n = write_cookies_file(cookies, config.COOKIES_FILE)
    return "ok", f"cookies браузера продлены ({n} cookies)"


def _external_refresh() -> Tuple[str, str]:
    """Продление внешних cookies отсюда или через proot. Профиль не нужен."""
    if _playwright_available():
        return _refresh_external_once()
    if config.AUTO_REFRESH_VIA_PROOT and bridge.have_proot():
        return bridge.refresh_external_via_proot()
    return "no_playwright", "браузер-слой не установлен — продлить не могу"


# ──────────────────── публичный best-effort хук ────────────────────
def ensure_fresh_cookies(max_age_hours: float | None = None) -> Tuple[str, str]:
    """
    Вызывается ПЕРЕД скачиванием. Никогда не падает — только сообщает статус.
    Коды: fresh | refreshed | need_login | refresh_failed | no_cookies | stale
    """
    max_age = config.COOKIES_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    age = cookies_age_hours()

    # cookies принесены извне: профилем из Debian их обновлять НЕЛЬЗЯ — это молча
    # подменит станцию микса на чужую. Продлеваем их собственной сессией.
    if config.cookies_are_external():
        if age is None:
            return "no_cookies", "cookies.txt пропал — повтори: python main.py cookies"
        if age < max_age:
            return "fresh", f"cookies из браузера ({age:.1f}ч)"
        with _LOCK:
            age = cookies_age_hours()          # мог продлить параллельный поток
            if age is not None and age < max_age:
                return "fresh", f"cookies из браузера ({age:.1f}ч)"
            code, msg = _external_refresh()
        if code == "ok":
            return "refreshed", msg
        if code == "expired":
            return "need_login", msg
        return "refresh_failed", msg

    # свежие — браузер не трогаем вообще (ни здесь, ни через proot)
    if age is not None and age < max_age:
        return _fresh_msg(age)

    # (а) мы внутри браузер-слоя — обновляем напрямую
    if _has_browser_layer():
        code, msg = _refresh_once()
        if code == "ok":
            return "refreshed", msg
        if code in ("expired", "no_profile"):
            return "need_login", msg
        return "refresh_failed", msg

    # (б) нативный Termux — сами сходим в браузер-слой через proot.
    #     Это и делает обновление cookies по-настоящему автоматическим.
    if config.AUTO_REFRESH_VIA_PROOT and bridge.have_proot():
        if not bridge.have_login_profile():
            return "need_login", "вход не выполнен — bash scripts/login.sh"
        with _LOCK:
            age = cookies_age_hours()      # мог успеть обновить параллельный поток
            if age is not None and age < max_age:
                return _fresh_msg(age)
            code, msg = bridge.refresh_via_proot()
        if code == "ok":
            return "refreshed", msg
        if code == "expired":
            return "need_login", msg
        return "refresh_failed", msg

    # (в) хода в браузер-слой нет — остаётся диагностика
    if age is None:
        return "no_cookies", "cookies.txt нет — приватные плейлисты недоступны"
    return "stale", f"cookies старые ({age:.0f}ч) — обнови: bash scripts/login.sh"


def main() -> int:
    """python -m auth.refresh [--external] — и в Debian, и в нативном Termux."""
    external = "--external" in sys.argv[1:]
    if external:
        code, msg = _refresh_external_once() if _playwright_available() \
            else bridge.refresh_external_via_proot()
    elif _playwright_available():
        code, msg = _refresh_once()
    else:
        code, msg = bridge.refresh_via_proot()
    if code == "ok":
        print(f"✓  {msg}")
        return 0
    print(f"⚠  {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
