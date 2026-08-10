"""
Состояние cookies: жива ли сессия. Без браузера, на stdlib.

Почему здесь больше нет headless-Chromium. Продлить сессию чужого браузера,
не имея его самого, нельзя: ключевой `__Secure-1PSIDTS` прокручивает Google в
ответ именно браузеру, и подделывать этот обмен — менять хрупкое на хрупкое.
Раньше ради него в проекте жил целый слой (proot + Debian + ARM-Chromium +
Playwright, ~2 ГБ) — при том, что сами cookies приезжают из браузера телефона
одним тапом по иконке расширения.

Что делаем вместо этого: честно СПРАШИВАЕМ у YouTube, жива ли сессия — один GET
с нашими cookies и маркер `"LOGGED_IN":true` в ответе. Это не замена продлению,
это то, чего раньше не было вовсе: прежняя логика гадала по возрасту файла
(«меньше 12 часов — значит хорошо»), поэтому молчала, когда cookies уже мертвы,
и тревожила, когда живы. Мёртвую сессию чинит повторный тап по расширению —
и теперь мы говорим об этом ровно тогда, когда это правда.

  python -m auth.refresh     проверить сейчас (0 — жива, 1 — нужен новый экспорт)
"""
from __future__ import annotations

import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Tuple

import config
from auth.cookies_export import netscape_has_auth, netscape_to_cookies

# Одна проверка на процесс: web-UI зовёт ensure_fresh_cookies() из нескольких
# потоков (кнопка + старт очереди), а ходить в сеть дважды за тем же ответом незачем.
_LOCK = threading.RLock()

# Страница, а не API: youtubei требует ключи и версии клиента, которые меняются,
# а обычная выдача HTML с ytcfg стабильна годами.
_PROBE_URL = "https://www.youtube.com/"
# Мобильный UA: с ним YouTube отдаёт заметно более компактную страницу.
_UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/120.0.0.0 Mobile Safari/537.36")
# Читаем только начало ответа: маркер лежит около 50-го килобайта (замерено), а
# тянуть на телефоне всю главную страницу ради одного флага — расточительно.
# Лимит с пятикратным запасом.
_READ_LIMIT = 256 * 1024
# Различаем ТРИ случая, а не два: true — вход есть, false — входа нет, маркера
# нет вовсе — YouTube ответил чем-то другим (консент, капча, сменил разметку).
# Последнее нельзя выдавать за «сессия мертва»: человек пойдёт заново
# выгружать рабочие cookies. Такое честнее назвать «проверить не смог».
_LOGGED_IN = re.compile(rb'"LOGGED_IN"\s*:\s*(true|false)')


# ──────────────────────────── возраст и состояние ────────────────────────────
def cookies_age_hours() -> float | None:
    """Возраст cookies.txt в часах, или None если файла нет."""
    if not config.COOKIES_FILE.exists():
        return None
    return (time.time() - config.COOKIES_FILE.stat().st_mtime) / 3600.0


def checked_ago_hours() -> float | None:
    """Сколько часов назад сессию проверяли живьём. None — не проверяли."""
    ts = config.read_cookies_state().get("checked_at") or 0
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    return (time.time() - ts) / 3600.0 if ts > 0 else None


# ──────────────────────────── живая проверка ────────────────────────────
def _cookie_header(path: Path) -> str:
    """`name=value; …` для домена YouTube из cookies.txt (включая httpOnly)."""
    pairs = []
    seen = set()
    for c in netscape_to_cookies(path):
        domain = (c.get("domain") or "").lstrip(".")
        if not (domain == "youtube.com" or domain.endswith(".youtube.com")
                or domain == "google.com" or domain.endswith(".google.com")):
            continue
        name = c.get("name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        pairs.append(f"{name}={c.get('value', '')}")
    return "; ".join(pairs)


def probe_session(timeout: float | None = None) -> Tuple[str, str]:
    """
    Спросить у YouTube, жива ли сессия. Никогда не бросает.

    Коды:
      alive       — сессия отвечает как авторизованная;
      dead        — cookies есть, но YouTube нас не узнаёт (нужен новый экспорт);
      no_cookies  — файла нет;
      offline     — до YouTube не дошли (сеть/таймаут) — это НЕ приговор cookies.
    """
    if not config.have_cookies():
        return "no_cookies", "cookies.txt нет — приватное и миксы недоступны"
    if not netscape_has_auth(config.COOKIES_FILE):
        return "dead", "в cookies нет маркеров входа — экспортируй с youtube.com"

    header = _cookie_header(config.COOKIES_FILE)
    if not header:
        return "dead", "не смог разобрать cookies.txt"

    req = urllib.request.Request(_PROBE_URL, headers={
        "User-Agent": _UA,
        "Cookie": header,
        "Accept-Language": "ru,en;q=0.9",
        # без сжатия: иначе пришлось бы распаковывать ради одного флага
        "Accept-Encoding": "identity",
    })
    t = config.COOKIES_CHECK_TIMEOUT if timeout is None else timeout
    try:
        with urllib.request.urlopen(req, timeout=t) as resp:
            body = resp.read(_READ_LIMIT)
    except (urllib.error.URLError, OSError, ValueError) as ex:
        return "offline", f"проверить не удалось ({ex.__class__.__name__})"

    m = _LOGGED_IN.search(body)
    if m is None:
        # ответ есть, но не тот — cookies тут ни при чём, вердикт не выносим
        return "offline", "YouTube ответил незнакомой страницей — проверить не смог"
    if m.group(1) == b"true":
        config.mark_cookies_checked(True)
        return "alive", "сессия жива — качаем под аккаунтом"
    config.mark_cookies_checked(False)
    return "dead", ("сессия истекла — открой YouTube в браузере и тапни иконку "
                    "расширения (или python main.py cookies)")


# ──────────────────────────── публичный best-effort хук ────────────────────────
def ensure_fresh_cookies(max_age_hours: float | None = None) -> Tuple[str, str]:
    """
    Зовётся ПЕРЕД скачиванием. Никогда не падает — только сообщает статус.

    Коды (они же CSS-классы индикатора в web-UI):
      fresh  — сессия подтверждена;
      stale  — cookies есть, но подтвердить сейчас не смогли (нет сети);
      dead   — сессия мертва, нужен новый экспорт из браузера;
      none   — cookies нет вовсе (публичное качается, приватное нет).
    """
    max_age = config.COOKIES_MAX_AGE_HOURS if max_age_hours is None else max_age_hours

    if not config.have_cookies():
        return "none", "cookies нет — приватное и миксы недоступны"

    state = config.read_cookies_state()
    ago = checked_ago_hours()
    if ago is not None and ago < max_age:
        # недавняя проверка — верим ей и в сеть не идём
        if state.get("alive"):
            return "fresh", f"сессия подтверждена ({ago:.1f}ч назад)"
        return "dead", "сессия мертва — нужен новый экспорт cookies из браузера"

    with _LOCK:
        ago = checked_ago_hours()          # мог успеть проверить параллельный поток
        if ago is not None and ago < max_age and config.read_cookies_state().get("alive"):
            return "fresh", f"сессия подтверждена ({ago:.1f}ч назад)"
        code, msg = probe_session()

    if code == "alive":
        return "fresh", msg
    if code == "dead":
        return "dead", msg
    if code == "no_cookies":
        return "none", msg
    return "stale", msg                     # offline: работаем с тем, что есть


def status() -> dict:
    """Снимок для интерфейсов: код, текст, есть ли маркеры входа, откуда приехали."""
    code, msg = ("none", "вход не выполнен")
    if config.have_cookies():
        ago = checked_ago_hours()
        alive = config.read_cookies_state().get("alive")
        if ago is None:
            code, msg = "stale", "сессия ещё не проверялась"
        elif alive:
            code, msg = "fresh", f"сессия подтверждена ({ago:.1f}ч назад)"
        else:
            code, msg = "dead", "сессия мертва — нужен новый экспорт"
    return {
        "status": code,
        "msg": msg,
        "auth": netscape_has_auth(config.COOKIES_FILE),
        "source": config.cookies_source(),
    }


def main() -> int:
    """python -m auth.refresh — проверить сессию прямо сейчас."""
    code, msg = probe_session()
    if code == "alive":
        print(f"✓  {msg}")
        return 0
    print(f"⚠  {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
