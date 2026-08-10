"""
Работа с файлом cookies.txt (формат Netscape — его ест yt-dlp):

  • конвертер из объектов cookie браузера (как их отдаёт chrome.cookies в
    расширении): domain flag path secure expiry name value;
  • разбор обратно — им пользуется проверка сессии (auth/refresh.py);
  • проверка, есть ли в готовом файле маркеры входа;
  • импорт файла, выгруженного из браузера телефона.

Почему cookies берутся из твоего браузера, а не из своего. Проверено на
устройстве: состав RD-микса определяется идентичностью сессии в cookies —
yt-dlp с cookies из Kiwi выдал ровно её список, 25 из 25, а с сессией,
поднятой отдельным Chromium, свой (2 из 25). Значит нужен именно тот браузер,
где ты смотришь миксы, — и держать свой смысла нет.
"""
from __future__ import annotations

import os
import shutil
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


def netscape_has_auth(path: Path) -> bool:
    """
    Есть ли в готовом cookies.txt маркеры входа.

    Отвечает на вопрос «качалка ходит под аккаунтом или анонимно» — а от этого
    зависит поведение микса: под аккаунтом выдача персональная и стабильная,
    анонимно — случайное радио от сида, каждый запрос новый. Без такой проверки
    разницу приходится угадывать по составу скачанного.

    Префикс `#HttpOnly_` снимаем ДО отбрасывания комментариев. Иначе теряются
    ровно те строки, которые тут и ищутся: SID и __Secure-* помечены httpOnly,
    и сторонние экспортёры (путь `python main.py cookies`) пишут их с этим
    префиксом — рабочий файл отвергался с «нет маркеров входа».
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return False
    names = set()
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith(HTTPONLY_PREFIX):
            line = line[len(HTTPONLY_PREFIX):]
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 6:
            names.add(parts[5])
    return bool(AUTH_MARKERS & names)


def netscape_to_cookies(path: Path) -> List[dict]:
    """
    Обратный разбор cookies.txt → список словарей.

    Нужен, чтобы собрать заголовок Cookie для проверки сессии (auth/refresh.py).
    Отдельная функция, а не http.cookiejar.MozillaCookieJar из stdlib, по
    конкретной причине: тот считает строки с префиксом `#HttpOnly_` комментарием
    и молча выбрасывает — то есть ровно SID и __Secure-*, по которым Google и
    узнаёт вход. Проверка тогда всегда отвечала бы «сессия мертва».
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
                c["expires"] = exp     # 0/отсутствие = сессионная
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
    """
    Годится ли файл в качестве cookies.txt. Ошибку называем словами.

    Считаем строки тем же парсером, каким потом читаем файл, — иначе «файл
    принят» и «файл читается» могут расходиться. Раньше здесь был свой фильтр
    строк, и он терял httpOnly-cookies (см. netscape_has_auth).
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        return False, f"файл не читается: {ex}"
    if not txt.strip():
        return False, "файл пустой"
    if txt.lstrip().startswith(("{", "[")):
        return False, "это JSON, а нужен формат Netscape (в расширении выбери «Netscape»)"
    rows = netscape_to_cookies(path)
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
    """Превращает список cookie-словарей браузера в текст Netscape-файла."""
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
