"""
Работа с файлом cookies.txt (формат Netscape — его ест yt-dlp):

  • конвертер из cookies Playwright: domain flag path secure expiry name value;
  • проверка, есть ли в готовом файле маркеры входа;
  • импорт файла, выгруженного из ДРУГОГО браузера.

Про импорт. Проверено на устройстве: состав RD-микса определяется идентичностью
сессии в cookies — yt-dlp с cookies из Kiwi выдал ровно её список, 25 из 25,
хотя с cookies профиля из Debian давал свой (2 из 25). Значит принеся cookies
того браузера, где ты смотришь миксы, всё сводится к одной станции.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# yt-dlp и расширения-экспортёры помечают httpOnly-cookies этим префиксом
HTTPONLY_PREFIX = "#HttpOnly_"

NETSCAPE_HEADER = (
    "# Netscape HTTP Cookie File\n"
    "# Сгенерировано TermuxYoutube. НЕ редактировать вручную и НЕ коммитить.\n"
)

# Cookies, по которым понятно, что вход в Google состоялся.
AUTH_MARKERS = {"SID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PSIDTS"}


def has_auth_cookies(cookies: Iterable[dict]) -> bool:
    """True, если среди cookies есть маркеры авторизованной сессии Google."""
    names = {c.get("name", "") for c in cookies}
    return bool(AUTH_MARKERS & names)


def netscape_has_auth(path: Path) -> bool:
    """
    Есть ли в готовом cookies.txt маркеры входа.

    Отвечает на вопрос «качалка ходит под аккаунтом или анонимно» — а от этого
    зависит поведение микса: под аккаунтом выдача персональная и стабильная,
    анонимно — случайное радио от сида, каждый запрос новый. Без такой проверки
    разницу приходится угадывать по составу скачанного.
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return False
    names = set()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 6:
            names.add(parts[5])
    return bool(AUTH_MARKERS & names)


def netscape_to_cookies(path: Path) -> List[dict]:
    """
    Обратный разбор cookies.txt → список для Playwright.

    Нужен, чтобы продлевать ЧУЖУЮ сессию, не имея её профиля: загружаем cookies
    в чистый контекст, заходим на YouTube, Google прокручивает токены — и мы
    пишем их обратно. Идентичность сессии сохраняется, а значит и станция микса.
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: List[dict] = []
    for line in txt.splitlines():
        raw = line.strip()
        http_only = raw.startswith(HTTPONLY_PREFIX)
        if http_only:
            raw = raw[len(HTTPONLY_PREFIX):]
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 7:
            continue
        domain, _include_sub, cpath, secure, expiry, name, value = parts[:7]
        if not domain or not name:
            continue
        c = {
            "name": name, "value": value, "domain": domain,
            "path": cpath or "/",
            "secure": secure.strip().upper() == "TRUE",
            "httpOnly": http_only,
        }
        try:
            exp = int(expiry)
            if exp > 0:
                c["expires"] = exp     # 0/отсутствие = сессионная, Playwright сам поймёт
        except ValueError:
            pass
        out.append(c)
    return out


# ──────────────────── импорт cookies из другого браузера ────────────────────
# Где браузеры Android складывают выгруженные файлы
_DOWNLOAD_DIRS = ("/storage/emulated/0/Download", "/storage/emulated/0/Downloads",
                  "~/storage/downloads", "~/Downloads")


def find_exported_cookies() -> Optional[Path]:
    """Свежайший *cookies*.txt в папке «Загрузки» — чтобы не искать путь руками."""
    best: Optional[Path] = None
    for d in _DOWNLOAD_DIRS:
        p = Path(os.path.expanduser(d))
        if not p.is_dir():
            continue
        for f in p.glob("*cookies*.txt"):
            try:
                if best is None or f.stat().st_mtime > best.stat().st_mtime:
                    best = f
            except OSError:
                continue
    return best


def validate_netscape(path: Path) -> Tuple[bool, str]:
    """Годится ли файл в качестве cookies.txt. Ошибку называем словами."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        return False, f"файл не читается: {ex}"
    if not txt.strip():
        return False, "файл пустой"
    if txt.lstrip().startswith(("{", "[")):
        return False, "это JSON, а нужен формат Netscape (в расширении выбери «Netscape»)"
    rows = [ln for ln in txt.splitlines()
            if ln.strip() and not ln.startswith("#") and ln.count("\t") >= 5]
    if not rows:
        return False, "не вижу ни одной строки cookie — формат не Netscape"
    if not netscape_has_auth(path):
        return False, ("нет маркеров входа — экспортируй cookies со страницы "
                       "youtube.com, где ты авторизован")
    return True, f"{len(rows)} cookies, вход на месте"


def import_cookies(src: Path, dest: Path) -> Tuple[bool, str]:
    """
    Кладёт внешний cookies-файл на место рабочего. Проверяет ДО замены — лучше
    отказать сразу, чем узнать о кривом файле посреди загрузки.
    """
    ok, msg = validate_netscape(src)
    if not ok:
        return False, msg
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)               # атомарно: читатель не поймает половину
    except OSError as ex:
        return False, f"не удалось скопировать: {ex}"
    return True, msg


def cookies_to_netscape(cookies: Iterable[dict]) -> str:
    """Превращает список cookies Playwright в текст Netscape-файла."""
    lines = [NETSCAPE_HEADER]
    for c in cookies:
        domain = c.get("domain", "")
        if not domain:
            continue
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        # expires: -1 / отсутствует → сессионная (0)
        expires = c.get("expires", 0)
        try:
            expiry = str(int(expires)) if expires and expires > 0 else "0"
        except (TypeError, ValueError):
            expiry = "0"
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(
            "\t".join([domain, include_sub, path, secure, expiry, name, value])
        )
    return "\n".join(lines) + "\n"


def write_cookies_file(cookies: Iterable[dict], path: Path) -> int:
    """
    Пишет cookies.txt атомарно. Возвращает число записанных cookies.

    Через временный файл + os.replace: качалка может читать cookies.txt в любой
    момент, и обычная запись «обрезать и налить» дала бы ей наполовину готовый
    файл — yt-dlp на это отвечает «does not look like a Netscape format».
    """
    cookies = list(cookies)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(cookies_to_netscape(cookies), encoding="utf-8")
    os.replace(tmp, path)      # атомарная подмена в пределах одной ФС
    return len(cookies)
