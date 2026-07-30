#!/bin/bash
# Настройка БРАУЗЕР-СЛОЯ внутри proot-distro/Debian (Playwright + системный Chromium).
#
# Руками запускать не надо — это делает scripts/setup-termux.sh, он же сам заходит
# в proot с bind-монтированием проекта. Bind нужен, чтобы cookies.txt из браузера
# лёг в ТУ ЖЕ папку, которую видит качалка в нативном Termux.
#
# Если всё же вручную (внутри Debian, в примонтированной папке проекта):
#   bash scripts/setup-debian.sh
set -e

echo ">> [1/3] Пакеты Debian (chromium ARM, ffmpeg, python)"
apt update && apt upgrade -y
apt install -y chromium ffmpeg python3 python3-pip fonts-liberation ca-certificates \
    matchbox-keyboard matchbox-window-manager

echo ">> [2/3] Playwright + yt-dlp"
pip3 install --break-system-packages --upgrade playwright yt-dlp || \
    pip3 install --upgrade playwright yt-dlp

echo ">> [3/3] Привязка Playwright к СИСТЕМНОМУ Chromium (ARM, не качаем x86)"
CHROMIUM_BIN="$(command -v chromium || command -v chromium-browser || true)"
if [ -z "$CHROMIUM_BIN" ]; then
    echo "   !! Chromium не найден после установки — проверь 'apt install chromium'"
    exit 1
fi
echo "   Chromium: $CHROMIUM_BIN"

# Прописываем переменную в bashrc, чтобы config.py её подхватывал
LINE="export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=$CHROMIUM_BIN"
grep -qxF "$LINE" ~/.bashrc 2>/dev/null || echo "$LINE" >> ~/.bashrc
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$CHROMIUM_BIN"

cat <<EOF

============================================================
 Браузер-слой готов (Debian).
   PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=$CHROMIUM_BIN

 Возвращайся в НАТИВНЫЙ Termux — дальше всё оттуда, одной командой:
   bash scripts/login.sh     вход в Google (окно откроется, только если надо)
   python main.py web        качалка

 Обновление cookies дёргается автоматически перед скачиванием.
============================================================
EOF
