#!/bin/bash
# Видимый вход в Google через встроенный Chromium.
# Запускать ВНУТРИ Debian (proot), когда X11-сервер в Termux уже запущен
# (scripts/start-x11.sh) и открыто приложение Termux:X11.
#
#   bash scripts/login-debian.sh
set -e

# дисплей X11-сервера Termux (через --shared-tmp сокет виден из Debian)
export DISPLAY="${DISPLAY:-:0}"

# системный ARM-Chromium (его ставит setup-debian.sh)
if [ -z "$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" ]; then
    export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$(command -v chromium || command -v chromium-browser || true)"
fi

if [ -z "$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" ]; then
    echo "!! Chromium не найден. Сначала: bash scripts/setup-debian.sh"
    exit 1
fi

echo ">> DISPLAY=$DISPLAY"
echo ">> Chromium=$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"

# оконный менеджер — БЕЗ него окно Playwright не отображается в Termux:X11
if command -v matchbox-window-manager >/dev/null 2>&1; then
    if ! pgrep -x matchbox-window > /dev/null 2>&1; then
        echo ">> Запускаю оконный менеджер (matchbox-window-manager)"
        DISPLAY="$DISPLAY" matchbox-window-manager -use_titlebar no >/dev/null 2>&1 &
        sleep 1
    fi
else
    echo "   (нет matchbox-window-manager — поставь: apt install -y matchbox-window-manager)"
fi

# экранная клавиатура в X11 — для ввода логина/пароля тапами
if command -v matchbox-keyboard >/dev/null 2>&1; then
    echo ">> Запускаю экранную клавиатуру (matchbox-keyboard)"
    DISPLAY="$DISPLAY" matchbox-keyboard >/dev/null 2>&1 &
else
    echo "   (нет matchbox-keyboard — поставь: apt install -y matchbox-keyboard)"
fi

echo ">> Открываю видимый браузер для входа…"
cd "$(dirname "$0")/.."
python3 -m auth.login
