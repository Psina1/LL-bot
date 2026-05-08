from __future__ import annotations

from sqlalchemy import text

from app.db.models import Base
from app.db.session import engine


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE message_feedback ADD COLUMN IF NOT EXISTS reason varchar(50)"))
