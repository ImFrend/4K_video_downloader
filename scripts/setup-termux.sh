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

echo ">> [5/8] Ярлыки на домашний экран (Termux:Widget)"
chmod +x "$DIR"/scripts/*.sh 2>/dev/null || true
mkdir -p ~/.shortcuts && chmod 700 ~/.shortcuts
ln -sf "$DIR/scripts/start-web.sh" ~/.shortcuts/TermuxYoutube
ln -sf "$DIR/scripts/login.sh"     ~/.shortcuts/TermuxYoutube-login
echo "   ~/.shortcuts/TermuxYoutube        — запуск Web-UI"
echo "   ~/.shortcuts/TermuxYoutube-login  — вход в Google"

stamp() {
    # Отметка «зависимости версии N установлены». По ней код после git pull
    # понимает, что окружение осталось от прошлой версии, и говорит об этом
    # прямо, а не падает где-то в середине работы.
    V="$(cd "$DIR" && python -c 'import config; print(config.SETUP_VERSION)' 2>/dev/null)"
    if [ -n "${V:-}" ] && command -v ffmpeg >/dev/null 2>&1 \
       && python -c "import yt_dlp" >/dev/null 2>&1; then
        printf '%s\n' "$V" > "$DIR/.setup-stamp"
    else
        echo "   !! базовые зависимости не встали — отметку не ставлю."
        echo "      Проверь причину:  bash scripts/doctor.sh"
    fi
}

if [ "$WITH_BROWSER" = "0" ]; then
    echo ">> [6/8] X11 и браузер-слой пропущены (--no-browser)"
    stamp
    echo ""
    echo " Запуск:  python main.py web   (или тап по виджету TermuxYoutube)"
    echo " Проверка зависимостей:  bash scripts/doctor.sh"
    exit 0
fi

echo ">> [6/8] Экран для входа (termux-x11 + am)"
# Ставим ЗАРАНЕЕ: раньше это доустанавливалось на лету посреди входа — человек
# ждал загрузки пакетов там, где ожидал увидеть форму Google.
pkg install -y x11-repo >/dev/null 2>&1
pkg install -y termux-x11-nightly || echo "   (termux-x11 не встал — проверь APK «Termux:X11»)"
pkg install -y termux-am || echo "   (termux-am не встал — Termux:X11 придётся открывать руками)"

echo ">> [7/8] proot-distro + $DISTRO (для браузер-слоя авторизации)"
pkg install -y proot-distro
# путь к rootfs зависит от версии proot-distro (5.x: containers/, ≤4.x:
# installed-rootfs/) — не гадаем, спрашиваем его самого. -q = только имена.
if proot-distro list -q 2>/dev/null | grep -qx -- "$DISTRO"; then
    echo "   ($DISTRO уже установлен)"
else
    proot-distro install "$DISTRO" || echo "   ($DISTRO уже установлен либо не встал — проверю на следующем шаге)"
fi

echo ">> [8/8] Браузер-слой внутри $DISTRO (Playwright + ARM-Chromium)"
echo "   Это долгий шаг (apt + chromium). Заходить в proot руками не надо."
BROWSER_OK=1
proot-distro login "$DISTRO" --bind "$DIR:$MOUNT" -- \
    bash -c "cd '$MOUNT' && bash scripts/setup-debian.sh" || BROWSER_OK=0

stamp

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

 Что-то не так — покажет, что именно, и чем чинить:
     bash scripts/doctor.sh
EOF
[ "$BROWSER_OK" = "1" ] || cat <<'EOF'

 !! Браузер-слой поставить не удалось (сеть/место?). Повтори позже:
    bash scripts/setup-termux.sh
    Публичные плейлисты работают и без него.
EOF
echo "============================================================"
