"""
Конвертер cookies Playwright → формат Netscape (cookies.txt), который ест yt-dlp.

Playwright отдаёт cookies как список dict'ов; yt-dlp хочет Netscape-файл:
  domain  flag  path  secure  expiry  name  value
"""
from __future__ import annotations

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
    """Пишет cookies.txt. Возвращает число записанных cookies."""
    cookies = list(cookies)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookies_to_netscape(cookies), encoding="utf-8")
    return len(cookies)
