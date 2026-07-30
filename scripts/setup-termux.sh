#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# УСТАНОВКА ЦЕЛИКОМ — ОДНОЙ КОМАНДОЙ.     bash scripts/setup-termux.sh
#
# Ставит и нативную часть (качалка, TUI, Web-UI), и браузер-слой в Debian,
# и ярлыки на домашний экран. Раньше между шагами надо было руками заходить
# в proot (login/cd/exit) и руками линковать shortcuts — теперь нет.
#
# Флаги:
#   --no-browser   не трогать Debian-слой (только качалка публичных плейлистов)
# ─────────────────────────────────────────────────────────────────────────────
set -u

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DISTRO="${TY_PROOT_DISTRO:-debian}"
MOUNT="/root/$(basename "$DIR")"
WITH_BROWSER=1
[ "${1:-}" = "--no-browser" ] && WITH_BROWSER=0

echo ">> [1/7] Обновление пакетов Termux"
pkg update -y && pkg upgrade -y

echo ">> [2/7] Базовые пакеты (python, ffmpeg, git, termux-api)"
# termux-api нужен для termux-media-scan (Samsung Music видит треки сразу).
# Дополнительно поставь APK "Termux:API" из F-Droid/того же источника, что Termux.
pkg install -y python ffmpeg git termux-api

echo ">> [3/7] Доступ к памяти телефона (для папки с музыкой)"
termux-setup-storage || echo "   (пропущено — дай разрешение вручную при запросе)"

echo ">> [4/7] Python-зависимости ядра и TUI"
# ВАЖНО: на Termux НЕЛЬЗЯ обновлять сам pip (сломает пакет python-pip).
# Обновляем pip только через системный пакет, не через pip.
pkg install -y python-pip || true
pip install --upgrade yt-dlp textual rich

# JS-движок: YouTube шифрует ссылки через JS (n-challenge). Без рантайма
# yt-dlp выдаёт "Only images are available". deno — рекомендованный для EJS.
echo ">> [4b/7] JS-движок для обхода n-challenge YouTube"
pkg install -y deno || pkg install -y nodejs || \
    echo "   !! поставь вручную: pkg install deno (или nodejs)"

echo ">> [5/7] Ярлыки на домашний экран (Termux:Widget)"
chmod +x "$DIR"/scripts/*.sh 2>/dev/null || true
mkdir -p ~/.shortcuts && chmod 700 ~/.shortcuts
ln -sf "$DIR/scripts/start-web.sh" ~/.shortcuts/TermuxYoutube
ln -sf "$DIR/scripts/login.sh"     ~/.shortcuts/TermuxYoutube-login
echo "   ~/.shortcuts/TermuxYoutube        — запуск Web-UI"
echo "   ~/.shortcuts/TermuxYoutube-login  — вход в Google"

if [ "$WITH_BROWSER" = "0" ]; then
    echo ">> [6/7] Браузер-слой пропущен (--no-browser)"
    echo ">> [7/7] Готово"
    echo ""
    echo " Запуск:  python main.py web   (или тап по виджету TermuxYoutube)"
    exit 0
fi

echo ">> [6/7] proot-distro + $DISTRO (для браузер-слоя авторизации)"
pkg install -y proot-distro
# путь к rootfs зависит от версии proot-distro (5.x: containers/, ≤4.x:
# installed-rootfs/) — не гадаем, спрашиваем его самого. -q = только имена.
if proot-distro list -q 2>/dev/null | grep -qx -- "$DISTRO"; then
    echo "   ($DISTRO уже установлен)"
else
    proot-distro install "$DISTRO" || echo "   ($DISTRO уже установлен либо не встал — проверю на следующем шаге)"
fi

echo ">> [7/7] Браузер-слой внутри $DISTRO (Playwright + ARM-Chromium)"
echo "   Это долгий шаг (apt + chromium). Заходить в proot руками не надо."
BROWSER_OK=1
proot-distro login "$DISTRO" --bind "$DIR:$MOUNT" -- \
    bash -c "cd '$MOUNT' && bash scripts/setup-debian.sh" || BROWSER_OK=0

cat <<EOF

============================================================
 Установка завершена.

 Скачивание (публичное уже работает):
     python main.py web        Web-UI в браузере телефона
     python main.py            TUI в терминале
     тап по виджету «TermuxYoutube» — то же самое, без команд

 Приватные плейлисты и My Mix — один вход, одной командой:
     bash scripts/login.sh
   (сам поднимет X11, откроет Termux:X11, покажет форму Google
    и закроется, когда войдёшь. Дальше cookies обновляются сами.)
EOF
[ "$BROWSER_OK" = "1" ] || cat <<'EOF'

 !! Браузер-слой поставить не удалось (сеть/место?). Повтори позже:
    bash scripts/setup-termux.sh
    Публичные плейлисты работают и без него.
EOF
echo "============================================================"
