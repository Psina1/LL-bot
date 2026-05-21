from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AllowedUser,
    AppSetting,
    BotText,
    Chunk,
    Document,
    DocumentStatusEnum,
    ErrorLog,
    Homework,
    Message,
    MessageFeedback,
    NotificationDelivery,
    ProgramLesson,
    ProgramMedia,
    RoleEnum,
    User,
    UserEvent,
    UserFile,
    UserNotificationSetting,
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
    async def list_recent(session: AsyncSession, limit: int = 20) -> list[User]:
        result = await session.execute(select(User).order_by(User.created_at.desc()).limit(limit))
        return list(result.scalars().all())

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


@dataclass(slots=True)
class EventStat:
    event_type: str
    event_name: str
    count: int


@dataclass(slots=True)
class UserActivityRow:
    telegram_id: int
    username: str | None
    full_name: str | None
    role: str
    created_at: datetime
    last_event_at: datetime | None
    messages_count: int
    button_events_count: int


class UserEventRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        telegram_id: int,
        username: str | None,
        event_type: str,
        event_name: str,
        user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> UserEvent:
        event = UserEvent(
            user_id=user_id,
            telegram_id=telegram_id,
            username=username,
            event_type=event_type,
            event_name=event_name[:255],
            payload=payload or {},
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    @staticmethod
    async def top_events(
        session: AsyncSession,
        event_types: list[str],
        since: datetime | None = None,
        limit: int = 10,
        exclude_telegram_ids: list[int] | None = None,
    ) -> list[EventStat]:
        filters = [UserEvent.event_type.in_(event_types)]
        if since is not None:
            filters.append(UserEvent.created_at >= since)
        if exclude_telegram_ids:
            filters.append(~UserEvent.telegram_id.in_(exclude_telegram_ids))

        stmt = (
            select(UserEvent.event_type, UserEvent.event_name, func.count(UserEvent.id).label("count"))
            .where(and_(*filters))
            .group_by(UserEvent.event_type, UserEvent.event_name)
            .order_by(func.count(UserEvent.id).desc(), UserEvent.event_name.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [EventStat(event_type=row[0], event_name=row[1], count=int(row[2] or 0)) for row in result.all()]

    @staticmethod
    async def event_counts_by_name(
        session: AsyncSession,
        event_names: list[str],
        since: datetime | None = None,
        exclude_telegram_ids: list[int] | None = None,
    ) -> dict[str, int]:
        if not event_names:
            return {}
        filters = [UserEvent.event_name.in_(event_names)]
        if since is not None:
            filters.append(UserEvent.created_at >= since)
        if exclude_telegram_ids:
            filters.append(~UserEvent.telegram_id.in_(exclude_telegram_ids))

        stmt = (
            select(UserEvent.event_name, func.count(UserEvent.id))
            .where(and_(*filters))
            .group_by(UserEvent.event_name)
        )
        result = await session.execute(stmt)
        return {str(name): int(count or 0) for name, count in result.all()}

    @staticmethod
    async def active_users_since(
        session: AsyncSession,
        since: datetime,
        exclude_telegram_ids: list[int] | None = None,
    ) -> int:
        filters = [UserEvent.created_at >= since]
        if exclude_telegram_ids:
            filters.append(~UserEvent.telegram_id.in_(exclude_telegram_ids))
        result = await session.execute(
            select(func.count(func.distinct(UserEvent.telegram_id))).where(and_(*filters))
        )
        return int(result.scalar() or 0)

    @staticmethod
    async def count_events_since(
        session: AsyncSession,
        since: datetime,
        event_types: list[str] | None = None,
        exclude_telegram_ids: list[int] | None = None,
    ) -> int:
        filters = [UserEvent.created_at >= since]
        if event_types:
            filters.append(UserEvent.event_type.in_(event_types))
        if exclude_telegram_ids:
            filters.append(~UserEvent.telegram_id.in_(exclude_telegram_ids))
        result = await session.execute(select(func.count(UserEvent.id)).where(and_(*filters)))
        return int(result.scalar() or 0)

    @staticmethod
    async def user_activity_rows(session: AsyncSession, limit: int = 500) -> list[UserActivityRow]:
        last_event_subquery = (
            select(UserEvent.telegram_id, func.max(UserEvent.created_at).label("last_event_at"))
            .group_by(UserEvent.telegram_id)
            .subquery()
        )
        button_count_subquery = (
            select(UserEvent.telegram_id, func.count(UserEvent.id).label("button_events_count"))
            .where(UserEvent.event_type.in_(["reply_button", "inline_button"]))
            .group_by(UserEvent.telegram_id)
            .subquery()
        )
        message_count_subquery = (
            select(Message.user_id, func.count(Message.id).label("messages_count"))
            .group_by(Message.user_id)
            .subquery()
        )
        stmt = (
            select(
                User.telegram_id,
                User.username,
                User.full_name,
                User.role,
                User.created_at,
                last_event_subquery.c.last_event_at,
                func.coalesce(message_count_subquery.c.messages_count, 0),
                func.coalesce(button_count_subquery.c.button_events_count, 0),
            )
            .outerjoin(last_event_subquery, last_event_subquery.c.telegram_id == User.telegram_id)
            .outerjoin(message_count_subquery, message_count_subquery.c.user_id == User.id)
            .outerjoin(button_count_subquery, button_count_subquery.c.telegram_id == User.telegram_id)
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows: list[UserActivityRow] = []
        for row in result.all():
            role_value = row[3].value if hasattr(row[3], "value") else str(row[3])
            rows.append(
                UserActivityRow(
                    telegram_id=int(row[0]),
                    username=row[1],
                    full_name=row[2],
                    role=role_value,
                    created_at=row[4],
                    last_event_at=row[5],
                    messages_count=int(row[6] or 0),
                    button_events_count=int(row[7] or 0),
                )
            )
        return rows


@dataclass(slots=True)
class NotificationRecipient:
    user_id: int
    telegram_id: int
    notification_time: str


class UserNotificationSettingRepository:
    @staticmethod
    async def get_for_user(session: AsyncSession, user_id: int) -> UserNotificationSetting | None:
        result = await session.execute(
            select(UserNotificationSetting).where(UserNotificationSetting.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_time(session: AsyncSession, user_id: int, notification_time: str) -> None:
        stmt = pg_insert(UserNotificationSetting).values(
            user_id=user_id,
            notification_time=notification_time,
            enabled=True,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserNotificationSetting.user_id],
            set_={"notification_time": notification_time, "enabled": True, "updated_at": func.now()},
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def disable(session: AsyncSession, user_id: int) -> None:
        setting = await UserNotificationSettingRepository.get_for_user(session, user_id)
        if setting is None:
            return
        setting.enabled = False
        await session.commit()

    @staticmethod
    async def list_due_recipients(session: AsyncSession, notification_time: str) -> list[NotificationRecipient]:
        stmt = (
            select(User.id, User.telegram_id, UserNotificationSetting.notification_time)
            .join(UserNotificationSetting, UserNotificationSetting.user_id == User.id)
            .where(
                and_(
                    UserNotificationSetting.enabled.is_(True),
                    UserNotificationSetting.notification_time == notification_time,
                )
            )
        )
        result = await session.execute(stmt)
        return [
            NotificationRecipient(user_id=user_id, telegram_id=telegram_id, notification_time=time_value)
            for user_id, telegram_id, time_value in result.all()
        ]


class NotificationDeliveryRepository:
    @staticmethod
    async def was_processed(
        session: AsyncSession,
        user_id: int,
        notification_key: str,
        delivery_date,
        scheduled_time: str,
    ) -> bool:
        stmt = select(func.count(NotificationDelivery.id)).where(
            and_(
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.notification_key == notification_key,
                NotificationDelivery.delivery_date == delivery_date,
                NotificationDelivery.scheduled_time == scheduled_time,
            )
        )
        result = await session.execute(stmt)
        return int(result.scalar() or 0) > 0

    @staticmethod
    async def mark(
        session: AsyncSession,
        user_id: int,
        notification_key: str,
        delivery_date,
        scheduled_time: str,
        status: str,
        error_text: str | None = None,
    ) -> None:
        stmt = pg_insert(NotificationDelivery).values(
            user_id=user_id,
            notification_key=notification_key,
            delivery_date=delivery_date,
            scheduled_time=scheduled_time,
            status=status,
            error_text=error_text[:10000] if error_text else None,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_notification_delivery_user_key_date_time",
            set_={"status": status, "error_text": error_text[:10000] if error_text else None},
        )
        await session.execute(stmt)
        await session.commit()


def normalize_telegram_username(username: str | None) -> str | None:
    if not username:
        return None
    normalized = username.strip().lstrip("@").lower()
    return normalized or None


class AllowedUserRepository:
    @staticmethod
    async def is_allowed(
        session: AsyncSession,
        telegram_id: int,
        username: str | None,
        admin_ids: set[int],
    ) -> bool:
        if telegram_id in admin_ids:
            return True

        username_normalized = normalize_telegram_username(username)
        filters = [AllowedUser.telegram_id == telegram_id]
        if username_normalized:
            filters.append(AllowedUser.username_normalized == username_normalized)

        result = await session.execute(
            select(AllowedUser.id).where(and_(AllowedUser.is_active.is_(True), or_(*filters))).limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def upsert(
        session: AsyncSession,
        full_name: str | None,
        telegram_id: int | None = None,
        username: str | None = None,
        phone: str | None = None,
        note: str | None = None,
        is_active: bool = True,
    ) -> AllowedUser:
        username_normalized = normalize_telegram_username(username)
        values = {
            "telegram_id": telegram_id,
            "username": username.strip() if username else None,
            "username_normalized": username_normalized,
            "full_name": full_name.strip() if full_name else None,
            "phone": phone.strip() if phone else None,
            "note": note.strip() if note else None,
            "is_active": is_active,
        }

        lookup_filter = None
        if telegram_id is not None:
            lookup_filter = AllowedUser.telegram_id == telegram_id
        elif username_normalized:
            lookup_filter = AllowedUser.username_normalized == username_normalized

        allowed_user = None
        if lookup_filter is not None:
            result = await session.execute(select(AllowedUser).where(lookup_filter))
            allowed_user = result.scalar_one_or_none()

        if allowed_user is None:
            allowed_user = AllowedUser(**values)
            session.add(allowed_user)
        else:
            for key, value in values.items():
                setattr(allowed_user, key, value)

        await session.commit()
        await session.refresh(allowed_user)
        return allowed_user

    @staticmethod
    async def count_active(session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count(AllowedUser.id)).where(AllowedUser.is_active.is_(True))
        )
        return int(result.scalar() or 0)


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


class AppSettingRepository:
    @staticmethod
    async def get_value(session: AsyncSession, key: str) -> str | None:
        result = await session.execute(select(AppSetting.value).where(AppSetting.key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        key: str,
        value: str,
        updated_by_user_id: int | None = None,
    ) -> None:
        stmt = pg_insert(AppSetting).values(key=key, value=value, updated_by_user_id=updated_by_user_id)
        stmt = stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": value, "updated_by_user_id": updated_by_user_id, "updated_at": func.now()},
        )
        await session.execute(stmt)
        await session.commit()


class ErrorRepository:
    @staticmethod
    async def create(session: AsyncSession, context: str, error_text: str, user_id: int | None = None) -> None:
        session.add(ErrorLog(user_id=user_id, context=context, error_text=error_text[:10000]))
        await session.commit()

    @staticmethod
    async def latest(session: AsyncSession, limit: int = 5) -> list[ErrorLog]:
        result = await session.execute(select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(limit))
        return list(result.scalars().all())


class ProgramLessonRepository:
    @staticmethod
    async def list_active(session: AsyncSession) -> list[ProgramLesson]:
        result = await session.execute(
            select(ProgramLesson)
            .where(ProgramLesson.is_active.is_(True))
            .order_by(ProgramLesson.sort_order.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_seasons(session: AsyncSession) -> list[tuple[str, str]]:
        result = await session.execute(
            select(ProgramLesson.season_key, ProgramLesson.season_title)
            .where(ProgramLesson.is_active.is_(True))
            .group_by(ProgramLesson.season_key, ProgramLesson.season_title)
            .order_by(func.min(ProgramLesson.sort_order).asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    @staticmethod
    async def list_blocks(session: AsyncSession, season_key: str) -> list[tuple[str, str, int]]:
        result = await session.execute(
            select(ProgramLesson.block_key, ProgramLesson.block_title, ProgramLesson.block_order)
            .where(and_(ProgramLesson.is_active.is_(True), ProgramLesson.season_key == season_key))
            .group_by(ProgramLesson.block_key, ProgramLesson.block_title, ProgramLesson.block_order)
            .order_by(ProgramLesson.block_order.asc())
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    @staticmethod
    async def list_by_block(session: AsyncSession, block_key: str) -> list[ProgramLesson]:
        result = await session.execute(
            select(ProgramLesson)
            .where(and_(ProgramLesson.is_active.is_(True), ProgramLesson.block_key == block_key))
            .order_by(ProgramLesson.sort_order.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_key(session: AsyncSession, lesson_key: str) -> ProgramLesson | None:
        result = await session.execute(select(ProgramLesson).where(ProgramLesson.lesson_key == lesson_key))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_date(session: AsyncSession, lesson_date) -> ProgramLesson | None:
        result = await session.execute(
            select(ProgramLesson)
            .where(
                and_(
                    ProgramLesson.is_active.is_(True),
                    or_(
                        ProgramLesson.date_start == lesson_date,
                        and_(
                            ProgramLesson.date_start <= lesson_date,
                            ProgramLesson.date_end.is_not(None),
                            ProgramLesson.date_end >= lesson_date,
                        ),
                    ),
                )
            )
            .order_by(ProgramLesson.sort_order.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_start_date(session: AsyncSession, lesson_date, limit: int = 50) -> list[ProgramLesson]:
        result = await session.execute(
            select(ProgramLesson)
            .where(and_(ProgramLesson.is_active.is_(True), ProgramLesson.date_start == lesson_date))
            .order_by(ProgramLesson.sort_order.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_next_after(
        session: AsyncSession,
        lesson_key: str | None = None,
        lesson_date=None,
    ) -> ProgramLesson | None:
        if lesson_key:
            current = await ProgramLessonRepository.get_by_key(session, lesson_key)
            if current is not None:
                result = await session.execute(
                    select(ProgramLesson)
                    .where(
                        and_(
                            ProgramLesson.is_active.is_(True),
                            ProgramLesson.date_start.is_not(None),
                            ProgramLesson.sort_order > current.sort_order,
                        )
                    )
                    .order_by(ProgramLesson.sort_order.asc())
                    .limit(1)
                )
                return result.scalar_one_or_none()

        if lesson_date:
            result = await session.execute(
                select(ProgramLesson)
                .where(
                    and_(
                        ProgramLesson.is_active.is_(True),
                        ProgramLesson.date_start.is_not(None),
                        ProgramLesson.date_start > lesson_date,
                    )
                )
                .order_by(ProgramLesson.date_start.asc(), ProgramLesson.sort_order.asc())
                .limit(1)
            )
            return result.scalar_one_or_none()

        return None


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
        lesson_key: str | None = None,
        lesson_date=None,
        material_type: str | None = None,
        tags: list[str] | None = None,
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
            lesson_key=lesson_key,
            lesson_date=lesson_date,
            material_type=material_type,
            tags=tags or [],
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
    async def list_visible_materials(session: AsyncSession, user_id: int, limit: int = 50) -> list[Document]:
        stmt = (
            select(Document)
            .where(
                and_(
                    Document.status == DocumentStatusEnum.ready,
                    or_(
                        Document.visibility == VisibilityEnum.global_,
                        and_(Document.visibility == VisibilityEnum.user, Document.owner_user_id == user_id),
                    ),
                )
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_visible_by_lesson(
        session: AsyncSession,
        user_id: int,
        lesson_key: str | None = None,
        lesson_date=None,
        limit: int = 50,
    ) -> list[Document]:
        if lesson_key and lesson_date:
            lesson_filter = and_(Document.lesson_key == lesson_key, Document.lesson_date == lesson_date)
        elif lesson_key:
            lesson_filter = Document.lesson_key == lesson_key
        elif lesson_date:
            lesson_filter = Document.lesson_date == lesson_date
        else:
            return []

        stmt = (
            select(Document)
            .where(
                and_(
                    Document.status == DocumentStatusEnum.ready,
                    lesson_filter,
                    or_(
                        Document.visibility == VisibilityEnum.global_,
                        and_(Document.visibility == VisibilityEnum.user, Document.owner_user_id == user_id),
                    ),
                )
            )
            .order_by(Document.module_number.asc().nulls_last(), Document.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
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
    async def search_relevant_by_lesson(
        session: AsyncSession,
        question_embedding: list[float],
        user_id: int,
        top_k: int,
        lesson_key: str | None = None,
        lesson_date: Any | None = None,
        document_ids: list[int] | None = None,
    ) -> list[ChunkMatch]:
        scope_filters = []
        if document_ids:
            scope_filters.append(Document.id.in_(document_ids))
        if lesson_key:
            scope_filters.append(Document.lesson_key == lesson_key)
        if lesson_date:
            scope_filters.append(Document.lesson_date == lesson_date)

        if not scope_filters:
            return await ChunkRepository.search_relevant(
                session=session,
                question_embedding=question_embedding,
                user_id=user_id,
                top_k=top_k,
            )

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
                    or_(*scope_filters),
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
    async def search_relevant_in_document(
        session: AsyncSession,
        question_embedding: list[float],
        user_id: int,
        document_id: int,
        top_k: int,
    ) -> list[ChunkMatch]:
        similarity = Chunk.embedding.cosine_distance(question_embedding)
        stmt = (
            select(Chunk, Document, similarity.label("distance"))
            .join(Document, Document.id == Chunk.document_id)
            .where(
                and_(
                    Document.id == document_id,
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


class HomeworkRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        title: str,
        description: str | None = None,
        document_id: int | None = None,
        moodle_url: str | None = None,
        module_number: int | None = None,
        module_title: str | None = None,
        lesson_key: str | None = None,
        lesson_date=None,
        deadline_date=None,
        created_by_user_id: int | None = None,
        status: str = "active",
    ) -> Homework:
        homework = Homework(
            title=title,
            description=description,
            document_id=document_id,
            moodle_url=moodle_url,
            module_number=module_number,
            module_title=module_title,
            lesson_key=lesson_key,
            lesson_date=lesson_date,
            deadline_date=deadline_date,
            created_by_user_id=created_by_user_id,
            status=status,
        )
        session.add(homework)
        await session.commit()
        await session.refresh(homework)
        return homework

    @staticmethod
    async def get_by_id(session: AsyncSession, homework_id: int) -> Homework | None:
        result = await session.execute(select(Homework).where(Homework.id == homework_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_active(session: AsyncSession, limit: int = 50) -> list[Homework]:
        stmt = (
            select(Homework)
            .where(Homework.status == "active")
            .order_by(
                Homework.deadline_date.asc().nulls_last(),
                Homework.lesson_date.asc().nulls_last(),
                Homework.module_number.asc().nulls_last(),
                Homework.id.asc(),
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_by_lesson(
        session: AsyncSession,
        lesson_key: str | None = None,
        lesson_date=None,
        limit: int = 20,
    ) -> list[Homework]:
        if lesson_key and lesson_date:
            lesson_filter = and_(Homework.lesson_key == lesson_key, Homework.lesson_date == lesson_date)
        elif lesson_key:
            lesson_filter = Homework.lesson_key == lesson_key
        elif lesson_date:
            lesson_filter = Homework.lesson_date == lesson_date
        else:
            return []

        stmt = (
            select(Homework)
            .where(and_(Homework.status == "active", lesson_filter))
            .order_by(
                Homework.deadline_date.asc().nulls_last(),
                Homework.lesson_date.asc().nulls_last(),
                Homework.module_number.asc().nulls_last(),
                Homework.id.asc(),
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_by_deadline(session: AsyncSession, deadline_date, limit: int = 50) -> list[Homework]:
        stmt = (
            select(Homework)
            .where(and_(Homework.status == "active", Homework.deadline_date == deadline_date))
            .order_by(Homework.lesson_date.asc().nulls_last(), Homework.module_number.asc().nulls_last(), Homework.id.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ProgramMediaRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        title: str,
        media_type: str,
        telegram_file_id: str,
        telegram_kind: str,
        created_by_user_id: int | None,
        telegram_file_unique_id: str | None = None,
        original_filename: str | None = None,
        file_size: int | None = None,
        mime_type: str | None = None,
        module_number: int | None = None,
        module_title: str | None = None,
        lesson_key: str | None = None,
        lesson_date=None,
        tags: list[str] | None = None,
    ) -> ProgramMedia:
        media = ProgramMedia(
            title=title,
            media_type=media_type,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            telegram_kind=telegram_kind,
            original_filename=original_filename,
            file_size=file_size,
            mime_type=mime_type,
            module_number=module_number,
            module_title=module_title,
            lesson_key=lesson_key,
            lesson_date=lesson_date,
            tags=tags or [],
            created_by_user_id=created_by_user_id,
        )
        session.add(media)
        await session.commit()
        await session.refresh(media)
        return media

    @staticmethod
    async def list_by_type(session: AsyncSession, media_type: str, limit: int = 20) -> list[ProgramMedia]:
        stmt = (
            select(ProgramMedia)
            .where(ProgramMedia.media_type == media_type)
            .order_by(ProgramMedia.module_number.asc().nulls_last(), ProgramMedia.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def latest_by_type(session: AsyncSession, media_type: str) -> ProgramMedia | None:
        result = await session.execute(
            select(ProgramMedia)
            .where(ProgramMedia.media_type == media_type)
            .order_by(ProgramMedia.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, media_id: int) -> ProgramMedia | None:
        result = await session.execute(select(ProgramMedia).where(ProgramMedia.id == media_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_lesson(
        session: AsyncSession,
        lesson_key: str | None = None,
        lesson_date=None,
        limit: int = 20,
    ) -> list[ProgramMedia]:
        if lesson_key and lesson_date:
            lesson_filter = and_(ProgramMedia.lesson_key == lesson_key, ProgramMedia.lesson_date == lesson_date)
        elif lesson_key:
            lesson_filter = ProgramMedia.lesson_key == lesson_key
        elif lesson_date:
            lesson_filter = ProgramMedia.lesson_date == lesson_date
        else:
            return []

        stmt = (
            select(ProgramMedia)
            .where(lesson_filter)
            .order_by(ProgramMedia.media_type.asc(), ProgramMedia.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_latest(session: AsyncSession, limit: int = 50) -> list[ProgramMedia]:
        result = await session.execute(select(ProgramMedia).order_by(ProgramMedia.created_at.desc()).limit(limit))
        return list(result.scalars().all())


class StatsRepository:
    @staticmethod
    async def totals(session: AsyncSession) -> dict[str, int]:
        users_count = int((await session.execute(select(func.count(User.id)))).scalar() or 0)
        documents_count = int((await session.execute(select(func.count(Document.id)))).scalar() or 0)
        homeworks_count = int((await session.execute(select(func.count(Homework.id)))).scalar() or 0)
        chunks_count = int((await session.execute(select(func.count(Chunk.id)))).scalar() or 0)
        messages_count = int((await session.execute(select(func.count(Message.id)))).scalar() or 0)
        return {
            "users": users_count,
            "documents": documents_count,
            "homeworks": homeworks_count,
            "chunks": chunks_count,
            "messages": messages_count,
        }

    @staticmethod
    async def dashboard(session: AsyncSession) -> dict[str, int]:
        totals = await StatsRepository.totals(session)
        user_files_count = int((await session.execute(select(func.count(UserFile.id)))).scalar() or 0)
        errors_count = int((await session.execute(select(func.count(ErrorLog.id)))).scalar() or 0)
        users_with_project_context = int(
            (
                await session.execute(
                    select(func.count(User.id)).where(
                        and_(User.project_context.is_not(None), func.length(User.project_context) > 0)
                    )
                )
            ).scalar()
            or 0
        )
        global_documents = int(
            (
                await session.execute(select(func.count(Document.id)).where(Document.visibility == VisibilityEnum.global_))
            ).scalar()
            or 0
        )
        user_documents = int(
            (await session.execute(select(func.count(Document.id)).where(Document.visibility == VisibilityEnum.user))).scalar()
            or 0
        )
        ready_documents = int(
            (await session.execute(select(func.count(Document.id)).where(Document.status == DocumentStatusEnum.ready))).scalar()
            or 0
        )
        processing_documents = int(
            (
                await session.execute(
                    select(func.count(Document.id)).where(
                        Document.status.in_([DocumentStatusEnum.uploaded, DocumentStatusEnum.processing])
                    )
                )
            ).scalar()
            or 0
        )
        error_documents = int(
            (await session.execute(select(func.count(Document.id)).where(Document.status == DocumentStatusEnum.error))).scalar()
            or 0
        )
        active_homeworks = int(
            (await session.execute(select(func.count(Homework.id)).where(Homework.status == "active"))).scalar()
            or 0
        )
        now = datetime.now(timezone.utc)
        messages_today = await StatsRepository.count_messages_since(session, now - timedelta(days=1))
        messages_week = await StatsRepository.count_messages_since(session, now - timedelta(days=7))
        messages_month = await StatsRepository.count_messages_since(session, now - timedelta(days=30))
        return {
            **totals,
            "user_files": user_files_count,
            "errors": errors_count,
            "users_with_project_context": users_with_project_context,
            "global_documents": global_documents,
            "user_documents": user_documents,
            "ready_documents": ready_documents,
            "processing_documents": processing_documents,
            "error_documents": error_documents,
            "active_homeworks": active_homeworks,
            "messages_today": messages_today,
            "messages_week": messages_week,
            "messages_month": messages_month,
        }

    @staticmethod
    async def count_messages_since(session: AsyncSession, since: datetime) -> int:
        result = await session.execute(select(func.count(Message.id)).where(Message.created_at >= since))
        return int(result.scalar() or 0)

    @staticmethod
    async def token_usage_since(session: AsyncSession, since: datetime) -> dict[str, int]:
        result = await session.execute(select(Message.token_usage).where(Message.created_at >= since))
        usage_rows = [row[0] for row in result.all() if isinstance(row[0], dict)]
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        for usage in usage_rows:
            prompt_tokens += _usage_int(
                usage,
                "prompt_tokens",
                "input_tokens",
                "input_text_tokens",
                "prompt_token_count",
            )
            completion_tokens += _usage_int(
                usage,
                "completion_tokens",
                "output_tokens",
                "completion_token_count",
            )
            total_tokens += _usage_int(usage, "total_tokens", "total_token_count")
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        return {
            "requests": len(usage_rows),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    async def estimated_embedding_tokens(session: AsyncSession) -> int:
        # A cheap MVP estimate: 1 token is roughly 4 text characters for Russian/English mixed docs.
        result = await session.execute(select(func.coalesce(func.sum(func.length(Chunk.chunk_text)), 0)))
        total_chars = int(result.scalar() or 0)
        return max(total_chars // 4, 0)


def _usage_int(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int | float):
            return int(value)
    return 0
