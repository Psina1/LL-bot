from __future__ import annotations

from sqlalchemy import text

from app.db.models import Base
from app.db.session import engine


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
        await conn.execute(text("ALTER TABLE program_media ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '[]'::jsonb"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_lesson_key ON documents(lesson_key)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_lesson_date ON documents(lesson_date)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_program_media_lesson_key ON program_media(lesson_key)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_program_media_lesson_date ON program_media(lesson_date)"))
