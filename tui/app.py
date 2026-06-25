"""
Премиум-TUI (Textual). Слой отображения — логика загрузки в core/.

• Загрузка идёт в отдельном thread-воркере → интерфейс не виснет.
• Прогресс из core приходит через callback и маршалится в UI-поток
  через call_from_thread (из воркера трогать виджеты напрямую нельзя).
"""
from __future__ import annotations

from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Footer, Header, Input, Label, ProgressBar, Static,
)

import config
from core.downloader import DownloadManager, Track

# Иконки статусов. Два набора:
#   • Nerd Font — красивые глифы (нужен установленный Nerd Font в терминале)
#   • Plain     — безопасный Unicode-fallback (рендерится везде)
# Переключение: config.NERD_FONT (env TY_NERD_FONT=0 чтобы выключить).
ICONS_NERD = {
    "queued": "",       #   часы (ожидание)
    "downloading": "",  #   стрелка вниз (загрузка)
    "converting": "",   #   шестерёнка (обработка)
    "done": "",         #   галочка
    "error": "",        #   крест в круге
}
ICONS_PLAIN = {
    "queued": "•",
    "downloading": "⬇",
    "converting": "♪",
    "done": "✓",
    "error": "✗",
}
STATUS_ICON = ICONS_NERD if config.NERD_FONT else ICONS_PLAIN

# Глиф для кнопки запуска
GO_ICON = "" if config.NERD_FONT else "▸"   #  стрелка-в-круге


class TrackRow(Static):
    """Карточка одного трека: название + прогресс-бар + статус."""

    def __init__(self, track: Track) -> None:
        super().__init__()
        self.track = track

    def compose(self) -> ComposeResult:
        idx = f"{self.track.playlist_index:02d}  " if self.track.playlist_index else ""
        yield Label(f"{idx}{self.track.title}", classes="t-title")
        with Horizontal(classes="t-meta"):
            yield Label(STATUS_ICON["queued"], classes="t-icon")
            yield ProgressBar(total=100, show_eta=False, classes="t-bar")
            yield Label("в очереди", classes="t-status")

    def refresh_from(self, tr: Track) -> None:
        self.query_one(".t-icon", Label).update(STATUS_ICON.get(tr.status, "•"))
        self.query_one(ProgressBar).update(progress=tr.percent)

        status_label = self.query_one(".t-status", Label)
        if tr.status == "downloading":
            status_label.update(tr.speed or "…")
        elif tr.status == "converting":
            status_label.update("конвертация")
        elif tr.status == "done":
            status_label.update("готово")
        elif tr.status == "error":
            status_label.update(tr.error or "ошибка")
        else:
            status_label.update("в очереди")

        self.set_class(tr.status == "done", "done")
        self.set_class(tr.status == "error", "error")


class TermuxYoutube(App):
    CSS_PATH = "app.tcss"
    TITLE = "TermuxYoutube"
    SUB_TITLE = "audio · max quality"
    BINDINGS = [
        ("q", "quit", "Выход"),
        ("escape", "quit", "Выход"),
    ]

    def __init__(self, manager: Optional[DownloadManager] = None) -> None:
        super().__init__()
        self._manager = manager or DownloadManager()
        self._rows: dict[int, TrackRow] = {}

    # ── раскладка ──
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            with Horizontal(id="input-row"):
                yield Input(placeholder="Ссылка на плейлист или видео…", id="url")
                yield Button(GO_ICON, id="go", variant="primary")
            yield Static(self._cookie_line(), id="cookie-status")
            yield Static("", id="status")
            yield VerticalScroll(id="tracks")
        yield Footer()

    def on_mount(self) -> None:
        cookie = self.query_one("#cookie-status", Static)
        cookie.set_class(config.have_cookies(), "ok")
        cookie.set_class(not config.have_cookies(), "warn")

    def _cookie_line(self) -> str:
        ok_icon = "" if config.NERD_FONT else "✓"     #  check-circle
        warn_icon = "" if config.NERD_FONT else "⚠"   #  warning
        if config.have_cookies():
            return f"{ok_icon}  вход активен — приватные плейлисты доступны"
        return f"{warn_icon}  без cookies — приватные плейлисты не видны (нужен вход)"

    # ── запуск ──
    @on(Button.Pressed, "#go")
    @on(Input.Submitted, "#url")
    def _start(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not url:
            return
        self.query_one("#url", Input).disabled = True
        self.query_one("#go", Button).disabled = True
        self.query_one("#tracks", VerticalScroll).remove_children()
        self._rows.clear()
        self._set_status("Читаю плейлист…", busy=True)
        self._run(url)

    # ── воркер: probe + загрузка (в отдельном потоке) ──
    @work(thread=True, exclusive=True)
    def _run(self, url: str) -> None:
        try:
            tracks, title = self._manager.probe(url)
        except Exception as ex:  # noqa: BLE001
            self.call_from_thread(self._fail, str(ex))
            return
        if not tracks:
            self.call_from_thread(self._fail, "ничего не найдено")
            return

        self.call_from_thread(self._build_rows, tracks, title)
        self._manager.download_all(
            tracks,
            on_progress=lambda tr: self.call_from_thread(self._on_progress, tr),
            subdir=title,
            on_sleep=lambda s: self.call_from_thread(
                self._set_status, f"Пауза {s:.0f}s (анти-бан)…", True),
        )
        self.call_from_thread(self._finish, tracks)

    # ── UI-поток ──
    def _build_rows(self, tracks: list[Track], title: Optional[str]) -> None:
        container = self.query_one("#tracks", VerticalScroll)
        for t in tracks:
            row = TrackRow(t)
            self._rows[id(t)] = row
            container.mount(row)
        n = len(tracks)
        self._set_status(f"{title or 'трек'} — {n} шт. в очереди", busy=True)

    def _on_progress(self, tr: Track) -> None:
        row = self._rows.get(id(tr))
        if row is not None:
            row.refresh_from(tr)

    def _finish(self, tracks: list[Track]) -> None:
        done = sum(1 for t in tracks if t.status == "done")
        err = sum(1 for t in tracks if t.status == "error")
        self._set_status(f"Готово: {done} ✓   ошибок: {err}", busy=False)
        self.query_one("#url", Input).disabled = False
        self.query_one("#go", Button).disabled = False

    def _fail(self, msg: str) -> None:
        self._set_status(f"Ошибка: {msg[:80]}", busy=False)
        self.query_one("#url", Input).disabled = False
        self.query_one("#go", Button).disabled = False

    def _set_status(self, text: str, busy: bool = False) -> None:
        s = self.query_one("#status", Static)
        s.update(text)
        s.set_class(busy, "busy")


def main() -> None:
    TermuxYoutube().run()


if __name__ == "__main__":
    main()
