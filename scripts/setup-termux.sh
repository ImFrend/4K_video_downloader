#!/data/data/com.termux/files/usr/bin/bash
# Настройка НАТИВНОЙ части в Termux (ядро + TUI).
# Запуск:  bash scripts/setup-termux.sh
set -e

echo ">> [1/5] Обновление пакетов Termux"
pkg update -y && pkg upgrade -y

echo ">> [2/5] Базовые пакеты (python, ffmpeg, git, termux-api)"
# termux-api нужен для termux-media-scan (Samsung Music видит треки сразу).
# Дополнительно поставь APK "Termux:API" из F-Droid/того же источника, что Termux.
pkg install -y python ffmpeg git termux-api

echo ">> [3/5] Доступ к памяти телефона (для папки с музыкой)"
termux-setup-storage || echo "   (пропущено — дай разрешение вручную при запросе)"

echo ">> [4/5] Python-зависимости ядра и TUI"
# ВАЖНО: на Termux НЕЛЬЗЯ обновлять сам pip (сломает пакет python-pip).
# Обновляем pip только через системный пакет, не через pip.
pkg install -y python-pip || true
pip install --upgrade yt-dlp textual rich

# JS-движок: YouTube шифрует ссылки через JS (n-challenge). Без рантайма
# yt-dlp выдаёт "Only images are available". deno — рекомендованный для EJS.
echo ">> [4b/5] JS-движок для обхода n-challenge YouTube"
pkg install -y deno || pkg install -y nodejs || \
    echo "   !! поставь вручную: pkg install deno (или nodejs)"

echo ">> [5/5] proot-distro + Debian (для браузер-слоя авторизации)"
pkg install -y proot-distro
proot-distro install debian || echo "   (debian уже установлен)"

cat <<'EOF'

============================================================
 Нативная часть готова.
 Запуск БЕЗ приватных плейлистов (публичное) уже возможен:
     python main.py

 Для приватных плейлистов нужен вход — настрой браузер-слой:
   1) bash scripts/setup-debian.sh   # см. README: запускать ВНУТРИ Debian
   2) python -m auth.login           # один раз, видимое окно (termux-x11)
   3) python -m auth.refresh         # дальше — headless обновление cookies
============================================================
EOF
