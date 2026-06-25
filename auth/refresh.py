"""
ШАГ 2 (повторяется автоматически — HEADLESS, без окна).

Поднимает Chromium с уже залогиненным профилем (из login.py), заходит на YouTube,
браузер сам обновляет токены/cookies сессии, после чего экспортируем свежий
cookies.txt для yt-dlp. Это закрывает проблему «протухающих cookies и динамичных
плейлистов».

  python -m auth.refresh        — обновить сейчас (выход 0 ок / 1 нужен повторный login)

Также отсюда берётся ensure_fresh_cookies() — её зовёт TUI/CLI ПЕРЕД скачиванием:
  • в Debian (есть браузер) → реально обновляет headless, если cookies устарели;
  • в нативном Termux (браузера нет) → просто проверяет свежесть и предупреждает.
"""
from __future__ import annotations

import sys
import time
from typing import Tuple

import config
from auth.cookies_export import has_auth_cookies, write_cookies_file

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


# ──────────────────── собственно refresh ────────────────────
def _refresh_once() -> Tuple[str, str]:
    """Один headless-проход обновления. Возвращает (code, message)."""
    if not config.BROWSER_PROFILE_DIR.exists():
        return "no_profile", "профиль не найден — нужен вход: python -m auth.login"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "no_playwright", "playwright не установлен (нужен Debian-слой)"

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=True,
        args=list(config.CHROMIUM_ARGS),
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
        return "expired", "сессия истекла — нужен повторный вход: python -m auth.login"

    n = write_cookies_file(cookies, config.COOKIES_FILE)
    return "ok", f"cookies.txt обновлён ({n} cookies)"


# ──────────────────── публичный best-effort хук ────────────────────
def ensure_fresh_cookies(max_age_hours: float | None = None) -> Tuple[str, str]:
    """
    Вызывается ПЕРЕД скачиванием. Никогда не падает — только сообщает статус.
    Коды: refreshed | fresh | stale | no_cookies | refresh_failed | skipped
    """
    max_age = config.COOKIES_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    age = cookies_age_hours()

    if _has_browser_layer():
        if age is not None and age < max_age:
            return "fresh", f"cookies свежие ({age:.1f}ч) — обновление не нужно"
        code, msg = _refresh_once()
        if code == "ok":
            return "refreshed", msg
        return "refresh_failed", msg

    # браузер-слоя здесь нет (нативный Termux) — только диагностика
    if age is None:
        return "no_cookies", "cookies.txt нет — приватные плейлисты недоступны"
    if age > max_age:
        return "stale", (f"cookies старые ({age:.0f}ч) — обнови в Debian: "
                         f"python -m auth.refresh")
    return "fresh", f"cookies свежие ({age:.1f}ч)"


def main() -> int:
    code, msg = _refresh_once()
    if code == "ok":
        print(f"✓  {msg}")
        return 0
    print(f"⚠  {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
