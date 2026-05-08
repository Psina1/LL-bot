# Liga Leaders Assistant Bot (MVP)

## 1. Что это за проект
Telegram-бот-ассистент для программы обучения руководителей «Лига лидеров».

MVP сфокусирован на рабочем цикле:
`пользователь -> вопрос -> LLM -> ответ -> лог в БД`,
а затем расширен до RAG по загруженным материалам и пользовательским файлам.

## 2. Что умеет бот
- `/start`, `/help`, главное меню.
- Вопросы по обучению с RAG-поиском по материалам.
- Ответы с блоком источников.
- Сценарий «Мой проект» с сохранением контекста проекта.
- Загрузка пользовательских файлов `PDF/DOCX/PPTX/TXT`.
- Индексация файлов: извлечение текста -> чанки -> embeddings -> сохранение в БД.
- Админ-команды для глобальных материалов и базовой статистики.
- Логирование вопросов/ответов/ошибок в PostgreSQL.

## 3. Архитектура
```text
Telegram
  ↓
aiogram bot handlers
  ↓
application services
  ↓
PostgreSQL + pgvector
  ↓
OpenAI API (chat + embeddings)
```

Структура:
```text
app/
  bot/
  services/
  rag/
  db/
  llm/
  file_processing/
  config.py
  main.py
data/
migrations/
docs/
Dockerfile
docker-compose.yml
requirements.txt
```

## 4. Требования
- Python 3.11+
- Docker + Docker Compose
- Telegram Bot Token
- OpenAI API key

## 5. Переменные окружения
Скопируй `.env.example` в `.env` и заполни значения:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS` (список через запятую)
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- лимиты: `MAX_FILE_SIZE_MB`, `MAX_CONTEXT_CHUNKS`, `MAX_CONTEXT_CHARS`, `MAX_USER_QUESTIONS_PER_MINUTE`

Если OpenAI-ключа пока нет, можно поставить `LLM_PROVIDER=mock`.
В этом режиме бот отвечает тестовым текстом и позволяет проверить Telegram, БД, админов и загрузку файлов.

Пример `DATABASE_URL` для локального запуска:
`postgresql+psycopg://postgres:postgres@localhost:5432/leader_bot`

## 6. Локальный запуск
1. Создай `.env`:
   `cp .env.example .env` (или вручную в Windows).
2. Подними PostgreSQL с pgvector:
   `docker compose up -d postgres`
3. Установи зависимости:
   `pip install -r requirements.txt`
4. Запусти бота:
   `python -m app.main`

Бот запускается в polling-режиме.

## 7. Запуск через Docker
1. Заполни `.env`.
2. Запусти:
   `docker compose up -d --build`
3. Логи:
   `docker compose logs -f bot`

Остановка:
`docker compose down`

## 8. Деплой на Яндекс Cloud VM
Целевая конфигурация VM:
- Ubuntu 22.04/24.04
- 2 vCPU
- 4 GB RAM
- 40 GB disk

Шаги:
1. Создай VM в Яндекс Cloud.
2. Установи Docker и Docker Compose.
3. Скопируй проект на VM.
4. Создай `.env`.
5. Запусти:
   `docker compose up -d --build`
6. Проверь логи:
   `docker compose logs -f bot`
7. Перезапуск:
   `docker compose restart bot`
8. Остановка:
   `docker compose down`

Для MVP используется polling (без webhook и HTTPS).

## 9. Админские команды
- `/admin` — админ-меню.
- `/upload_global_material` — загрузка общего материала.
- `/list_materials` — список материалов.
- `/reindex` — переиндексация документов.
- `/stats` — базовая статистика.
- `/cancel` — сброс состояния.

Доступ проверяется по `TELEGRAM_ADMIN_IDS`.

## 10. Пользовательские сценарии
- `Задать вопрос по обучению`
- `Материалы программы`
- `Домашние задания`
- `Мой проект`
- `Загрузить файл`
- `Помощь`

## 11. Как загружать материалы
### Пользовательский файл
1. Нажми `Загрузить файл`.
2. Отправь `PDF/DOCX/PPTX/TXT`.
3. Бот сохранит файл в `data/uploads/{telegram_id}/`.
4. Бот извлечёт текст, создаст чанки и embeddings.
5. После статуса `ready` можно задавать вопросы по файлу.

### Глобальный материал (админ)
1. Выполни `/upload_global_material`.
2. Отправь файл.
3. Опционально caption:
   `module=3; module_title=Бизнес-анализ; type=homework`

## 12. Как работает RAG
1. Извлекается текст из `PDF/DOCX/PPTX/TXT`.
2. Текст режется на чанки (около 1200 символов + overlap).
3. Для чанков создаются embeddings.
4. Embeddings сохраняются в `chunks` (`pgvector`).
5. На вопрос пользователя строится embedding вопроса.
6. Ищутся top-k релевантные чанки:
   - global материалы
   - user материалы текущего пользователя
7. Контекст передаётся в LLM.
8. Ответ сохраняется в `messages`, источники добавляются в ответ.

## 13. Ограничения MVP
- Нет интеграции с Moodle.
- Нет SSO и сложной системы ролей.
- Нет интеграций с внутренними корпоративными сервисами.
- Бот знает только вручную загруженные материалы.
- Качество ответа зависит от качества исходных документов.
- Если ответа в материалах нет, бот должен сообщать об этом.

## 14. Troubleshooting
1. Бот не запускается:
   - Проверь `TELEGRAM_BOT_TOKEN` и `OPENAI_API_KEY`.
   - Проверь доступность PostgreSQL.
2. Ошибка БД:
   - Проверь `DATABASE_URL`.
   - Проверь, что поднят контейнер `postgres`.
3. Файл не обрабатывается:
   - Проверь размер (`MAX_FILE_SIZE_MB`) и расширение (`ALLOWED_EXTENSIONS`).
4. Пустые ответы по материалам:
   - Проверь статус документа (`ready`).
   - Выполни `/reindex`.
5. Ошибки модели:
   - Проверь лимиты API и корректность `OPENAI_*` переменных.

## Дополнительно
- SQL-инициализация: `migrations/init.sql`
- Тестовые вопросы: `docs/test_questions.md`
