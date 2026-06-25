# TermuxYoutube

Аудио-граббер плейлистов YouTube с премиум-TUI прямо в терминале Termux.
Заточен под **Samsung S23 Ultra** (aarch64, AMOLED). Качает **только аудио в
максимальном качестве** (приоритет AAC/m4a, fallback mp3), включая **приватные
плейлисты** — через слой авторизации с авто-обновлением cookies.

---

## Что это и чем не является

- ✅ Скачивает **аудио** из плейлистов/видео в `m4a` (AAC, без перекодирования) или `mp3`.
- ✅ Тянет **приватные плейлисты** (вход в Google → cookies).
- ✅ Сохраняет **обложки**: значок каждого видео (`<трек>.jpg`) + обложку плейлиста
  (`folder.jpg`) с масштабом до **720px**, плюс встраивает cover art в аудиофайл.
- ✅ Имена файлов — строго **UTF-8** (NFC), любой язык сохраняется как есть.
- ✅ Лимит плейлиста настраивается (`config.MAX_PLAYLIST_ITEMS`; YouTube отдаёт до ~5000).
- ✅ Премиум-**TUI** (Textual): AMOLED-чёрный фон, один акцент, живые прогресс-бары.
- ❌ Не качает видео/4K (осознанно — только звук).
- ❌ Не отдельное Android-приложение — всё живёт в терминале.

---

## Архитектура

```
┌───────────────── S23 Ultra · Termux ─────────────────┐
│  НАТИВНО в Termux:                                    │
│    Textual TUI  ──►  core/downloader (yt-dlp как lib) │
│                          │  progress hooks            │
│                          ▼                            │
│                     ffmpeg  ──►  ~/storage/music/*.m4a │
│                          ▲                            │
│                          │ cookies.txt (общий файл)    │
│  В proot-distro / Debian (браузер-слой):              │
│    Playwright + системный ARM-Chromium                │
│      auth/login   (1 раз, видимое окно)               │
│      auth/refresh (headless, обновляет cookies)       │
└───────────────────────────────────────────────────────┘
```

Принятые решения (почему так):
| # | Решение | Выбор |
|---|---|---|
| 1 | Получение cookies | Браузер-слой: 1 раз видимый вход → дальше headless-refresh |
| 2 | Формат | Приоритет **AAC/m4a** (копия, без потерь) → fallback **mp3** |
| 4 | yt-dlp | Как **библиотека** (progress hooks, без парсинга текста) |
| 5 | Дизайн | Премиум: AMOLED-чёрный, акцент iOS-blue, Nerd Font иконки |
| 6 | Анти-бан | `--sleep-interval` (паузы 5–15с). `--download-archive` НЕ используется |
| 7 | Доставка кода | GitHub (`git pull`) |

---

## Структура

```
TermuxYoutube/
├── main.py                 точка входа (tui | login | refresh | grab)
├── config.py               пути и настройки (адаптируются Termux/desktop)
├── core/
│   └── downloader.py        ядро: probe, выбор формата AAC→mp3, загрузка, hooks
├── tui/
│   ├── app.py               Textual-приложение
│   └── app.tcss             премиум-тема (AMOLED)
├── auth/
│   ├── login.py             1-й вход (headful, persistent-профиль)
│   ├── refresh.py           обновление cookies (headless)
│   └── cookies_export.py    Playwright cookies → Netscape (cookies.txt)
├── scripts/
│   ├── setup-termux.sh      нативная установка (ядро+TUI)
│   ├── setup-debian.sh      браузер-слой в proot/Debian
│   └── install-nerdfont.sh  Nerd Font для иконок TUI
├── requirements.txt
└── .gitignore               cookies.txt / профиль / музыка — НЕ коммитятся
```

---

## Установка на S23 Ultra

### 1. Получить код (GitHub)
```bash
pkg install git -y
git clone https://github.com/<твой-логин>/TermuxYoutube.git
cd TermuxYoutube
```

### 2. Нативная часть (ядро + TUI)
```bash
bash scripts/setup-termux.sh
```
После этого **публичное** уже качается:
```bash
python main.py
```

### 2b. Иконки TUI (Nerd Font) — опционально, но красиво
Для глифов (загрузка/галочка/шестерёнка) поставь Nerd Font в Termux:
```bash
bash scripts/install-nerdfont.sh
```
Не хочешь шрифт — выключи иконки, будет безопасный Unicode-fallback:
```bash
export TY_NERD_FONT=0
```

### 3. Браузер-слой (для приватных плейлистов)
Войти в Debian **с bind-монтированием папки проекта** (чтобы cookies.txt был общий):
```bash
proot-distro login debian --bind ~/TermuxYoutube:/root/TermuxYoutube
cd /root/TermuxYoutube
bash scripts/setup-debian.sh
```

### 4. Первый вход (1 раз, нужно видимое окно)
Видимый Chromium на телефоне даёт **Termux-X11**. Установи termux-x11, затем внутри Debian:
```bash
python3 -m auth.login      # вход руками (пароль + 2FA), потом Enter в терминале
```
Дальше сессия обновляется без окна:
```bash
python3 -m auth.refresh    # headless, перед скачиванием или по расписанию
```

---

## Использование

```bash
python main.py                 # TUI: вставь ссылку на плейлист → Enter
python main.py grab <URL>      # без интерфейса (отладка)
python main.py refresh         # обновить cookies
```
Музыка сохраняется в `~/storage/music/TermuxYoutube/<Плейлист>/NN - Название.m4a`.

---

## Риски (коротко)

- ⚠️ **Аккаунт**: cookies = доступ к аккаунту. Не коммить `cookies.txt` (он в `.gitignore`).
  Качаешь свои плейлисты — риск низкий; держи человеческий темп (паузы уже включены).
- ⚠️ **Хрупкость**: YouTube меняет защиту → обновляй `pip install -U yt-dlp`.
- ⚠️ **Chromium в proot** — самое ломкое звено; если падает, проверь `--no-sandbox` и `apt install chromium`.
- ⚖️ Скачивание нарушает ToS YouTube; контент чужой — для личного использования.

---

## Статус проверки

Проверено на dev-машине (Windows, Python 3.10):
- ✅ Ядро: progress hooks, ffmpeg-извлечение аудио, выбор кодека AAC→mp3 (юниты + интеграция на прямом mp4).
- ✅ TUI: рендер, построение карточек, прогресс до `done` (Textual pilot).
- ✅ Конвертер cookies → Netscape.

Проверяется на устройстве (специфика ARM/Termux):
- ⏳ Живой YouTube с cookies (с dev-IP YouTube блокирует гостя — это и есть причина cookie-слоя).
- ⏳ Chromium в proot/Debian, Termux-X11, пути `~/storage`.
```
