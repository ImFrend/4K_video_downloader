#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Launcher для Termux:Widget — ОДИН ТАП по иконке:
#   wake-lock (не дать Android усыпить) → web-UI на localhost → браузер телефона.
# Можно символически слинковать в ~/.shortcuts/ (см. README, раздел Web-UI).
# ─────────────────────────────────────────────────────────────────────────────
set -e

# корень репозитория (readlink -f → работает даже через симлинк из ~/.shortcuts)
SELF="$(readlink -f "$0")"
DIR="$(cd "$(dirname "$SELF")/.." && pwd)"
cd "$DIR"

# не дать процессу уснуть в фоне (критично: Android Doze рвёт загрузку)
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true
trap 'command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true' EXIT

python main.py web
