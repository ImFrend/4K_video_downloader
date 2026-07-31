#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ПРОВЕРКА ЗАВИСИМОСТЕЙ.        bash scripts/doctor.sh [--quick]
#
# Показывает, что стоит, чего не хватает и какой командой чинить. Нужна, когда
# код приехал через git pull, а окружение осталось от прошлой установки — такое
# расхождение иначе вылезает невнятной ошибкой в середине работы.
#
#   --quick   не заходить в Debian (проверка браузер-слоя занимает ~15с)
# ─────────────────────────────────────────────────────────────────────────────
set -u

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DISTRO="${TY_PROOT_DISTRO:-debian}"
MOUNT="/root/$(basename "$DIR")"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

cd "$DIR" || exit 1

BAD=0
G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; D=$'\033[2m'; N=$'\033[0m'
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
bad()  { BAD=$((BAD + 1)); printf '  %s✗%s %s\n     %sчиню: %s%s\n' "$R" "$N" "$1" "$D" "$2" "$N"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
head_() { printf '\n%s\n' "$1"; }

need_cmd() {   # $1 команда, $2 описание, $3 чем чинить
    if command -v "$1" >/dev/null 2>&1; then ok "$2"; else bad "$2" "$3"; fi
}

need_py() {    # $1 модуль, $2 описание, $3 чем чинить
    if python -c "import $1" >/dev/null 2>&1; then ok "$2"; else bad "$2" "$3"; fi
}

echo "── Зависимости TermuxYoutube ──"

head_ "Нативный Termux"
need_cmd python  "python"                "pkg install python"
need_cmd ffmpeg  "ffmpeg (извлечение аудио)" "pkg install ffmpeg"
need_cmd git     "git"                   "pkg install git"
need_cmd termux-media-scan "termux-api (Samsung Music видит треки сразу)" \
    "pkg install termux-api + APK Termux:API"
if command -v deno >/dev/null 2>&1 || command -v node >/dev/null 2>&1; then
    ok "JS-рантайм (n-challenge YouTube)"
else
    bad "JS-рантайм — без него «Only images are available»" "pkg install deno"
fi
need_cmd proot-distro "proot-distro (контейнер под браузер)" "pkg install proot-distro"

head_ "Python-модули"
need_py yt_dlp  "yt-dlp"  "pip install -U yt-dlp"
need_py textual "textual (TUI)" "pip install -U textual"
need_py rich    "rich (TUI)"    "pip install -U rich"
if python -c "import yt_dlp" >/dev/null 2>&1; then
    V="$(python -c 'import yt_dlp;print(yt_dlp.version.__version__)' 2>/dev/null)"
    printf '     %sверсия yt-dlp: %s (YouTube ломает совместимость чаще всего именно тут)%s\n' \
        "$D" "${V:-?}" "$N"
fi

head_ "Вход в Google (нужен только для приватных плейлистов)"
need_cmd termux-x11 "termux-x11 (экран для окна входа)" \
    "pkg install x11-repo && pkg install termux-x11-nightly"
if command -v am >/dev/null 2>&1 || command -v termux-am >/dev/null 2>&1; then
    ok "am (сам открывает приложение Termux:X11)"
else
    bad "am — Termux:X11 придётся открывать руками" "pkg install termux-am"
fi

head_ "Приложения (APK)"
if command -v pm >/dev/null 2>&1; then
    for p in com.termux.x11:"Termux:X11" com.termux.api:"Termux:API" \
             com.termux.widget:"Termux:Widget"; do
        pkgid="${p%%:*}"; name="${p##*:}"
        if pm list packages 2>/dev/null | grep -q "$pkgid"; then
            ok "$name"
        else
            bad "$name не установлен" "поставь APK из того же источника, что Termux (см. README)"
        fi
    done
else
    warn "не могу проверить APK (нет pm) — сверься с таблицей в README"
fi

head_ "Память телефона"
if [ -d "$HOME/storage" ] || [ -w /storage/emulated/0 ]; then
    ok "доступ к общей памяти (папка Music)"
else
    bad "нет доступа к памяти — музыку некуда класть" "termux-setup-storage"
fi

head_ "Браузер-слой ($DISTRO)"
if proot-distro list -q 2>/dev/null | grep -qx -- "$DISTRO" \
   || [ -d "$PREFIX/var/lib/proot-distro/containers/$DISTRO" ] \
   || [ -d "$PREFIX/var/lib/proot-distro/installed-rootfs/$DISTRO" ]; then
    ok "$DISTRO установлен"
    if [ "$QUICK" = "1" ]; then
        warn "содержимое не проверял (--quick)"
    else
        echo "     (захожу внутрь, ~15с…)"
        INNER='c=0
command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || { echo "NO_CHROMIUM"; c=1; }
python3 -c "import playwright" >/dev/null 2>&1 || { echo "NO_PLAYWRIGHT"; c=1; }
exit $c'
        OUT="$(proot-distro login "$DISTRO" --bind "$DIR:$MOUNT" -- bash -c "$INNER" 2>&1)"
        case "$OUT" in
            *NO_CHROMIUM*)  bad "нет Chromium внутри $DISTRO" "bash scripts/setup-termux.sh" ;;
            *)              ok "Chromium на месте" ;;
        esac
        case "$OUT" in
            *NO_PLAYWRIGHT*) bad "нет Playwright внутри $DISTRO" "bash scripts/setup-termux.sh" ;;
            *)               ok "Playwright на месте" ;;
        esac
    fi
else
    bad "$DISTRO не установлен — приватные плейлисты недоступны" \
        "bash scripts/setup-termux.sh"
fi

head_ "Состояние"
STAMP_MSG="$(python -c 'import config; ok, m = config.setup_is_current(); print("" if ok else m)' 2>/dev/null)"
if [ -z "$STAMP_MSG" ]; then
    ok "окружение соответствует версии кода"
else
    bad "$STAMP_MSG" "bash scripts/setup-termux.sh"
fi
if [ -s "$DIR/cookies.txt" ]; then
    ok "вход выполнен (cookies.txt есть)"
else
    warn "входа нет — публичное качается, приватное нет: bash scripts/login.sh"
fi

echo ""
if [ "$BAD" = "0" ]; then
    printf '%s✓ Всё на месте.%s  Запуск:  python main.py web\n' "$G" "$N"
    exit 0
fi
printf '%s✗ Проблем: %s.%s Почти всё лечится одной командой:\n     bash scripts/setup-termux.sh\n' \
    "$R" "$BAD" "$N"
exit 1
