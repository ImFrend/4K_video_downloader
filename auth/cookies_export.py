"""
Конвертер cookies Playwright → формат Netscape (cookies.txt), который ест yt-dlp.

Playwright отдаёт cookies как список dict'ов; yt-dlp хочет Netscape-файл:
  domain  flag  path  secure  expiry  name  value
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


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
