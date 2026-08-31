from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.db.models import Base
from app.db.session import engine


DEFAULT_PROGRAM_LESSONS = [
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b1",
        "block_title": "Кикоф программы и блока",
        "block_order": 1,
        "lesson_key": "s1_b1_kickoff",
        "lesson_number": None,
        "lesson_title": "Кикоф программы и блока",
        "date_start": date(2026, 5, 21),
        "date_end": None,
        "date_text": "21.05.2026",
        "speaker": None,
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 10,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b2",
        "block_title": "Бизнес-консалтинг",
        "block_order": 2,
        "lesson_key": "s1_b2_l1",
        "lesson_number": 1,
        "lesson_title": "Занятие 1. Логика консалтингового бизнеса и Time to Cash",
        "date_start": date(2026, 5, 26),
        "date_end": None,
        "date_text": "26.05.2026",
        "speaker": "Рахманов А.",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 20,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b2",
        "block_title": "Бизнес-консалтинг",
        "block_order": 2,
        "lesson_key": "s1_b2_l2",
        "lesson_number": 2,
        "lesson_title": "Занятие 2. Организационные модели консалтингового бизнеса",
        "date_start": date(2026, 6, 2),
        "date_end": None,
        "date_text": "02.06.2026",
        "speaker": "Берштейн Т. Рахманов А.",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 30,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b2",
        "block_title": "Бизнес-консалтинг",
        "block_order": 2,
        "lesson_key": "s1_b2_l3",
        "lesson_number": 3,
        "lesson_title": "Занятие 3. Практикум",
        "date_start": date(2026, 6, 9),
        "date_end": None,
        "date_text": "09.06.2026",
        "speaker": "Рахманов А.",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 40,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b2",
        "block_title": "Бизнес-консалтинг",
        "block_order": 2,
        "lesson_key": "s1_b2_l4",
        "lesson_number": 4,
        "lesson_title": "Занятие 4. Итоговая сборка блока",
        "date_start": date(2026, 6, 16),
        "date_end": None,
        "date_text": "16.06.2026",
        "speaker": "Рахманов А.",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 50,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b3",
        "block_title": "Стратегия",
        "block_order": 3,
        "lesson_key": "s1_b3_l1",
        "lesson_number": 1,
        "lesson_title": "Занятие 1. Стратегия как инструмент лидера",
        "date_start": date(2026, 6, 23),
        "date_end": None,
        "date_text": "23.06.2026",
        "speaker": "Семенов А.",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 60,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b3",
        "block_title": "Стратегия",
        "block_order": 3,
        "lesson_key": "s1_b3_l2",
        "lesson_number": 2,
        "lesson_title": "Занятие 2. Сценарное планирование",
        "date_start": date(2026, 6, 30),
        "date_end": None,
        "date_text": "30.06.2026",
        "speaker": "Ярослав Павлов",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 70,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b3",
        "block_title": "Стратегия",
        "block_order": 3,
        "lesson_key": "s1_b3_l3",
        "lesson_number": 3,
        "lesson_title": "Занятие 3. Разработка стратегии на примере компании ДАР",
        "date_start": date(2026, 7, 7),
        "date_end": None,
        "date_text": "07.07.2026",
        "speaker": "Елена Лашманова",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 80,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b3",
        "block_title": "Стратегия",
        "block_order": 3,
        "lesson_key": "s1_b3_l4",
        "lesson_number": 4,
        "lesson_title": "Занятие 4. Управленческий совет: защита стратегических проектов",
        "date_start": date(2026, 7, 14),
        "date_end": None,
        "date_text": "14.07.2026",
        "speaker": "Александр Семенов",
        "content_status": None,
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 90,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b4",
        "block_title": "Экономика и финансы",
        "block_order": 4,
        "lesson_key": "s1_b4_l1",
        "lesson_number": 1,
        "lesson_title": "Занятие 1. Экономика и финансы. Введение",
        "date_start": date(2026, 7, 21),
        "date_end": None,
        "date_text": "21.07.2026",
        "speaker": "М.А. Карлик",
        "content_status": "Актуализировано по плану блока Экономика и финансы от 20.07.2026",
        "material_format": "Финансово-экономические цели компании; процесс создания добавленной стоимости; управление ДЗ и КЗ.",
        "hr_moderator_role": None,
        "sort_order": 100,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b4",
        "block_title": "Экономика и финансы",
        "block_order": 4,
        "lesson_key": "s1_b4_l2",
        "lesson_number": 2,
        "lesson_title": "Занятие 2. Экономика: как заработать прибыль",
        "date_start": date(2026, 7, 28),
        "date_end": None,
        "date_text": "28.07.2026",
        "speaker": "С. Сафронов",
        "content_status": "Актуализировано по плану блока Экономика и финансы от 20.07.2026",
        "material_format": "Прибыль и связь с учётной политикой; золотая формула бизнеса; выручка от услуг и факторный анализ отклонений.",
        "hr_moderator_role": None,
        "sort_order": 110,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b4",
        "block_title": "Экономика и финансы",
        "block_order": 4,
        "lesson_key": "s1_b4_l3",
        "lesson_number": 3,
        "lesson_title": "Занятие 3. Отчёты и показатели ЭиФ в КОРУСе",
        "date_start": date(2026, 8, 4),
        "date_end": None,
        "date_text": "04.08.2026",
        "speaker": "Ю. Макарова",
        "content_status": "Актуализировано по плану блока Экономика и финансы от 20.07.2026",
        "material_format": "Структура отчётов PL и CF; фактические и плановые показатели; KPI: сравнение и динамика.",
        "hr_moderator_role": None,
        "sort_order": 120,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b4",
        "block_title": "Экономика и финансы",
        "block_order": 4,
        "lesson_key": "s1_b4_l4",
        "lesson_number": 4,
        "lesson_title": "Занятие 4. Групповая работа по итогам блока ЭиФ",
        "date_start": date(2026, 8, 11),
        "date_end": None,
        "date_text": "11.08.2026",
        "speaker": "Ю. Макарова, С. Сафронов",
        "content_status": "Актуализировано по плану блока Экономика и финансы от 20.07.2026",
        "material_format": "Онлайн-работа в группах по полученному заданию; представление результатов и обратная связь.",
        "hr_moderator_role": None,
        "sort_order": 130,
        "is_active": True,
    },
    {
        "season_key": "s1",
        "season_title": "Бизнес",
        "block_key": "s1_b5",
        "block_title": "Подведение итогов сезона",
        "block_order": 5,
        "lesson_key": "s1_b5_final",
        "lesson_number": None,
        "lesson_title": "Очная сессия в СПб",
        "date_start": date(2026, 8, 25),
        "date_end": None,
        "date_text": "25.08.2026",
        "speaker": None,
        "content_status": "Дата уточнена: 25.08.2026",
        "material_format": None,
        "hr_moderator_role": None,
        "sort_order": 140,
        "is_active": True,
    },
]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE message_feedback ADD COLUMN IF NOT EXISTS reason varchar(50)"))
        await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS lesson_key varchar(100)"))
        await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS lesson_date date"))
        await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '[]'::jsonb"))
        await conn.execute(text("ALTER TABLE program_media ADD COLUMN IF NOT EXISTS lesson_key varchar(100)"))
        await conn.execute(text("ALTER TABLE program_media ADD COLUMN IF NOT EXISTS lesson_date date"))
        await conn.execute(text("ALTER TABLE program_media ADD COLUMN IF NOT EXISTS stored_path varchar(1000)"))
        await conn.execute(text("ALTER TABLE program_media ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '[]'::jsonb"))
        await conn.execute(text("ALTER TABLE homeworks ADD COLUMN IF NOT EXISTS deadline_date date"))
        await conn.execute(text("ALTER TABLE homeworks ALTER COLUMN status SET DEFAULT 'active'"))
        await conn.execute(text("ALTER TABLE feedback_campaigns ADD COLUMN IF NOT EXISTS usefulness_question text"))
        await conn.execute(text("ALTER TABLE feedback_campaigns ADD COLUMN IF NOT EXISTS experts_question text"))
        await conn.execute(text("ALTER TABLE feedback_campaigns ADD COLUMN IF NOT EXISTS valuable_question text"))
        await conn.execute(text("ALTER TABLE feedback_campaigns ADD COLUMN IF NOT EXISTS improvement_question text"))
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS director_assignments (
                    id SERIAL PRIMARY KEY,
                    director_telegram_id BIGINT NOT NULL,
                    employee_telegram_id BIGINT NOT NULL,
                    note TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_director_assignment_pair UNIQUE (director_telegram_id, employee_telegram_id)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS director_reminder_logs (
                    id SERIAL PRIMARY KEY,
                    director_telegram_id BIGINT NOT NULL,
                    employee_telegram_id BIGINT,
                    employee_name VARCHAR(512) NOT NULL,
                    template_key VARCHAR(100) NOT NULL DEFAULT 'director_attention_reminder',
                    reminder_text TEXT NOT NULL,
                    reminder_hash VARCHAR(64) NOT NULL,
                    delivery_mode VARCHAR(50) NOT NULL DEFAULT 'admin_test',
                    status VARCHAR(50) NOT NULL DEFAULT 'sent',
                    sent_recipient_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    failed_recipient_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_lesson_key ON documents(lesson_key)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_lesson_date ON documents(lesson_date)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_program_media_lesson_key ON program_media(lesson_key)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_program_media_lesson_date ON program_media(lesson_date)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_homeworks_deadline_date ON homeworks(deadline_date)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_director_assignments_director ON director_assignments(director_telegram_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_director_assignments_employee ON director_assignments(employee_telegram_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_director_assignments_active_director ON director_assignments(is_active, director_telegram_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_director_reminder_logs_director_created ON director_reminder_logs(director_telegram_id, created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_director_reminder_logs_employee_created ON director_reminder_logs(director_telegram_id, employee_name, created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_director_reminder_logs_hash_created ON director_reminder_logs(director_telegram_id, employee_name, reminder_hash, created_at)"))
        await conn.execute(
            text(
                """
                INSERT INTO program_lessons (
                    season_key,
                    season_title,
                    block_key,
                    block_title,
                    block_order,
                    lesson_key,
                    lesson_number,
                    lesson_title,
                    date_start,
                    date_end,
                    date_text,
                    speaker,
                    content_status,
                    material_format,
                    hr_moderator_role,
                    sort_order,
                    is_active
                )
                VALUES (
                    :season_key,
                    :season_title,
                    :block_key,
                    :block_title,
                    :block_order,
                    :lesson_key,
                    :lesson_number,
                    :lesson_title,
                    :date_start,
                    :date_end,
                    :date_text,
                    :speaker,
                    :content_status,
                    :material_format,
                    :hr_moderator_role,
                    :sort_order,
                    :is_active
                )
                ON CONFLICT (lesson_key) DO UPDATE SET
                    season_title = EXCLUDED.season_title,
                    block_key = EXCLUDED.block_key,
                    block_title = EXCLUDED.block_title,
                    block_order = EXCLUDED.block_order,
                    lesson_number = EXCLUDED.lesson_number,
                    lesson_title = EXCLUDED.lesson_title,
                    date_start = EXCLUDED.date_start,
                    date_end = EXCLUDED.date_end,
                    date_text = EXCLUDED.date_text,
                    speaker = EXCLUDED.speaker,
                    content_status = EXCLUDED.content_status,
                    material_format = EXCLUDED.material_format,
                    hr_moderator_role = EXCLUDED.hr_moderator_role,
                    sort_order = EXCLUDED.sort_order,
                    is_active = EXCLUDED.is_active
                """
            ),
            DEFAULT_PROGRAM_LESSONS,
        )
        await conn.execute(
            text(
                """
                UPDATE program_lessons
                SET lesson_title = CASE lesson_key
                    WHEN 's1_b4_l1' THEN 'Занятие 1. Экономика и финансы. Введение'
                    WHEN 's1_b4_l2' THEN 'Занятие 2. Экономика: как заработать прибыль'
                    WHEN 's1_b4_l3' THEN 'Занятие 3. Отчёты и показатели ЭиФ в КОРУСе'
                    WHEN 's1_b4_l4' THEN 'Занятие 4. Групповая работа по итогам блока ЭиФ'
                    ELSE lesson_title
                END,
                speaker = CASE lesson_key
                    WHEN 's1_b4_l1' THEN 'М.А. Карлик'
                    WHEN 's1_b4_l2' THEN 'С. Сафронов'
                    WHEN 's1_b4_l3' THEN 'Ю. Макарова'
                    WHEN 's1_b4_l4' THEN 'Ю. Макарова, С. Сафронов'
                    ELSE speaker
                END,
                material_format = CASE lesson_key
                    WHEN 's1_b4_l1' THEN 'Финансово-экономические цели компании; процесс создания добавленной стоимости; управление ДЗ и КЗ.'
                    WHEN 's1_b4_l2' THEN 'Прибыль и связь с учётной политикой; золотая формула бизнеса; выручка от услуг и факторный анализ отклонений.'
                    WHEN 's1_b4_l3' THEN 'Структура отчётов PL и CF; фактические и плановые показатели; KPI: сравнение и динамика.'
                    WHEN 's1_b4_l4' THEN 'Онлайн-работа в группах по полученному заданию; представление результатов и обратная связь.'
                    ELSE material_format
                END,
                content_status = 'Актуализировано по плану блока Экономика и финансы от 20.07.2026',
                updated_at = NOW()
                WHERE lesson_key IN ('s1_b4_l1', 's1_b4_l2', 's1_b4_l3', 's1_b4_l4')
                """
            )
        )
