#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ПРОВЕРКА ЗАВИСИМОСТЕЙ.        bash scripts/doctor.sh [--quick]
#
# Показывает, что стоит, чего не хватает и какой командой чинить. Нужна, когда
# код приехал через git pull, а окружение осталось от прошлой установки — такое
# расхождение иначе вылезает невнятной ошибкой в середине работы.
#
#   --quick   не ходить в сеть (не проверять, жива ли сессия YouTube)
# ─────────────────────────────────────────────────────────────────────────────
set -u

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
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
# Показываем, КАКОЙ рантайм возьмёт yt-dlp: приоритет его, не наш
# (deno > node > quickjs > bun), и все они разрешены в config.JS_RUNTIMES.
JSRT=""
for c in deno node qjs qjs-ng quickjs bun; do
    command -v "$c" >/dev/null 2>&1 && { JSRT="$c"; break; }
done
if [ -n "$JSRT" ]; then
    ok "JS-рантайм: $JSRT (n-challenge YouTube)"
else
    bad "JS-рантайм — без него «Only images are available»" \
        "pkg install deno (на armv7: pkg install nodejs или quickjs-ng)"
fi

head_ "Python-модули"
need_py yt_dlp  "yt-dlp"  "pip install -U yt-dlp"
need_py textual "textual (TUI)" "pip install -U textual"
need_py rich    "rich (TUI)"    "pip install -U rich"
if python -c "import yt_dlp" >/dev/null 2>&1; then
    V="$(python -c 'import yt_dlp;print(yt_dlp.version.__version__)' 2>/dev/null)"
    printf '     %sверсия yt-dlp: %s (YouTube ломает совместимость чаще всего именно тут)%s\n' \
        "$D" "${V:-?}" "$N"
fi

head_ "Приложения (APK)"
# Termux:X11 больше не нужен: своего браузера у проекта нет.
if command -v pm >/dev/null 2>&1; then
    for p in com.termux.api:"Termux:API" com.termux.widget:"Termux:Widget"; do
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

head_ "Аккаунт (нужен для приватного и для миксов)"
# Важно не «файл есть», а узнаёт ли нас YouTube: анонимный микс — случайная
# выдача, которая не совпадёт с приложением YouTube. Файл при этом может быть
# свежим и уже мёртвым, поэтому спрашиваем сам YouTube, а не смотрим на дату.
if [ -s "$DIR/cookies.txt" ]; then
    if [ "$QUICK" = "1" ]; then
        warn "cookies есть, живьём не проверял (--quick): python main.py check"
    elif python -m auth.refresh >/dev/null 2>&1; then
        ok "сессия жива — качаем под аккаунтом"
    else
        bad "YouTube не узнаёт cookies — миксы будут случайными" \
            "открой YouTube в Kiwi и тапни иконку расширения"
    fi
else
    warn "cookies нет — публичное качается, приватное и миксы нет:"
    printf '     %spython main.py kiwi  → поставить расширение в Kiwi → тапнуть иконку%s\n' "$D" "$N"
fi

head_ "Состояние"
STAMP_MSG="$(python -c 'import config; ok, m = config.setup_is_current(); print("" if ok else m)' 2>/dev/null)"
if [ -z "$STAMP_MSG" ]; then
    ok "окружение соответствует версии кода"
else
    bad "$STAMP_MSG" "bash scripts/setup-termux.sh"
fi

echo ""
if [ "$BAD" = "0" ]; then
    printf '%s✓ Всё на месте.%s  Запуск:  python main.py web\n' "$G" "$N"
    exit 0
fi
printf '%s✗ Проблем: %s.%s Почти всё лечится одной командой:\n     bash scripts/setup-termux.sh\n' \
    "$R" "$BAD" "$N"
exit 1
