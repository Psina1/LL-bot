# Деплой на Яндекс Cloud VM

Этот документ описывает простой MVP-деплой: одна VM, Docker Compose, контейнер бота и контейнер PostgreSQL + pgvector.

## Цель

После переезда бот должен работать 24/7 на сервере, а локальная копия на ПК разработчика должна быть выключена.

Важно:
- не запускать одновременно локального и серверного бота с одним `TELEGRAM_BOT_TOKEN`;
- не хранить токены в GitHub;
- не удалять Docker volumes без отдельного решения о backup/restore.

## Что понадобится

- Аккаунт Яндекс Cloud с привязанным биллингом.
- Публичный репозиторий GitHub с проектом.
- SSH-ключ разработчика.
- Telegram bot token.
- OpenAI API key.
- Список Telegram admin IDs.

## Рекомендуемая VM

- OS: Ubuntu 22.04 LTS или Ubuntu 24.04 LTS.
- vCPU: 2.
- RAM: 4 GB.
- Disk: 40 GB или больше.
- Public IP: включить.
- Доступ: SSH по ключу.

Для MVP webhook не нужен. Бот работает через polling, поэтому домен и HTTPS пока не требуются.

## Создание VM в интерфейсе Яндекс Cloud

1. Открыть Яндекс Cloud Console.
2. Выбрать нужное облако и каталог.
3. Перейти в `Compute Cloud`.
4. Нажать `Создать VM`.
5. Выбрать образ Ubuntu 22.04 LTS или 24.04 LTS.
6. Указать ресурсы: 2 vCPU, 4 GB RAM.
7. Указать диск: 40 GB.
8. Включить публичный IP.
9. Добавить SSH-ключ.
10. Создать VM.

После создания сохранить:
- публичный IP;
- имя пользователя для SSH, обычно `ubuntu`;
- зону размещения, если понадобится для поддержки.

## Подключение к серверу

На Windows PowerShell:

```powershell
ssh ubuntu@SERVER_PUBLIC_IP
```

Если используется отдельный ключ:

```powershell
ssh -i C:\path\to\key ubuntu@SERVER_PUBLIC_IP
```

## Установка Docker на Ubuntu

На сервере:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo ${UBUNTU_CODENAME:-$VERSION_CODENAME}) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

После `usermod` выйти из SSH и зайти снова.

Проверка:

```bash
docker --version
docker compose version
docker run hello-world
```

## Клонирование проекта

```bash
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/Psina1/LL-bot.git
cd LL-bot
```

## Настройка `.env`

На сервере:

```bash
cp .env.example .env
nano .env
```

Заполнить:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_IDS=

POSTGRES_DB=leader_bot
POSTGRES_USER=postgres
POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://postgres:CHANGE_ME_STRONG_PASSWORD@postgres:5432/leader_bot

LLM_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
LLM_BASE_URL=

BOT_MODE=polling
ENV=production

DATA_DIR=./data
UPLOADS_DIR=./data/uploads
MATERIALS_DIR=./data/materials

MAX_FILE_SIZE_MB=20
ALLOWED_EXTENSIONS=pdf,docx,pptx,txt
MAX_CONTEXT_CHUNKS=8
MAX_CONTEXT_CHARS=12000
MAX_USER_QUESTIONS_PER_MINUTE=10
TEMPERATURE=0.2
LOG_LEVEL=INFO
```

Важно:
- не коммитить `.env`;
- не отправлять `.env` в общий чат;
- пароль Postgres на сервере должен отличаться от локального примера.

## Первый запуск

Перед запуском на сервере выключить локального бота на ПК:

```powershell
docker compose down
```

На сервере:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot
```

Нормальные признаки:

```text
leader_bot_postgres ... healthy
leader_bot_app ... Up
Bot started in polling mode
Run polling for bot @...
```

## Проверка после запуска

В Telegram:
- отправить `/start`;
- открыть `/admin`;
- нажать `Админ: статус`;
- проверить, что БД, LLM chat и embeddings имеют статус OK;
- задать простой вопрос;
- проверить, что ответ приходит.

## Обновление бота на сервере

На сервере:

```bash
cd ~/apps/LL-bot
git pull
docker compose up -d --build bot
docker compose logs -f bot
```

Если менялись зависимости или compose:

```bash
docker compose up -d --build
```

## Остановка

Остановить контейнеры, но оставить данные:

```bash
docker compose down
```

Остановить только бота:

```bash
docker compose stop bot
```

Запустить обратно:

```bash
docker compose start bot
```

Не использовать без backup:

```bash
docker compose down -v
```

`-v` удаляет volumes, включая базу.

## Backup MVP

Минимальный backup базы:

```bash
mkdir -p ~/backups
docker compose exec -T postgres pg_dump -U postgres -d leader_bot > ~/backups/leader_bot_$(date +%F_%H-%M).sql
```

Backup файлов:

```bash
tar -czf ~/backups/leader_bot_data_$(date +%F_%H-%M).tar.gz data
```

Проверить backup:

```bash
ls -lh ~/backups
```

## Restore MVP

Перед restore остановить бота:

```bash
docker compose stop bot
```

Восстановление базы требует аккуратности и отдельного решения. Не выполнять restore на боевой базе без явной причины.

## Правило одного polling-бота

Telegram polling должен работать только в одном месте.

Правильно:
- серверный бот работает;
- локальный бот выключен.

Для разработки лучше создать отдельного тестового Telegram-бота с другим token.

## Что не делать

- Не запускать локальный и серверный бот одновременно с одним token.
- Не коммитить `.env`.
- Не удалять Docker volumes.
- Не открывать наружу PostgreSQL без необходимости.
- Не давать SSH двум редакторам, если им хватает Telegram-админки.

