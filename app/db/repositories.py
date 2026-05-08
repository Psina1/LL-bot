from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BotText,
    Chunk,
    Document,
    DocumentStatusEnum,
    ErrorLog,
    Message,
    MessageFeedback,
    RoleEnum,
    User,
    UserFile,
    VisibilityEnum,
)


@dataclass(slots=True)
class ChunkMatch:
    chunk_id: int
    chunk_text: str
    score: float
    metadata: dict[str, Any]
    document_id: int
    document_title: str
    original_filename: str


class UserRepository:
    @staticmethod
    async def upsert_telegram_user(
        session: AsyncSession,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        is_admin: bool,
    ) -> User:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        full_name = " ".join(part for part in [first_name, last_name] if part).strip() or None
        role = RoleEnum.admin if is_admin else RoleEnum.user

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                role=role,
            )
            session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.full_name = full_name
            user.role = role

        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_project_context(session: AsyncSession, user_id: int, project_context: str) -> None:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return
        user.project_context = project_context.strip()
        await session.commit()


class MessageRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        mode: str,
        question: str,
        answer: str,
        sources: list[dict[str, Any]] | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            user_id=user_id,
            mode=mode,
            question=question,
            answer=answer,
            sources=sources or [],
            token_usage=token_usage,
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        return message

    @staticmethod
    async def count_last_minute(session: AsyncSession, user_id: int) -> int:
        since = datetime.now(timezone.utc) - timedelta(minutes=1)
        stmt = select(func.count(Message.id)).where(and_(Message.user_id == user_id, Message.created_at >= since))
        result = await session.execute(stmt)
        return int(result.scalar() or 0)


class MessageFeedbackRepository:
    @staticmethod
    async def upsert(session: AsyncSession, message_id: int, user_id: int, value: str, reason: str | None = None) -> None:
        stmt = pg_insert(MessageFeedback).values(message_id=message_id, user_id=user_id, value=value, reason=reason)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_message_feedback_message_user",
            set_={"value": value, "reason": reason},
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def totals(session: AsyncSession) -> dict[str, int]:
        result = await session.execute(select(MessageFeedback.value, func.count(MessageFeedback.id)).group_by(MessageFeedback.value))
        totals = {"yes": 0, "no": 0}
        for value, count in result.all():
            totals[str(value)] = int(count or 0)
        return totals

    @staticmethod
    async def reason_totals(session: AsyncSession) -> dict[str, int]:
        stmt = (
            select(MessageFeedback.reason, func.count(MessageFeedback.id))
            .where(MessageFeedback.reason.is_not(None))
            .group_by(MessageFeedback.reason)
        )
        result = await session.execute(stmt)
        return {str(reason): int(count or 0) for reason, count in result.all()}


class BotTextRepository:
    @staticmethod
    async def get(session: AsyncSession, key: str) -> BotText | None:
        result = await session.execute(select(BotText).where(BotText.key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_value(session: AsyncSession, key: str, default: str) -> str:
        text = await BotTextRepository.get(session, key)
        return text.value if text is not None else default

    @staticmethod
    async def upsert(session: AsyncSession, key: str, value: str, updated_by_user_id: int | None = None) -> None:
        stmt = pg_insert(BotText).values(key=key, value=value.strip(), updated_by_user_id=updated_by_user_id)
        stmt = stmt.on_conflict_do_update(
            index_elements=[BotText.key],
            set_={"value": value.strip(), "updated_by_user_id": updated_by_user_id, "updated_at": func.now()},
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def list_all(session: AsyncSession) -> list[BotText]:
        result = await session.execute(select(BotText).order_by(BotText.key))
        return list(result.scalars().all())


class ErrorRepository:
    @staticmethod
    async def create(session: AsyncSession, context: str, error_text: str, user_id: int | None = None) -> None:
        session.add(ErrorLog(user_id=user_id, context=context, error_text=error_text[:10000]))
        await session.commit()

    @staticmethod
    async def latest(session: AsyncSession, limit: int = 5) -> list[ErrorLog]:
        result = await session.execute(select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(limit))
        return list(result.scalars().all())


class DocumentRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        title: str,
        original_filename: str,
        stored_path: str,
        file_type: str,
        visibility: VisibilityEnum,
        owner_user_id: int | None,
        module_number: int | None = None,
        module_title: str | None = None,
        material_type: str | None = None,
        status: DocumentStatusEnum = DocumentStatusEnum.uploaded,
    ) -> Document:
        document = Document(
            title=title,
            original_filename=original_filename,
            stored_path=stored_path,
            file_type=file_type,
            visibility=visibility,
            owner_user_id=owner_user_id,
            module_number=module_number,
            module_title=module_title,
            material_type=material_type,
            status=status,
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document

    @staticmethod
    async def get_by_id(session: AsyncSession, document_id: int) -> Document | None:
        result = await session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def set_status(
        session: AsyncSession,
        document_id: int,
        status: DocumentStatusEnum,
        error_message: str | None = None,
    ) -> None:
        document = await DocumentRepository.get_by_id(session, document_id)
        if document is None:
            return
        document.status = status
        document.error_message = error_message
        await session.commit()

    @staticmethod
    async def list_materials(session: AsyncSession, limit: int = 50) -> list[Document]:
        result = await session.execute(select(Document).order_by(Document.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    @staticmethod
    async def list_homework_materials(session: AsyncSession) -> list[Document]:
        stmt = select(Document).where(
            and_(
                Document.status == DocumentStatusEnum.ready,
                or_(
                    Document.material_type == "homework",
                    func.lower(Document.title).like("%домаш%"),
                    func.lower(Document.original_filename).like("%homework%"),
                    func.lower(Document.original_filename).like("%домаш%"),
                ),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_modules(session: AsyncSession) -> list[tuple[int, str | None, int]]:
        stmt = (
            select(Document.module_number, Document.module_title, func.count(Document.id))
            .where(Document.module_number.is_not(None))
            .group_by(Document.module_number, Document.module_title)
            .order_by(Document.module_number)
        )
        result = await session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    @staticmethod
    async def reindex_candidates(session: AsyncSession) -> list[Document]:
        stmt = select(Document).where(Document.status.in_([DocumentStatusEnum.ready, DocumentStatusEnum.error]))
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ChunkRepository:
    @staticmethod
    async def replace_for_document(
        session: AsyncSession,
        document_id: int,
        chunks_payload: list[dict[str, Any]],
    ) -> int:
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        chunks = [
            Chunk(
                document_id=document_id,
                chunk_index=item["chunk_index"],
                chunk_text=item["chunk_text"],
                embedding=item["embedding"],
                chunk_metadata=item["metadata"],
            )
            for item in chunks_payload
        ]
        session.add_all(chunks)
        await session.commit()
        return len(chunks)

    @staticmethod
    async def search_relevant(
        session: AsyncSession,
        question_embedding: list[float],
        user_id: int,
        top_k: int,
    ) -> list[ChunkMatch]:
        similarity = Chunk.embedding.cosine_distance(question_embedding)
        stmt = (
            select(Chunk, Document, similarity.label("distance"))
            .join(Document, Document.id == Chunk.document_id)
            .where(
                and_(
                    Document.status == DocumentStatusEnum.ready,
                    or_(
                        Document.visibility == VisibilityEnum.global_,
                        and_(Document.visibility == VisibilityEnum.user, Document.owner_user_id == user_id),
                    ),
                )
            )
            .order_by(similarity.asc())
            .limit(top_k)
        )
        result = await session.execute(stmt)
        matches: list[ChunkMatch] = []
        for chunk, document, distance in result.all():
            score = 1 - float(distance)
            matches.append(
                ChunkMatch(
                    chunk_id=chunk.id,
                    chunk_text=chunk.chunk_text,
                    score=score,
                    metadata=chunk.chunk_metadata or {},
                    document_id=document.id,
                    document_title=document.title,
                    original_filename=document.original_filename,
                )
            )
        return matches

    @staticmethod
    async def latest_user_chunks(
        session: AsyncSession,
        user_id: int,
        limit: int,
    ) -> list[ChunkMatch]:
        stmt = (
            select(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                and_(
                    Document.status == DocumentStatusEnum.ready,
                    Document.visibility == VisibilityEnum.user,
                    Document.owner_user_id == user_id,
                )
            )
            .order_by(Document.created_at.desc(), Chunk.chunk_index.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        matches: list[ChunkMatch] = []
        for chunk, document in result.all():
            matches.append(
                ChunkMatch(
                    chunk_id=chunk.id,
                    chunk_text=chunk.chunk_text,
                    score=0.0,
                    metadata=chunk.chunk_metadata or {},
                    document_id=document.id,
                    document_title=document.title,
                    original_filename=document.original_filename,
                )
            )
        return matches

    @staticmethod
    async def count(session: AsyncSession) -> int:
        result = await session.execute(select(func.count(Chunk.id)))
        return int(result.scalar() or 0)


class UserFileRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        telegram_file_id: str,
        document_id: int,
        original_filename: str,
    ) -> UserFile:
        user_file = UserFile(
            user_id=user_id,
            telegram_file_id=telegram_file_id,
            document_id=document_id,
            original_filename=original_filename,
        )
        session.add(user_file)
        await session.commit()
        await session.refresh(user_file)
        return user_file


class StatsRepository:
    @staticmethod
    async def totals(session: AsyncSession) -> dict[str, int]:
        users_count = int((await session.execute(select(func.count(User.id)))).scalar() or 0)
        documents_count = int((await session.execute(select(func.count(Document.id)))).scalar() or 0)
        chunks_count = int((await session.execute(select(func.count(Chunk.id)))).scalar() or 0)
        messages_count = int((await session.execute(select(func.count(Message.id)))).scalar() or 0)
        return {
            "users": users_count,
            "documents": documents_count,
            "chunks": chunks_count,
            "messages": messages_count,
        }
