# TermuxYoutube

Аудио-граббер плейлистов YouTube для **Samsung S23 Ultra** (aarch64, AMOLED),
работает прямо в Termux. Качает **только аудио в максимальном качестве**, включая
**приватные плейлисты** и динамические **My Mix** — через слой авторизации с
авто-обновлением cookies. Два интерфейса: терминальный **TUI** и **Web-UI** в
браузере телефона («как приложение», без команд).

---

## Что это и чем не является

- ✅ Скачивает **аудио** из плейлистов/видео/My Mix в `m4a` (AAC) или `mp3`.
- ✅ Тянет **приватные плейлисты** и **My Mix** (вход в Google → cookies).
- ✅ Встраивает **обложку** (cover art) + теги: `album`, `track=N/всего`
  (Samsung Music сортирует по тегу → правильный порядок 1..25, не по имени).
- ✅ **Дедуп**: один трек не качается дважды (по video id + архив `.downloaded.txt`).
- ✅ Имена файлов — строго **UTF-8** (NFC), любой язык сохраняется как есть.
- ✅ **Параллельные загрузки** с человеческим темпом (джиттер старта + паузы).
- ✅ Мгновенная индексация в медиатеку (`termux-media-scan`) — Samsung Music видит
  треки сразу, без перезагрузки телефона.
- ✅ Премиум-**TUI** (Textual) **и** премиум-**Web-UI** (iOS-стиль, AMOLED).
- ✅ **100% on-device**: web-сервер слушает только `127.0.0.1`, никакого облака.
- ❌ Не качает видео/4K (осознанно — только звук).
- ❌ Не отдельное Android-приложение (пока) — всё живёт в Termux.

---

## Архитектура

```
┌───────────────── S23 Ultra · Termux ───────────────────┐
│  НАТИВНО в Termux:                                      │
│    Textual TUI ─┐                                       │
│                 ├─► core/downloader (yt-dlp как lib)    │
│    Web-UI ───────┘        │  progress hooks             │
│    (web/server.py,        ▼                             │
│     stdlib, 127.0.0.1)  ffmpeg ──► /storage/.../Music/  │
│                           ▲                             │
│                           │ cookies.txt (общий файл)     │
│  В proot-distro / Debian (браузер-слой, нужен РЕДКО):   │
│    Playwright + системный ARM-Chromium                  │
│      auth/login   (1 раз, видимое окно через Termux:X11)│
│      auth/refresh (headless, авто-обновляет cookies)    │
└─────────────────────────────────────────────────────────┘
```

Принятые решения (почему так):
| # | Решение | Выбор |
|---|---|---|
| 1 | Получение cookies | Браузер-слой: 1 раз видимый вход → дальше headless-refresh **по времени, без кнопки** |
| 2 | Формат | TUI: AAC/m4a. Web: 3 реальных уровня (Opus ~160k / AAC 128k / ~50–64k) |
| 4 | yt-dlp | Как **библиотека** (progress hooks, без парсинга текста) |
| 5 | Дизайн | Премиум: AMOLED-чёрный, акцент iOS-blue, принципы iOS (GPU-анимации, пружины) |
| 6 | Анти-бан | Джиттер старта + паузы между плейлистами + **адаптивный делёж потоков** |
| 7 | Доставка кода | GitHub (`git pull`) |
| 8 | Стек Web-UI | **stdlib** `http.server` — ноль зависимостей, тянет любой старый телефон |

---

## Структура

```
TermuxYoutube/
├── main.py                 точка входа (tui | web | login | refresh | grab)
├── config.py               пути и настройки (адаптируются Termux/desktop)
├── core/
│   └── downloader.py        ядро: probe, формат, загрузка, hooks, дедуп, медиаскан
├── tui/
│   ├── app.py               Textual-приложение
│   └── app.tcss             премиум-тема (AMOLED)
├── web/                     ── Web-UI (localhost, 100% on-device) ──
│   ├── server.py            stdlib-сервер: очередь, SSE-прогресс, оркестрация
│   └── static/
│       ├── index.html       2 экрана: очередь ⇄ детали плейлиста
│       ├── style.css        iOS-тема: AMOLED, сегменты, «созревающие» карточки
│       └── app.js           SSE, keyed-DOM, drag-сегменты с резиной
├── auth/
│   ├── login.py             1-й вход (headful, persistent-профиль)
│   ├── refresh.py           обновление cookies (headless) + ensure_fresh_cookies()
│   └── cookies_export.py    Playwright cookies → Netscape (cookies.txt)
├── scripts/
│   ├── setup-termux.sh      нативная установка (ядро + TUI + Web)
│   ├── setup-debian.sh      браузер-слой в proot/Debian
│   ├── start-x11.sh         запуск Termux:X11 (для видимого входа)
│   ├── login-debian.sh      видимый вход в Chromium
│   ├── start-web.sh         launcher Web-UI для Termux:Widget (wake-lock)
│   └── install-nerdfont.sh  Nerd Font для иконок TUI
├── requirements.txt
└── .gitignore               cookies.txt / профиль / музыка — НЕ коммитятся
```

---

## Установка на S23 Ultra

### 1. Получить код (GitHub)
```bash
pkg install git -y
git clone https://github.com/<твой-логин>/4K_video_downloader.git
cd 4K_video_downloader
```

### 2. Нативная часть (ядро + TUI + Web)
```bash
bash scripts/setup-termux.sh
```
После этого **публичное** уже качается (TUI или Web):
```bash
python main.py        # TUI
python main.py web    # Web-UI в браузере
```

### 2b. Иконки TUI (Nerd Font) — опционально, но красиво
```bash
bash scripts/install-nerdfont.sh
# не хочешь шрифт — выключи иконки: export TY_NERD_FONT=0
```

### 3. Браузер-слой (для приватных плейлистов) — встроенный вход «как в 4KVD»

Нужен **редко** — только первый вход и когда сессия истечёт. Cookies-refresh
дальше идёт сам, по времени, без окна.

**3a. Поставить Debian + Playwright + Chromium** (один раз):
```bash
proot-distro login debian --shared-tmp \
  --bind ~/4K_video_downloader:/root/4K_video_downloader
cd /root/4K_video_downloader
bash scripts/setup-debian.sh
exit                         # вернуться в Termux
```

**3b. Запустить X11-сервер** (нативный Termux; нужно APK «Termux:X11»):
```bash
bash scripts/start-x11.sh    # затем ОТКРОЙ приложение Termux:X11
```

**3c. Видимый вход** (в другой сессии Termux → Debian):
```bash
proot-distro login debian --shared-tmp \
  --bind ~/4K_video_downloader:/root/4K_video_downloader
cd /root/4K_video_downloader
bash scripts/login-debian.sh   # откроется Chromium → войди руками (пароль+2FA)
```
cookies сохранятся в профиль и в `cookies.txt`. Дальше — само:
```bash
python -m auth.refresh         # headless (или авто из main.py перед скачиванием)
```

---

## Использование

```bash
python main.py                 # TUI: вставь ссылку на плейлист → Enter
python main.py web             # Web-UI на localhost (браузер телефона)
python main.py grab <URL>      # без интерфейса (отладка)
python main.py refresh         # обновить cookies
```
Музыка сохраняется в `/storage/emulated/0/Music/<Плейлист>/NN - Название.m4a`
(путь задан в `config.OUTPUT_DIR`).

---

## Web-UI «как приложение» (один тап, без команд)

Лёгкий локальный интерфейс на **stdlib** (`http.server`, **ноль зависимостей** —
тянет даже слабые/старые телефоны). Рисует браузер телефона; сервер слушает
**строго `127.0.0.1`** — 100% on-device, наружу не доступен.

```bash
python main.py web      # поднимет сервер и сам откроет браузер
```

**Возможности:**
- 📋 **Вставка плейлиста из буфера** одним тапом → `probe` → карточка в очереди.
- 🗂 **Очередь до 5 My Mix**; тап по миксу → экран **деталей** с потреково.
- 🎨 **Качество ②** — 3 реальных потока YouTube, цвет по уровню:
  🔵 **Максимум** (Opus ~160k) · 🟢 **Стандарт** (AAC 128k) · ⚪ **Эконом** (~50–64k).
- 🏷 **Платформа ①** — бренд-цвета из логотипов (iOS=графит, Win=синий,
  Android=зелёный, Linux=янтарь); задаёт контейнер/кодек.
- 🎚 **Слайдер параллелизма** с цветовым риском 🟢→🔴; метка и риск считаются
  по факту (см. «Параллелизм» ниже).
- 📈 **Карточка «созревает»**: рамка перетекает синий → зелёный по мере %,
  свечение растёт; готово → зелёный, ошибка → красный.
- 🍎 **Принципы iOS**: GPU-анимации (`transform: scaleX`), пружинный easing,
  сегмент-контрол с **тапом И drag-ом** (тянешь палец, на краях — резина),
  тактильные тапы. Прогресс «доплавляется» CSS между throttle-апдейтами.
- 🔁 Загрузка **переживает закрытие вкладки** (состояние держит сервер, SSE).
- 🔑 **Обновление cookies — авто, по времени, без кнопки** (вход 🔑 в ⚙ — редко).

### Параллелизм и анти-бан

Слайдер = **бюджет потоков** (потолок риска). Бюджет **делится по реально
добавленным миксам**, потолок одного плейлиста — **4 потока** (проверенный 4KVD):

```
1 микс,  слайдер 6  →  1 плейлист × 4 трека = 4 потока   (один My Mix = 4)
2 микса, слайдер 6  →  2 × 3 = 6
3 микса, слайдер 6  →  3 × 2 = 6
```
Плюс человеческий темп: ramp-up/джиттер старта треков (`config.START_JITTER_MAX`)
и пауза 2–12с после полностью скачанного My Mix
(`config.PLAYLIST_PAUSE_MIN/MAX`). Суммарно потоков **не больше слайдера**.

### Иконка на домашнем экране (Termux:Widget)

1. Поставь APK **Termux:Widget** (с того же источника, что и Termux — F-Droid).
2. Слинкуй launcher в папку ярлыков и сделай исполняемым:
   ```bash
   mkdir -p ~/.shortcuts
   chmod +x ~/4K_video_downloader/scripts/start-web.sh
   ln -sf ~/4K_video_downloader/scripts/start-web.sh ~/.shortcuts/TermuxYoutube
   ```
3. Добавь на домашний экран **виджет Termux:Widget** → тап по «TermuxYoutube»
   поднимает сервер (с `wake-lock`) и открывает UI. Без единой команды.

> ⚠️ **Батарея.** Android (Doze) душит фоновые процессы. Один раз:
> *Настройки → Приложения → Termux → Батарея → «Не оптимизировать / Unrestricted»*.
> Иначе долгая загрузка может оборваться при гаснущем экране.

---

## Риски (коротко)

- ⚠️ **Аккаунт**: cookies = доступ к аккаунту. Не коммить `cookies.txt` (он в `.gitignore`).
  Качаешь свои плейлисты — риск низкий; держи человеческий темп (включён).
- ⚠️ **Хрупкость**: YouTube меняет защиту → обновляй `pip install -U yt-dlp`.
- ⚠️ **«Only images are available» / «Requested format is not available»**: YouTube
  шифрует ссылки через JS (n-challenge). Нужен JS-рантайм (`pkg install deno`) — его
  ставит `setup-termux.sh`. Решатель EJS yt-dlp качает с GitHub (через
  `config.REMOTE_COMPONENTS`); первый запуск требует интернета для скачивания решателя.
- ⚠️ **Chromium в proot** — самое ломкое звено (нужен только для входа); если падает,
  проверь `--no-sandbox` и `apt install chromium`.
- ⚖️ Скачивание нарушает ToS YouTube; контент чужой — для личного использования.

---

## Статус проверки

Проверено на dev-машине (Windows, Python 3.10):
- ✅ Ядро: progress hooks, ffmpeg-извлечение аудио, выбор кодека, дедуп, теги (юниты + интеграция).
- ✅ TUI: рендер, построение карточек, прогресс до `done` (Textual pilot).
- ✅ Web-UI: старт сервера, отдача страницы/статики, SSE-поток, `probe` плейлиста,
  endpoints настроек/добавления, guard path-traversal, формула адаптивного дележа.
- ✅ Конвертер cookies → Netscape.

Работает на устройстве (подтверждено вживую):
- ✅ Полный цикл на S23 Ultra: вход, My Mix, 4 параллельных загрузки, Samsung Music.
- ✅ Запуск даже на слабом MediaTek Helio G88 (4+2 ГБ) — «как родной».

Проверяется на устройстве (специфика, точечно):
- ⏳ Web-UI на S23: drag-сегменты/резина, бренд-цвета, медиаскан, Termux:Widget.
