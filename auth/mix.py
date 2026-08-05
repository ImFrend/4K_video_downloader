"""
Снимок очереди микса ИЗ БРАУЗЕРА — оттуда, где он реально существует.

Почему так, а не через yt-dlp. Проверено на устройстве: RD-микс привязан к
СЕССИИ браузера, а не к аккаунту. При валидных cookies, одном аккаунте и любом
клиенте плеера (web / mweb / tv / default) yt-dlp получает свою станцию, а
браузер — свою: совпало 2 трека из 25, причём у каждого своя выдача стабильна
и воспроизводима. То есть «правильного» списка по ссылке не существует, есть
список конкретной сессии.

Отсюда решение: спросить браузер, который у нас и так есть — Chromium в Debian
с сохранённым профилем. Он открывает ссылку, отдаёт очередь из DOM и ТУТ ЖЕ
экспортирует cookies той же сессии, поэтому список и cookies заведомо из одного
состояния. Никакого расширения, Kiwi и ручного копирования.

  python3 -m auth.mix <URL>     печатает id по одному в строке
"""
from __future__ import annotations

import sys
from typing import List

import config
from auth.cookies_export import has_auth_cookies, write_cookies_file

# Очередь снимаем не по тегам YouTube (они разные на десктопе и мобильном, и
# меняются), а по параметру index= — он есть у элементов очереди и отсутствует
# у рекомендаций сбоку. Проверено на реальной разметке панели.
_EXTRACT = """() => {
  const rows = [];
  document.querySelectorAll('a[href*="index="]').forEach(a => {
    const u = new URL(a.href, location.origin);
    const v = u.searchParams.get('v');
    const i = parseInt(u.searchParams.get('index'), 10);
    if (v && i > 0) rows.push([i, v]);
  });
  rows.sort((a, b) => a[0] - b[0]);
  const ids = [];
  rows.forEach(x => { if (ids.indexOf(x[1]) < 0) ids.push(x[1]); });
  return ids;
}"""


def snapshot(url: str, timeout_s: float = 45.0) -> List[str]:
    """
    Список video id очереди в порядке проигрывания. [] — снять не вышло.
    Побочно обновляет cookies.txt из той же сессии.
    """
    if not config.BROWSER_PROFILE_DIR.exists():
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=True,
        args=list(config.CHROMIUM_ARGS),
        ignore_default_args=["--enable-automation"],   # не палить автоматизацию
    )
    if config.CHROMIUM_EXECUTABLE:
        launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE

    ids: List[str] = []
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded",
                          timeout=int(timeout_s * 1000))
                # очередь подгружается асинхронно — ждём первую ссылку с index=
                page.wait_for_selector('a[href*="index="]',
                                       timeout=int(timeout_s * 1000))
                page.wait_for_timeout(2500)     # дать списку дорисоваться целиком
                ids = page.evaluate(_EXTRACT) or []
            except Exception:  # noqa: BLE001
                ids = []

            # cookies из ЭТОЙ ЖЕ сессии — список и авторизация из одного состояния
            try:
                cookies = ctx.cookies()
                if has_auth_cookies(cookies):
                    write_cookies_file(cookies, config.COOKIES_FILE)
            except Exception:  # noqa: BLE001
                pass
            ctx.close()
    except Exception:  # noqa: BLE001
        return []

    return [v for v in ids if isinstance(v, str) and len(v) == 11]


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("укажи ссылку: python3 -m auth.mix <URL>", file=sys.stderr)
        return 2
    ids = snapshot(argv[0])
    if not ids:
        print("очередь снять не удалось", file=sys.stderr)
        return 1
    for v in ids:
        print(v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
