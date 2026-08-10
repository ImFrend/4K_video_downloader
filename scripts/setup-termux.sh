#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# УСТАНОВКА — ОДНОЙ КОМАНДОЙ.     bash scripts/setup-termux.sh
#
# Ставит ровно одно окружение: нативный Termux (качалка, TUI, Web-UI). ~300 МБ,
# пара минут. Приватные плейлисты и My Mix при этом работают — cookies приезжают
# из браузера телефона (расширение для Kiwi, python main.py kiwi).
#
# Слоя на proot + Debian + ARM-Chromium + Playwright больше нет. Он весил ~2 ГБ
# и существовал ради своей сессии в браузере — а именно она и портила миксы:
# состав RD-станции определяется идентичностью сессии в cookies, и с cookies
# твоего браузера yt-dlp повторяет его список 25 из 25 против 2 из 25 со своим.
# ─────────────────────────────────────────────────────────────────────────────
set -u

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

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
# yt-dlp выдаёт "Only images are available". deno — рекомендованный для EJS,
# nodejs — рабочая замена там, где deno не встаёт.
echo ">> [4b/5] JS-движок для обхода n-challenge YouTube"
pkg install -y deno || pkg install -y nodejs || \
    echo "   !! поставь вручную: pkg install deno (или nodejs)"

echo ">> [5/5] Ярлык на домашний экран (Termux:Widget)"
chmod +x "$DIR"/scripts/*.sh 2>/dev/null || true
mkdir -p ~/.shortcuts && chmod 700 ~/.shortcuts
ln -sf "$DIR/scripts/start-web.sh" ~/.shortcuts/TermuxYoutube
# ярлык входа остался от браузер-слоя и теперь ведёт в никуда — убираем
rm -f ~/.shortcuts/TermuxYoutube-login
echo "   ~/.shortcuts/TermuxYoutube — запуск Web-UI"

# Отметка «зависимости версии N установлены». По ней код после git pull понимает,
# что окружение осталось от прошлой версии, и говорит об этом прямо, а не падает
# где-то в середине работы.
V="$(cd "$DIR" && python -c 'import config; print(config.SETUP_VERSION)' 2>/dev/null)"
if [ -n "${V:-}" ] && command -v ffmpeg >/dev/null 2>&1 \
   && python -c "import yt_dlp" >/dev/null 2>&1; then
    printf '%s\n' "$V" > "$DIR/.setup-stamp"
else
    echo "   !! базовые зависимости не встали — отметку не ставлю."
    echo "      Проверь причину:  bash scripts/doctor.sh"
fi

cat <<'EOF'

============================================================
 Готово.

 Запуск:
     python main.py web        Web-UI в браузере телефона
     python main.py            TUI в терминале
     тап по виджету «TermuxYoutube» — то же самое, без команд

 Приватные плейлисты и My Mix — cookies из твоего браузера:
     python main.py kiwi       собрать расширение для Kiwi
   (поставить .zip в Kiwi, открыть YouTube, тапнуть иконку —
    cookies уедут сами. Заодно миксы будут ровно те, что видно
    в браузере: состав микса определяется сессией cookies.)

 Вместо расширения можно файлом:  python main.py cookies
 Жива ли сессия:                  python main.py check
 Проверка зависимостей:           bash scripts/doctor.sh
============================================================
EOF
