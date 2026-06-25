#!/usr/bin/env python3
"""
TermuxYoutube — точка входа.

  python main.py            запустить TUI (основной режим)
  python main.py login      первый вход в Google (видимое окно, 1 раз)
  python main.py refresh    обновить cookies (headless)
  python main.py grab URL   скачать без TUI (CLI-режим, для отладки)
"""
from __future__ import annotations

import sys


def _usage() -> None:
    print(__doc__)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tui"

    if cmd in ("-h", "--help", "help"):
        _usage()
        return 0

    if cmd == "login":
        from auth.login import main as login_main
        return login_main()

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

    tracks, title = dm.probe(url)
    print(f"Найдено: {len(tracks)} трек(ов){' — ' + title if title else ''}")
    dm.download_all(tracks, on_progress, subdir=title,
                    on_sleep=lambda s: print(f"  пауза {s:.0f}s…", end="\r"))
    done = sum(1 for t in tracks if t.status == "done")
    print(f"\nИтог: {done}/{len(tracks)} готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
