#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ВХОД В GOOGLE — ОДНОЙ КОМАНДОЙ.        bash scripts/login.sh
#
# Было: start-x11.sh → руками открыть APK Termux:X11 → НОВАЯ сессия Termux →
#       длинная proot-distro login --bind … → cd → login-debian.sh → войти →
#       вернуться в Termux и нажать Enter → exit.   (6 команд, 4 перехода)
#
# Стало: эта команда. Она сама:
#   1) тихо проверяет сохранённую сессию в Debian. ЖИВА → просто обновляет
#      cookies.txt и выходит. Окно не открывается вообще («я же уже вошёл»).
#   2) если сессии нет — ставит/поднимает X11-сервер, САМ открывает приложение
#      Termux:X11, заходит в Debian, поднимает WM+клавиатуру и Chromium с формой
#      входа Google.
#   3) как только вход состоялся — cookies сохраняются, окно закрывается само,
#      X11-сервер гасится. Возвращаться и жать Enter не надо.
#
# Флаги:
#   --force   не проверять сессию, сразу видимое окно (сменить аккаунт)
#   --check   только тихая проверка, без окна (код 0 = жива, 10 = нужен вход)
# ─────────────────────────────────────────────────────────────────────────────
set -u

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DISTRO="${TY_PROOT_DISTRO:-debian}"
MOUNT="/root/$(basename "$DIR")"
XSOCK="${TMPDIR:-$PREFIX/tmp}/.X11-unix/X0"
STARTED_X11=0

FORCE=0
CHECK=0
for a in "$@"; do
    case "$a" in
        --force) FORCE=1 ;;
        --check) CHECK=1 ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    esac
done

say()  { printf '%s\n' "$*"; }
die()  { printf '!! %s\n' "$*" >&2; exit 1; }

cleanup() {
    # гасим X11-сервер, только если подняли его сами (чужой не трогаем)
    [ "$STARTED_X11" = "1" ] && pkill -f "termux-x11 :0" >/dev/null 2>&1
    return 0
}
trap cleanup EXIT

# ── проверки окружения ──────────────────────────────────────────────────────
# pkg есть только в нативном Termux — внутри Debian его нет (там apt)
command -v pkg >/dev/null 2>&1 || die "это скрипт для нативного Termux (внутри Debian он не нужен)"
command -v proot-distro >/dev/null 2>&1 || die "нет proot-distro — сначала: bash scripts/setup-termux.sh"

# Где лежит rootfs — НЕ гадаем: путь зависит от версии proot-distro, и захардкоженный
# `$PREFIX/var/lib/proot-distro/installed-rootfs/` уже давал ложное «нет дистрибутива»
# на рабочей установке. Проверка мягкая: не нашли — предупреждаем и всё равно пробуем,
# а настоящую ошибку (если она есть) скажет сам proot-distro.
distro_ready() {
    for d in "$PREFIX/var/lib/proot-distro/containers/$DISTRO" \
             "$PREFIX/var/lib/proot-distro/installed-rootfs/$DISTRO"; do
        [ -d "$d" ] && return 0          # 5.x: containers/ ; ≤4.x: installed-rootfs/
    done
    # -q печатает только имена, по одному в строке (в 5.x --installed уже нет)
    proot-distro list -q 2>/dev/null | grep -qx -- "$DISTRO" && return 0
    return 1
}
distro_ready || say "⚠  не вижу '$DISTRO' в обычных местах — пробую всё равно"

# Пролог инннер-команды: находим ARM-Chromium явно (на ~/.bashrc не полагаемся —
# он подхватывается только интерактивным шеллом, а мы запускаем bash -c).
PRELUDE='export PYTHONUNBUFFERED=1; export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-$(command -v chromium || command -v chromium-browser || true)}";'

in_debian() {   # $1 = quiet|x11 (нужен ли общий /tmp с X11-сокетом), $2 = команда
    if [ "$1" = "x11" ]; then
        # --shared-tmp обязателен: через общий /tmp Debian видит X11-сокет Termux
        proot-distro login "$DISTRO" --shared-tmp --bind "$DIR:$MOUNT" -- \
            bash -c "cd '$MOUNT'; $PRELUDE $2"
    else
        proot-distro login "$DISTRO" --bind "$DIR:$MOUNT" -- \
            bash -c "cd '$MOUNT'; $PRELUDE $2"
    fi
}

# ── фаза 1: тихо, без окна ──────────────────────────────────────────────────
if [ "$FORCE" = "0" ]; then
    say "── проверяю сохранённую сессию (тихо, окно не нужно)…"
    in_debian quiet "python3 -m auth.login --probe"
    rc=$?
    case "$rc" in
        0)  say ""
            say "✓ Уже авторизован — cookies обновлены. Окно не понадобилось."
            exit 0 ;;
        10) say "→ сессии нет или истекла — нужен видимый вход" ;;
        *)  say "→ тихая проверка не удалась (код $rc) — пробую видимый вход" ;;
    esac
fi

[ "$CHECK" = "1" ] && exit 10

# ── фаза 2: поднимаем экран ─────────────────────────────────────────────────
ensure_x11_server() {
    if ! command -v termux-x11 >/dev/null 2>&1; then
        say "── ставлю termux-x11 (один раз)…"
        pkg install -y x11-repo >/dev/null 2>&1
        pkg install -y termux-x11-nightly \
            || die "не смог поставить termux-x11-nightly. Проверь, что установлено APK «Termux:X11»."
    fi
    if pgrep -f "termux-x11 :0" >/dev/null 2>&1; then
        say "── X11-сервер уже работает"
        return 0
    fi
    say "── поднимаю X11-сервер (:0)"
    nohup termux-x11 :0 >"${TMPDIR:-$PREFIX/tmp}/termux-x11.log" 2>&1 &
    STARTED_X11=1
}

open_x11_app() {                       # ← это раньше делалось руками из лаунчера
    say "── открываю приложение Termux:X11"
    for AM in am termux-am; do
        command -v "$AM" >/dev/null 2>&1 || continue
        "$AM" start --user 0 -n com.termux.x11/com.termux.x11.MainActivity \
            >/dev/null 2>&1 && return 0
    done
    pkg install -y termux-am >/dev/null 2>&1
    if command -v am >/dev/null 2>&1; then
        am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity \
            >/dev/null 2>&1 && return 0
    fi
    say "   (автоматом не вышло — открой приложение «Termux:X11» сам)"
    return 1
}

wait_socket() {                        # ждём сокет X-сервера, а не «спим наугад»
    i=0
    while [ "$i" -lt 40 ]; do
        [ -e "$XSOCK" ] && return 0
        sleep 0.5
        i=$((i + 1))
    done
    return 1
}

ensure_x11_server
wait_socket || say "   (сокет X11 не появился за 20с — всё равно пробую)"
open_x11_app
sleep 1

say "── открываю окно входа. Введи почту/пароль/2FA на экране Termux:X11."
say "   Возвращаться сюда не надо: как только войдёшь, окно закроется само."
# Android 10+ может запретить фоновый запуск чужого приложения (например, если
# вход нажат из браузера, а Termux в фоне). Сервер X11 при этом уже поднят.
say "   Если экран Termux:X11 не открылся сам — открой его из лаунчера."
say ""
# --force внутри: тихую фазу уже отработали выше, второй раз Chromium не поднимаем.
in_debian x11 "DISPLAY=:0 bash scripts/login-debian.sh --force"
rc=$?

say ""
if [ "$rc" = "0" ] && [ -s "$DIR/cookies.txt" ]; then
    say "✓ Готово — вход сохранён. Приватные плейлисты и My Mix доступны."
    say "  Дальше cookies обновляются сами; эта команда понадобится не скоро."
else
    say "!! Вход не завершён (код $rc). Повтори:  bash scripts/login.sh --force"
fi
exit "$rc"
