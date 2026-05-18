from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.types import FSInputFile

from app.bot.texts import BOT_TEXT_DEFAULTS
from app.config import Settings
from app.db.repositories import (
    AppSettingRepository,
    BotTextRepository,
    ErrorRepository,
    NotificationDeliveryRepository,
    UserNotificationSettingRepository,
)
from app.db.session import SessionLocal
from app.notifications.constants import (
    DAILY_TEST_NOTIFICATION_KEY,
    NOTIFICATION_ICS_FILENAME_KEY,
    NOTIFICATION_ICS_PATH_KEY,
    NOTIFICATION_TEXT_KEY,
    NOTIFICATION_TIME_OPTIONS,
)

logger = logging.getLogger(__name__)


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
        async with SessionLocal() as session:
            text = await BotTextRepository.get_value(
                session,
                NOTIFICATION_TEXT_KEY,
                BOT_TEXT_DEFAULTS[NOTIFICATION_TEXT_KEY],
            )
            ics_path_value = await AppSettingRepository.get_value(session, NOTIFICATION_ICS_PATH_KEY)
            ics_filename = await AppSettingRepository.get_value(session, NOTIFICATION_ICS_FILENAME_KEY)
            recipients = await UserNotificationSettingRepository.list_due_recipients(session, current_time)

        ics_path = Path(ics_path_value) if ics_path_value else None
        if ics_path is not None and not ics_path.exists():
            logger.warning("Configured ICS file does not exist: %s", ics_path)
            ics_path = None

        for recipient in recipients:
            async with SessionLocal() as session:
                already_processed = await NotificationDeliveryRepository.was_processed(
                    session=session,
                    user_id=recipient.user_id,
                    notification_key=DAILY_TEST_NOTIFICATION_KEY,
                    delivery_date=delivery_date,
                    scheduled_time=current_time,
                )
            if already_processed:
                continue

            try:
                await bot.send_message(chat_id=recipient.telegram_id, text=text, parse_mode=None)
                if ics_path is not None:
                    await bot.send_document(
                        chat_id=recipient.telegram_id,
                        document=FSInputFile(ics_path, filename=ics_filename or ics_path.name),
                        parse_mode=None,
                    )
                async with SessionLocal() as session:
                    await NotificationDeliveryRepository.mark(
                        session=session,
                        user_id=recipient.user_id,
                        notification_key=DAILY_TEST_NOTIFICATION_KEY,
                        delivery_date=delivery_date,
                        scheduled_time=current_time,
                        status="sent",
                    )
            except Exception as exc:
                logger.exception("send_user_notification_failed")
                async with SessionLocal() as session:
                    await NotificationDeliveryRepository.mark(
                        session=session,
                        user_id=recipient.user_id,
                        notification_key=DAILY_TEST_NOTIFICATION_KEY,
                        delivery_date=delivery_date,
                        scheduled_time=current_time,
                        status="error",
                        error_text=str(exc),
                    )
                    await ErrorRepository.create(
                        session=session,
                        context="send_user_notification",
                        error_text=str(exc),
                        user_id=recipient.user_id,
                    )
