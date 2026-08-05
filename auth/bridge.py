"""
Мост Termux ⇄ Debian — чтобы браузер-слой дёргался САМ, а не руками.

Проект живёт в двух мирах:
  • нативный Termux  — качалка (yt-dlp, TUI, web-UI). Браузера тут нет.
  • proot-distro/Debian — Playwright + ARM-Chromium. Только ради cookies.

Раньше пользователь сам ходил между мирами: `proot-distro login … --bind …`,
`cd`, `python -m auth.refresh`, `exit`. Из-за этого «авто-обновление cookies»
на телефоне не работало вообще (в Termux нет Playwright → refresh молча
превращался в надпись «обнови в Debian»).

Здесь один вход в браузер-слой: собрать команду, запустить, вернуть результат.
Все, кто раньше писал инструкции пользователю, теперь зовут эти функции.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import config

# Пролог инннер-команды: явно находим ARM-Chromium. НЕ полагаемся на ~/.bashrc —
# он подхватывается только интерактивными шеллами, а мы запускаем bash -c.
_PRELUDE = (
    'export PYTHONUNBUFFERED=1; '
    'export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH='
    '"${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-'
    '$(command -v chromium || command -v chromium-browser || true)}"; '
)

LOGIN_SCRIPT = config.ROOT / "scripts" / "login.sh"


# ──────────────────────────── доступность слоёв ────────────────────────────
def in_browser_layer() -> bool:
    """Мы уже ВНУТРИ браузер-слоя (Debian с Playwright)?"""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _rootfs_candidates() -> list[Path]:
    """Где может лежать rootfs. В proot-distro 5.x это containers/, в ≤4.x —
    installed-rootfs/. Это лишь быстрая проверка: источником правды путь быть
    не может, его меняют между версиями."""
    base = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) \
        / "var/lib/proot-distro"
    return [
        base / "containers" / config.PROOT_DISTRO,
        base / "installed-rootfs" / config.PROOT_DISTRO,
    ]


def have_proot() -> bool:
    """
    Есть ли отсюда ход в браузер-слой.

    Раньше здесь стоял захардкоженный путь к rootfs — и на рабочей установке он
    не совпал, из-за чего авто-обновление cookies молча выключалось. Теперь
    решает наличие самого proot-distro: если дистрибутива нет, об этом честно
    скажет его собственная ошибка, а не тихий False.
    """
    if not shutil.which("proot-distro"):
        return False
    if any(p.is_dir() for p in _rootfs_candidates()):
        return True
    try:
        # -q: только имена, по одному в строке (в 5.x флага --installed уже нет)
        out = subprocess.run(["proot-distro", "list", "-q"],
                             capture_output=True, text=True, timeout=30)
        if config.PROOT_DISTRO in (out.stdout or "").split():
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # не подтвердили — но и не отказываем: пусть попытка сама покажет причину
    return True


def have_login_profile() -> bool:
    """Был ли хоть один успешный вход (профиль браузера лежит внутри репозитория)."""
    return config.BROWSER_PROFILE_DIR.is_dir() and any(config.BROWSER_PROFILE_DIR.iterdir())


def can_bridge() -> bool:
    """Можно ли из нативного Termux сходить в браузер-слой и что-то там сделать."""
    return have_proot() and have_login_profile()


# ──────────────────────────── запуск в Debian ────────────────────────────
def debian_argv(inner: str, shared_tmp: bool = False) -> list[str]:
    """argv для запуска shell-команды внутри Debian с примонтированным проектом."""
    argv = ["proot-distro", "login", config.PROOT_DISTRO]
    if shared_tmp:
        # через общий /tmp Debian видит X11-сокет Termux (нужно видимому окну)
        argv.append("--shared-tmp")
    argv += ["--bind", f"{config.ROOT}:{config.PROOT_MOUNT}", "--",
             "bash", "-c", f"cd '{config.PROOT_MOUNT}'; {_PRELUDE}{inner}"]
    return argv


def run_in_debian(inner: str, timeout: float, shared_tmp: bool = False) -> Tuple[int, str]:
    """Выполнить команду в Debian. Возвращает (код возврата, слитый вывод)."""
    try:
        p = subprocess.run(
            debian_argv(inner, shared_tmp), capture_output=True, text=True,
            timeout=timeout, errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 124, f"браузер-слой не ответил за {timeout:.0f}с"
    except (FileNotFoundError, OSError) as ex:
        return 127, f"не удалось запустить proot-distro: {ex}"
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


# ──────────────────────────── headless-обновление cookies ────────────────────
def refresh_via_proot() -> Tuple[str, str]:
    """
    Обновить cookies.txt, сходив в Debian headless. Зовётся из нативного Termux.
    Коды: ok | expired | unavailable | error  (как у auth.refresh._refresh_once)
    """
    if not have_proot():
        return "unavailable", "браузер-слой не установлен (bash scripts/setup-termux.sh)"
    if not have_login_profile():
        return "expired", "вход не выполнен — bash scripts/login.sh"

    rc, out = run_in_debian("python3 -m auth.refresh",
                            timeout=config.PROOT_REFRESH_TIMEOUT)
    tail = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if rc == 0:
        return "ok", tail or "cookies.txt обновлён"
    if rc == 124:
        return "error", tail or "браузер-слой не ответил вовремя"
    # refresh.main() отдаёт 1 и на «сессия истекла», и на прочие сбои —
    # различаем по тексту, чтобы UI мог предложить именно вход.
    if "истек" in tail or "вход" in tail:
        return "expired", tail
    return "error", tail or f"браузер-слой вернул код {rc}"


def refresh_external_via_proot() -> Tuple[str, str]:
    """
    Продлить принесённые извне cookies через Debian.

    В отличие от refresh_via_proot() профиль браузера НЕ нужен: личность сессии
    приходит из самого cookies.txt, Debian даёт только Chromium.
    """
    if not have_proot():
        return "unavailable", "браузер-слой не установлен (bash scripts/setup-termux.sh)"
    rc, out = run_in_debian("python3 -m auth.refresh --external",
                            timeout=config.PROOT_REFRESH_TIMEOUT)
    tail = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if rc == 0:
        return "ok", tail or "cookies браузера продлены"
    if "истек" in tail or "выгрузи" in tail:
        return "expired", tail
    return "error", tail or f"браузер-слой вернул код {rc}"


# ──────────────────────────── снимок очереди микса ────────────────────────────
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def mix_snapshot(url: str) -> List[str]:
    """
    Состав микса, снятый БРАУЗЕРОМ (там, где он реально существует).
    Пусто — браузер-слой недоступен или страница не отдала очередь; вызывающий
    в этом случае откатывается на обычный разбор через yt-dlp.
    """
    if in_browser_layer():          # мы уже внутри Debian — зовём напрямую
        try:
            from auth.mix import snapshot
            return snapshot(url)
        except Exception:  # noqa: BLE001
            return []

    if not can_bridge():
        return []
    rc, out = run_in_debian(f"python3 -m auth.mix {shlex.quote(url)}",
                            timeout=config.PROOT_MIX_TIMEOUT)
    if rc != 0:
        return []
    # из вывода берём только строки-идентификаторы: proot любит досыпать своё
    return [ln.strip() for ln in out.splitlines() if _ID_RE.match(ln.strip())]


# ──────────────────────────── вход (видимое окно) ────────────────────────────
def login_argv(extra: Sequence[str] = ()) -> list[str]:
    """
    argv «умного входа». На телефоне — scripts/login.sh (он сам решает, нужно ли
    вообще открывать окно, и поднимает X11 + Termux:X11). На десктопе — прямой
    запуск auth.login (там браузер уже под рукой).
    """
    if config.IS_TERMUX:
        return ["bash", str(LOGIN_SCRIPT), *extra]
    return [sys.executable, "-m", "auth.login", *extra]


def run_login(extra: Sequence[str] = ()) -> int:
    """Интерактивный вход в текущем терминале (main.py login)."""
    try:
        return subprocess.call(login_argv(extra), cwd=str(config.ROOT))
    except (FileNotFoundError, OSError) as ex:
        print(f"!! не удалось запустить вход: {ex}")
        return 1


def stream_login(on_line: Callable[[str], None],
                 extra: Sequence[str] = ()) -> int:
    """
    Тот же вход, но построчно отдаёт вывод в callback — чтобы web-UI показывал
    живой статус («проверяю сессию…», «открываю Termux:X11…», «готово»).
    """
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        p = subprocess.Popen(
            login_argv(extra), cwd=str(config.ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, errors="replace",
        )
    except (FileNotFoundError, OSError) as ex:
        on_line(f"!! не удалось запустить вход: {ex}")
        return 127
    assert p.stdout is not None
    for line in p.stdout:
        line = line.rstrip()
        if line:
            on_line(line)
    return p.wait()


def iter_tail(lines: Iterable[str], n: int = 6) -> list[str]:
    """Последние n непустых строк — компактный лог для UI."""
    keep: list[str] = []
    for ln in lines:
        if ln.strip():
            keep.append(ln.strip())
    return keep[-n:]


def which_chromium() -> Optional[str]:
    """Путь к Chromium в ТЕКУЩЕМ мире (не в Debian). Для диагностики."""
    return shutil.which("chromium") or shutil.which("chromium-browser")
