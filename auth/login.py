"""
Вход в Google — с автоопределением и автозакрытием.

Окно открывается ТОЛЬКО если без него никак:

  фаза 1 «тихая»   — если сохранённый профиль ещё жив, cookies.txt обновляется
                     headless. Ни X11, ни единого тапа. Это обычный случай:
                     «я же уже авторизован» — значит окна и не будет.
  фаза 2 «видимая» — сессии нет: открываем Chromium на Termux:X11, ты вводишь
                     пароль/2FA. Скрипт САМ ловит момент входа, сохраняет cookies
                     и закрывает окно. Возвращаться в терминал и жать Enter не надо
                     (раньше это стоило двух переключений между приложениями).

Запуск:
  python -m auth.login             обе фазы (для фазы 2 нужен DISPLAY)
  python -m auth.login --probe     только фаза 1; код 10 = нужно видимое окно
  python -m auth.login --force     сразу фаза 2 (сменить аккаунт / чинить сессию)

На телефоне это дёргает не человек, а scripts/login.sh — он же поднимает X11.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

import config
from auth.cookies_export import has_auth_cookies, write_cookies_file

# Сразу на форму входа с возвратом на YouTube: если сессия жива — редирект
# проскакивает мимо формы, и автодетект закрывает окно почти мгновенно.
LOGIN_URL = ("https://accounts.google.com/ServiceLogin"
             "?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F")
YOUTUBE = "https://www.youtube.com/account"

NEED_WINDOW = 10          # код возврата --probe: тихо не вышло, нужен видимый вход

_OK_PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:0;height:100vh;display:flex;flex-direction:column;
 align-items:center;justify-content:center;background:#000;color:#fff;
 font:600 22px -apple-system,Roboto,sans-serif;gap:14px">
 <div style="font-size:64px;color:#30d158">&#10003;</div>
 <div>Вход сохранён</div>
 <div style="font-size:15px;color:#8e8e93;font-weight:400">окно закроется само</div>
</body>"""


# ──────────────────────────── фаза 1: тихо ────────────────────────────
def quiet_session_ok() -> tuple[bool, str]:
    """Пробуем обойтись сохранённой сессией: headless-заход + экспорт cookies."""
    from auth.refresh import _refresh_once
    code, msg = _refresh_once()
    return code == "ok", msg


# ──────────────────────────── фаза 2: видимое окно ────────────────────────────
def _collect(ctx) -> Optional[list]:
    """cookies контекста; None — окно/браузер закрыли."""
    try:
        return ctx.cookies()
    except Exception:  # noqa: BLE001
        return None


def _pause(page, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001
        time.sleep(ms / 1000.0)


def _goto(page, url: str) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded")
    except Exception as ex:  # noqa: BLE001
        print(f"   не удалось открыть {url}: {ex}", flush=True)


def _wait_for_login(ctx, page, timeout_s: float) -> Optional[list]:
    """
    Ждём, пока в контексте появятся cookies авторизованной сессии.
    Требуем два попадания подряд — чтобы не схватить полусостояние на середине
    2FA, когда часть cookies уже выставлена, а вход ещё не завершён.
    """
    deadline = time.monotonic() + timeout_s
    hits = 0
    last_note = time.monotonic()

    while time.monotonic() < deadline:
        cookies = _collect(ctx)
        if cookies is None:
            print("   окно закрыто — вход не завершён", flush=True)
            return None

        if has_auth_cookies(cookies):
            hits += 1
            if hits >= 2:
                return cookies
        else:
            hits = 0

        _pause(page, 1000)
        if time.monotonic() - last_note >= 20:
            last_note = time.monotonic()
            left = (deadline - time.monotonic()) / 60.0
            print(f"   жду вход на экране Termux:X11… (ещё {left:.0f} мин)", flush=True)

    print("   время ожидания вышло", flush=True)
    return None


def visible_login(timeout_s: Optional[float] = None) -> int:
    """Видимое окно + автодетект входа + автосохранение + автозакрытие."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if config.IS_TERMUX:
            # браузер живёт в Debian — сюда попадать не должны, но подскажем как надо
            print("!! Браузера тут нет (он в Debian). Вход запускается одной командой:")
            print("   bash scripts/login.sh")
        else:
            print("!! Playwright не установлен:  pip install playwright")
        return 1

    if not os.environ.get("DISPLAY"):
        print("⚠  DISPLAY не задан — видимому окну нужен X11.")
        print("   На телефоне запускай вход одной командой: bash scripts/login.sh")

    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    timeout_s = config.LOGIN_WAIT_TIMEOUT if timeout_s is None else timeout_s

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=list(config.CHROMIUM_ARGS),   # софт-рендер для Termux-X11
        # убрать метку автоматизации → Google не ругается «browser not secure»
        ignore_default_args=["--enable-automation"],
        viewport={"width": 412, "height": 915},  # пропорции телефона
    )
    if config.CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE

    cookies: Optional[list] = None
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as ex:  # noqa: BLE001
            print(f"!! не удалось запустить Chromium: {ex}")
            return 1

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _goto(page, LOGIN_URL)
        print("→ Окно входа открыто. Введи почту/пароль (и 2FA) на экране Termux:X11.")
        print("  Возвращаться сюда НЕ надо — как увижу вход, сохраню и закрою окно.",
              flush=True)

        cookies = _wait_for_login(ctx, page, timeout_s)

        if cookies is not None:
            # добираем cookies домена youtube.com — именно ими кормится yt-dlp
            _goto(page, YOUTUBE)
            _pause(page, 2500)
            cookies = _collect(ctx) or cookies
            try:
                page.set_content(_OK_PAGE)
                _pause(page, 1800)
            except Exception:  # noqa: BLE001
                pass

        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass

    if cookies is None:
        print("⚠  Вход не завершён. Повтори:  bash scripts/login.sh --force")
        return 1

    n = write_cookies_file(cookies, config.COOKIES_FILE)
    # вход через браузер-слой снова делает хозяином профиль в Debian
    config.unmark_cookies_external()
    print(f"✓  Вход сохранён: {n} cookies → {config.COOKIES_FILE}")
    print("   Дальше cookies обновляются сами, по времени. Окно больше не нужно.")
    return 0


# ──────────────────────────── точка входа ────────────────────────────
def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    probe_only = "--probe" in argv
    force = "--force" in argv

    if not force:
        ok, msg = quiet_session_ok()
        if ok:
            print(f"✓  Уже авторизован — {msg}. Окно не понадобилось.")
            return 0
        print(f"→  Тихий вход не прошёл: {msg}", flush=True)
        if probe_only:
            return NEED_WINDOW

    if probe_only:      # --probe --force: сказать «нужно окно», окно не открывать
        return NEED_WINDOW

    return visible_login()


if __name__ == "__main__":
    sys.exit(main())
