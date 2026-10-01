# Команды проекта — шпаргалка

## 1. Первый раз (уже сделано на этой машине)

```bash
cd ~/Desktop/projects/selfhost_chat
./setkey.sh               # спросит ключ с ollama.com/settings/keys и запишет в .env сам
                          # (пароль входа можно задать в .env строкой AUTH_PASSWORD=...)
```

## 2. Запуск всего (одна команда: бэкенд + фронт)

```bash
./run.sh                  # фронт соберётся сам при первом запуске, дальше только запуск
RUN_FRONTEND=1 ./run.sh   # принудительно пересобрать фронт (после правок src/)
```

- Порт: если 8000 занят (jupyterhub) — сам перескочит на свободный и напечатает
  `[WARN] ... — запускаюсь на NNNN`; закрепить можно в .env строкой `APP_PORT=8001`

## 3. Разработка без пересборок (hot-reload)

```bash
./dev.sh                  # backend (uvicorn --reload) + vite dev одним Ctrl+C
```

- Открывать **http://localhost:5173** (vite), /api уходит через прокси на бэкенд
- Правки и бэкенда, и интерфейса подхватываются на лету; `Ctrl+C` гасит оба

## 4. Остановка и зависшие процессы

```bash
# Ctrl+C в терминале, где запущен скрипт
pkill -f "uvicorn backend.app"            # если запущен не там / повис
pkill -f vite                             # если повис дев-сервер фронта
```

## 5. Тесты

```bash
.venv/bin/python -m unittest discover -s tests
```

## 6. Проверка живого сервера

```bash
curl localhost:8001/healthz
grep '^AUTH_PASSWORD' .env                 # свой пароль для входа
```

## 7. Приборка с портом 8000 (по желанию)

```bash
sudo systemctl disable --now jupyterhub    # отключить узуратора порта навсегда
```

## 8. Данные

```bash
.venv/bin/python -c "import sqlite3; sqlite3.connect('data/chat.db').execute('PRAGMA wal_checkpoint;')"
cp data/chat.db ~/backups/chat-$(date +%F).db   # бэкап = копия файла
```