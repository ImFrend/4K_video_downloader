#!/data/data/com.termux/files/usr/bin/bash
# Устанавливает Nerd Font (JetBrains Mono) в терминал Termux — для иконок в TUI.
# Запуск:  bash scripts/install-nerdfont.sh
set -e

pkg install -y curl unzip

TMP="$(mktemp -d)"
URL="https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip"

echo ">> Скачиваю JetBrains Mono Nerd Font…"
curl -fL --retry 3 -o "$TMP/font.zip" "$URL"

echo ">> Распаковываю Regular-начертание…"
# берём первое подходящее Regular.ttf из архива
FILE="$(unzip -Z1 "$TMP/font.zip" | grep -i 'Regular.ttf$' | head -n1)"
if [ -z "$FILE" ]; then
    echo "!! Не нашёл Regular.ttf в архиве"; exit 1
fi
unzip -o "$TMP/font.zip" "$FILE" -d "$TMP" >/dev/null

mkdir -p ~/.termux
cp "$TMP/$FILE" ~/.termux/font.ttf
termux-reload-settings || true
rm -rf "$TMP"

echo "✓ Nerd Font установлен. Иконки в TUI теперь отрисуются."
echo "  (если не нравится — выключить: export TY_NERD_FONT=0)"
