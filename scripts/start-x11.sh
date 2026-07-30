#!/data/data/com.termux/files/usr/bin/bash
# Поднять X11-сервер и открыть приложение Termux:X11.
#
# Для входа в Google это НЕ нужно запускать отдельно — всё делает
#   bash scripts/login.sh
# Скрипт оставлен на случай, когда экран X11 нужен сам по себе.
#
#   bash scripts/start-x11.sh
set -u

echo ">> Проверяю пакет termux-x11"
if ! command -v termux-x11 >/dev/null 2>&1; then
    pkg install -y x11-repo >/dev/null 2>&1 || true
    pkg install -y termux-x11-nightly || {
        echo "!! Не удалось поставить termux-x11-nightly."
        echo "   Убедись, что установлено APK 'Termux:X11' (github.com/termux/termux-x11)."
    }
fi

# гасим прежний сервер, если висит
pkill -f "termux-x11 :0" >/dev/null 2>&1

echo ">> Запускаю X11-сервер на DISPLAY :0"
nohup termux-x11 :0 >"${TMPDIR:-$PREFIX/tmp}/termux-x11.log" 2>&1 &

# ждём сокет, а не «спим наугад»
XSOCK="${TMPDIR:-$PREFIX/tmp}/.X11-unix/X0"
i=0
while [ "$i" -lt 40 ] && [ ! -e "$XSOCK" ]; do sleep 0.5; i=$((i + 1)); done

echo ">> Открываю приложение Termux:X11"
for AM in am termux-am; do
    command -v "$AM" >/dev/null 2>&1 || continue
    "$AM" start --user 0 -n com.termux.x11/com.termux.x11.MainActivity >/dev/null 2>&1 && break
done

cat <<'EOF'

============================================================
 X11-сервер запущен (:0), приложение Termux:X11 открыто.

 Для входа в Google отдельная возня не нужна — просто:
   bash scripts/login.sh
============================================================
EOF
