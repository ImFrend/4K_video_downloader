#!/usr/bin/env python3
"""
TermuxYoutube — точка входа.

  python main.py            запустить TUI (основной режим)
  python main.py web        web-UI на localhost (открой в браузере телефона)
  python main.py login      вход в Google — одной командой, окно откроется,
                            только если сохранённая сессия уже мертва
  python main.py refresh    обновить cookies (сам сходит в браузер-слой)
  python main.py doctor     проверить зависимости: что стоит, чего не хватает
  python main.py cookies    взять cookies из браузера телефона (см. README)
  python main.py grab URL   скачать без TUI (CLI-режим, для отладки)
"""
from __future__ import annotations

import sys


def _usage() -> None:
    print(__doc__)


def _warn_stale_setup() -> None:
    """Код приезжает через git pull, а зависимости — нет. Скажем об этом вслух."""
    try:
        import config
        ok, msg = config.setup_is_current()
        if not ok:
            print(f"⚠  {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _doctor() -> int:
    import subprocess

    import config
    script = config.ROOT / "scripts" / "doctor.sh"
    if config.IS_TERMUX and script.exists():
        return subprocess.call(["bash", str(script), *sys.argv[2:]])
    # на десктопе полной проверки нет — она про пакеты телефона
    ok, msg = config.setup_is_current()
    print("✓  окружение соответствует версии кода" if ok else f"⚠  {msg}")
    return 0 if ok else 1


def _cookies(args: list) -> int:
    """
    Взять cookies из браузера телефона.

    Состав My Mix определяется идентичностью сессии: с cookies того браузера,
    где ты смотришь миксы, yt-dlp воспроизводит ЕГО список один в один
    (проверено на устройстве: 25 из 25 против 2 из 25 с профилем из Debian).
    """
    from pathlib import Path

    import config
    from auth.cookies_export import find_exported_cookies, import_cookies

    src = Path(args[0]).expanduser() if args else find_exported_cookies()
    if src is None:
        print("Не нашёл выгруженный cookies-файл в «Загрузках».")
        print("Выгрузи его из браузера (расширение экспорта cookies, формат Netscape)")
        print("или укажи путь:  python main.py cookies /путь/к/cookies.txt")
        return 1

    ok, msg = import_cookies(src, config.COOKIES_FILE)
    if not ok:
        print(f"✗  {src}: {msg}")
        return 1

    config.mark_cookies_external(str(src))
    print(f"✓  Взял cookies из {src} — {msg}")
    print("   Миксы теперь будут такими же, как в этом браузере.")
    print("   Авто-обновление их не тронет; когда устареют, повтори эту команду.")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tui"

    if cmd in ("-h", "--help", "help"):
        _usage()
        return 0

    if cmd == "doctor":
        return _doctor()

    if cmd == "cookies":
        return _cookies(sys.argv[2:])

    _warn_stale_setup()

    if cmd == "login":
        # на телефоне это scripts/login.sh (X11 + proot берёт на себя он),
        # на десктопе — прямой запуск auth.login
        from auth.bridge import run_login
        return run_login(sys.argv[2:])

    if cmd == "web":
        from web.server import serve
        no_open = "--no-open" in sys.argv
        return serve(open_browser=not no_open)

    if cmd == "refresh":
        from auth.refresh import main as refresh_main
        return refresh_main()

    if cmd == "grab":
        if len(sys.argv) < 3:
            print("Укажи URL:  python main.py grab <URL>")
            return 1
        return _grab(sys.argv[2])

    # по умолчанию — TUI
    from tui.app import main as tui_main
    tui_main()
    return 0


def _grab(url: str) -> int:
    """CLI-загрузка без интерфейса — удобно для отладки на телефоне."""
    from core.downloader import DownloadManager
    from auth.refresh import ensure_fresh_cookies

    # (c) авто-refresh cookies перед скачиванием
    _, ck_msg = ensure_fresh_cookies()
    print(f"cookies: {ck_msg}")

    dm = DownloadManager()

    def on_progress(tr):
        if tr.status == "downloading":
            print(f"  {tr.percent:5.1f}%  {tr.speed:>10}  {tr.title[:40]}", end="\r")
        elif tr.status == "done":
            print(f"  ✓ {tr.title[:50]}" + " " * 20)
        elif tr.status == "error":
            print(f"  ✗ {tr.title[:40]}: {tr.error}")

    pl = dm.probe(url)
    print(f"Найдено: {len(pl.tracks)} трек(ов){' — ' + pl.title if pl.title else ''}")
    dm.download_all(pl.tracks, on_progress, subdir=pl.title, cover_url=pl.thumbnail,
                    on_sleep=lambda s: print(f"  пауза {s:.0f}s…", end="\r"))
    done = sum(1 for t in pl.tracks if t.status == "done")
    print(f"\nИтог: {done}/{len(pl.tracks)} готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
