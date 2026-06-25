"""
ШАГ 1 (делается ОДИН раз, с видимым окном — headful).

Открывает Chromium с ПОСТОЯННЫМ профилем, ты входишь в Google руками
(пароль + 2FA — вслепую headless это невозможно, поэтому первый вход — видимый).
После входа cookies сохраняются И в профиль (для будущего headless-refresh),
И в cookies.txt (для yt-dlp).

Termux: запускать внутри proot-distro/Debian с поднятым X11 (termux-x11),
чтобы окно браузера было видно. Дальнейшие обновления — уже headless (refresh.py).

Запуск:  python -m auth.login
"""
from __future__ import annotations

import sys

import config
from auth.cookies_export import has_auth_cookies, write_cookies_file

YOUTUBE = "https://www.youtube.com/account"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright не установлен. Внутри Debian:  pip install playwright")
        return 1

    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 412, "height": 915},  # пропорции телефона
    )
    if config.CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(YOUTUBE, wait_until="domcontentloaded")
        except Exception as ex:  # noqa: BLE001
            print(f"Не удалось открыть YouTube: {ex}")

        print("\n" + "=" * 56)
        print("  Войди в свой Google-аккаунт в открытом окне браузера.")
        print("  Когда увидишь, что вошёл — вернись сюда и нажми Enter.")
        print("=" * 56 + "\n")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print("\nОтменено.")
            ctx.close()
            return 1

        cookies = ctx.cookies()
        ctx.close()

    if not has_auth_cookies(cookies):
        print("⚠  Не вижу cookies входа — возможно, вход не завершён.")
        print("   Файл всё равно сохраню, но проверь и при необходимости повтори.")

    n = write_cookies_file(cookies, config.COOKIES_FILE)
    print(f"✓  Сохранено {n} cookies → {config.COOKIES_FILE}")
    print(f"✓  Профиль браузера → {config.BROWSER_PROFILE_DIR}")
    print("   Дальше обновлять сессию можно headless:  python -m auth.refresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
