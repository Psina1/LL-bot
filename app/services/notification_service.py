from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from app.config import Settings
from app.db.repositories import (
    AppSettingRepository,
    ErrorRepository,
    HomeworkRepository,
    NotificationDeliveryRepository,
    ProgramLessonRepository,
    UserNotificationSettingRepository,
)
from app.db.session import SessionLocal
from app.notifications.constants import (
    NOTIFICATION_ACTIVE_KEY,
    NOTIFICATION_EXPIRES_AT_KEY,
    NOTIFICATION_TIME_OPTIONS,
)

logger = logging.getLogger(__name__)
NO_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)


class NotificationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            self.timezone = ZoneInfo(settings.notification_timezone)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown notification timezone %s, fallback to UTC", settings.notification_timezone)
            self.timezone = ZoneInfo("UTC")

    async def run(self, bot: Bot) -> None:
        if not self.settings.notifications_enabled:
            logger.info("Notifications are disabled")
            return

        logger.info("Notification scheduler started")
        while True:
            try:
                await self.send_due_notifications(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("notification_scheduler_failed")
            await asyncio.sleep(max(self.settings.notification_check_interval_seconds, 10))

    async def send_due_notifications(self, bot: Bot) -> None:
        now = datetime.now(self.timezone)
        current_time = now.strftime("%H:%M")
        if current_time not in NOTIFICATION_TIME_OPTIONS:
            return

        delivery_date = now.date()
        target_date = delivery_date + timedelta(days=1)
        async with SessionLocal() as session:
            active_value = await AppSettingRepository.get_value(session, NOTIFICATION_ACTIVE_KEY)
            if not _is_enabled(active_value):
                return

            expires_at_value = await AppSettingRepository.get_value(session, NOTIFICATION_EXPIRES_AT_KEY)
            expires_at = _parse_expires_at(expires_at_value, self.timezone)
            if expires_at is not None and now >= expires_at:
                logger.info("Notification expired at %s, skip sending", expires_at.isoformat())
                return

            recipients = await UserNotificationSettingRepository.list_due_recipients(session, current_time)
            lessons = await ProgramLessonRepository.list_by_start_date(session, target_date)
            homeworks = await HomeworkRepository.list_by_deadline(session, target_date)

        if not recipients or (not lessons and not homeworks):
            return

        for recipient in recipients:
            for lesson in lessons:
                await self._send_once(
                    bot=bot,
                    chat_id=recipient.telegram_id,
                    user_id=recipient.user_id,
                    notification_key=f"event:{lesson.lesson_key}",
                    delivery_date=delivery_date,
                    scheduled_time=current_time,
                    text=_build_event_notification_text(lesson),
                    error_context="send_event_notification",
                )

            for homework in homeworks:
                await self._send_once(
                    bot=bot,
                    chat_id=recipient.telegram_id,
                    user_id=recipient.user_id,
                    notification_key=f"homework:{homework.id}:deadline",
                    delivery_date=delivery_date,
                    scheduled_time=current_time,
                    text=_build_homework_notification_text(homework),
                    error_context="send_homework_notification",
                )

    async def _send_once(
        self,
        bot: Bot,
        chat_id: int,
        user_id: int,
        notification_key: str,
        delivery_date,
        scheduled_time: str,
        text: str,
        error_context: str,
    ) -> None:
        async with SessionLocal() as session:
            already_processed = await NotificationDeliveryRepository.was_processed(
                session=session,
                user_id=user_id,
                notification_key=notification_key,
                delivery_date=delivery_date,
                scheduled_time=scheduled_time,
            )
        if already_processed:
            return

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=None,
                link_preview_options=NO_LINK_PREVIEW,
            )
            async with SessionLocal() as session:
                await NotificationDeliveryRepository.mark(
                    session=session,
                    user_id=user_id,
                    notification_key=notification_key,
                    delivery_date=delivery_date,
                    scheduled_time=scheduled_time,
                    status="sent",
                )
        except Exception as exc:
            logger.exception("%s_failed", error_context)
            async with SessionLocal() as session:
                await NotificationDeliveryRepository.mark(
                    session=session,
                    user_id=user_id,
                    notification_key=notification_key,
                    delivery_date=delivery_date,
                    scheduled_time=scheduled_time,
                    status="error",
                    error_text=str(exc),
                )
                await ErrorRepository.create(
                    session=session,
                    context=error_context,
                    error_text=str(exc),
                    user_id=user_id,
                )


def _is_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _parse_expires_at(value: str | None, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning("Invalid notification expiry datetime: %s", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _format_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else "дата уточняется"


def _build_event_notification_text(lesson) -> str:
    lines = [
        "Напоминание о занятии",
        "",
        f"Завтра, {_format_date(lesson.date_start)}, состоится:",
        lesson.lesson_title,
        "",
        f"Блок: {lesson.block_title}",
    ]
    if lesson.speaker:
        lines.append(f"Спикер: {lesson.speaker}")
    lines.extend(
        [
            "",
            "Материалы и ссылки по обучению публикуем на ПРОГРЕССе.",
        ]
    )
    return "\n".join(lines)


def _build_homework_notification_text(homework) -> str:
    lines = [
        "Напоминание по домашнему заданию",
        "",
        f"Завтра, {_format_date(homework.deadline_date)}, дедлайн сдачи:",
        homework.title,
    ]
    if homework.module_title or homework.lesson_date:
        context_parts = []
        if homework.module_title:
            context_parts.append(homework.module_title)
        if homework.lesson_date:
            context_parts.append(_format_date(homework.lesson_date))
        lines.extend(["", f"Привязка: {', '.join(context_parts)}"])
    if homework.moodle_url:
        lines.extend(["", f"Ссылка для сдачи: {homework.moodle_url}"])
    return "\n".join(lines)
