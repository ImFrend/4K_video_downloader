"""
ШАГ 2 (повторяется автоматически — HEADLESS, без окна).

Поднимает Chromium с уже залогиненным профилем (из login.py), заходит на YouTube,
браузер сам обновляет токены/cookies сессии, после чего экспортируем свежий
cookies.txt для yt-dlp. Это закрывает проблему «протухающих cookies и динамичных
плейлистов» — запускай перед скачиванием (или по расписанию).

Запуск:  python -m auth.refresh
Выход:   0 — ок; 1 — сессия истекла, нужен повторный python -m auth.login
"""
from __future__ import annotations

import sys

import config
from auth.cookies_export import has_auth_cookies, write_cookies_file

YOUTUBE = "https://www.youtube.com/account"


def main() -> int:
    if not config.BROWSER_PROFILE_DIR.exists():
        print("Профиль не найден. Сначала выполни вход:  python -m auth.login")
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright не установлен. Внутри Debian:  pip install playwright")
        return 1

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    if config.CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(YOUTUBE, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # дать браузеру обновить токены
        except Exception as ex:  # noqa: BLE001
            print(f"⚠  Проблема при заходе на YouTube: {ex}")
        cookies = ctx.cookies()
        ctx.close()

    if not has_auth_cookies(cookies):
        print("⚠  Сессия истекла — нужен повторный вход:  python -m auth.login")
        return 1

    n = write_cookies_file(cookies, config.COOKIES_FILE)
    print(f"✓  cookies.txt обновлён ({n} cookies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
