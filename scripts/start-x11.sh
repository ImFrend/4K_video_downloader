#!/data/data/com.termux/files/usr/bin/bash
# Запуск X11-сервера в Termux — нужен для ВИДИМОГО Chromium (вход в Google).
# Запускать в НАТИВНОМ Termux (не в Debian).  Требует приложение "Termux:X11".
#   bash scripts/start-x11.sh
set -e

echo ">> Проверяю пакет termux-x11"
pkg install -y x11-repo >/dev/null 2>&1 || true
pkg install -y termux-x11-nightly || {
    echo "!! Не удалось поставить termux-x11-nightly."
    echo "   Убедись, что установлено APK 'Termux:X11' (github.com/termux/termux-x11)."
}

# гасим прежний сервер, если висит
pkill -f "termux-x11 :0" 2>/dev/null || true

echo ">> Запускаю X11-сервер на DISPLAY :0"
termux-x11 :0 >/dev/null 2>&1 &
sleep 2

cat <<'EOF'

============================================================
 X11-сервер запущен (:0).
 1) ОТКРОЙ приложение "Termux:X11" — там увидишь графику.
 2) В ДРУГОЙ сессии Termux зайди в Debian и запусти вход:

   proot-distro login debian --shared-tmp \
     --bind ~/4K_video_downloader:/root/4K_video_downloader
   cd /root/4K_video_downloader
   bash scripts/login-debian.sh

 (--shared-tmp обязателен: через него Debian видит X11-сокет Termux)
============================================================
EOF
