#!/bin/bash
# Настройка БРАУЗЕР-СЛОЯ внутри proot-distro/Debian (Playwright + системный Chromium).
# ВАЖНО: запускать ВНУТРИ Debian, войдя с bind-монтированием папки проекта:
#
#   proot-distro login debian --bind ~/TermuxYoutube:/root/TermuxYoutube
#   cd /root/TermuxYoutube && bash scripts/setup-debian.sh
#
# Bind нужен, чтобы cookies.txt из браузера лёг в ТУ ЖЕ папку, что видит TUI в Termux.
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

 Дальше (внутри Debian, в папке проекта):
   python3 -m auth.login     # 1 раз, видимое окно — нужен termux-x11
   python3 -m auth.refresh   # обновить cookies headless (перед скачиванием)

 Скачивание (TUI) запускается в НАТИВНОМ Termux:
   python main.py
============================================================
EOF
