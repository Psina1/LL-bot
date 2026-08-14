from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot

from app.bot.keyboards.lesson_feedback import feedback_invitation_keyboard
from app.config import Settings
from app.db.feedback_repositories import (
    FeedbackCampaignRepository,
    FeedbackDeliveryRepository,
    FeedbackResponseRepository,
    list_feedback_recipients,
)
from app.db.repositories import ErrorRepository
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class FeedbackService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            self.timezone = ZoneInfo(settings.notification_timezone)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Unknown feedback timezone %s, fallback to UTC",
                settings.notification_timezone,
            )
            self.timezone = ZoneInfo("UTC")

    async def run(self, bot: Bot) -> None:
        logger.info("Lesson feedback scheduler started")
        while True:
            try:
                await self.process_due_campaigns(bot)
                await self.process_due_reminders(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("lesson_feedback_scheduler_failed")
            await asyncio.sleep(max(self.settings.notification_check_interval_seconds, 10))

    async def process_due_campaigns(self, bot: Bot) -> None:
        now = datetime.now(self.timezone)
        async with SessionLocal() as session:
            campaigns = await FeedbackCampaignRepository.list_due(session, now)

        for campaign in campaigns:
            await self._launch_campaign(bot, campaign.id, now)

    async def process_due_reminders(self, bot: Bot) -> None:
        now = datetime.now(self.timezone)
        async with SessionLocal() as session:
            due_rows = await FeedbackResponseRepository.list_due_reminders(session, now)

        for response, campaign, user, notification_time in due_rows:
            delivery_number = response.reminder_count + 1
            delivery_type = f"reminder_{delivery_number}"
            final_reminder = delivery_number >= 2

            async with SessionLocal() as session:
                already_sent = await FeedbackDeliveryRepository.was_sent(
                    session,
                    response.id,
                    delivery_type,
                )
            if already_sent:
                continue

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        campaign.reminder_text_override
                        or self.build_reminder_text(campaign.lesson_title, campaign.lesson_date)
                    ),
                    reply_markup=feedback_invitation_keyboard(
                        response.id,
                        final_reminder=final_reminder,
                    ),
                    parse_mode=None,
                )
                sent_at = datetime.now(self.timezone)
                next_reminder_at = None
                if not final_reminder:
                    next_reminder_at = self.next_day_at(
                        sent_at,
                        notification_time or "12:00",
                    )
                async with SessionLocal() as session:
                    await FeedbackDeliveryRepository.mark(
                        session=session,
                        campaign_id=campaign.id,
                        response_id=response.id,
                        user_id=user.id,
                        delivery_type=delivery_type,
                        scheduled_at=response.next_reminder_at or now,
                        sent_at=sent_at,
                        status="sent",
                    )
                    await FeedbackResponseRepository.mark_reminder_sent(
                        session,
                        response.id,
                        sent_at,
                        next_reminder_at,
                    )
            except Exception as exc:
                logger.exception("lesson_feedback_reminder_failed")
                async with SessionLocal() as session:
                    await FeedbackDeliveryRepository.mark(
                        session=session,
                        campaign_id=campaign.id,
                        response_id=response.id,
                        user_id=user.id,
                        delivery_type=delivery_type,
                        scheduled_at=response.next_reminder_at or now,
                        status="error",
                        error_text=str(exc),
                    )
                    await ErrorRepository.create(
                        session,
                        context="lesson_feedback_reminder",
                        error_text=str(exc),
                        user_id=user.id,
                    )
                    await FeedbackResponseRepository.postpone(
                        session,
                        response.id,
                        now + timedelta(hours=1),
                    )

    async def _launch_campaign(self, bot: Bot, campaign_id: int, now: datetime) -> None:
        async with SessionLocal() as session:
            campaign = await FeedbackCampaignRepository.get(session, campaign_id)
            if campaign is None or campaign.status != "scheduled":
                return
            recipients = await list_feedback_recipients(
                session,
                admin_ids=self.settings.admin_ids,
                is_test=campaign.is_test,
            )

        for user, notification_time in recipients:
            async with SessionLocal() as session:
                response = await FeedbackResponseRepository.ensure_for_user(
                    session,
                    campaign_id=campaign.id,
                    user_id=user.id,
                )
                already_sent = await FeedbackDeliveryRepository.was_sent(
                    session,
                    response.id,
                    "initial",
                )
            if already_sent:
                continue

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        campaign.initial_text_override
                        or self.build_initial_text(campaign.lesson_title, campaign.lesson_date)
                    ),
                    reply_markup=feedback_invitation_keyboard(response.id),
                    parse_mode=None,
                )
                sent_at = datetime.now(self.timezone)
                next_reminder_at = self.next_day_at(
                    sent_at,
                    notification_time or "12:00",
                )
                async with SessionLocal() as session:
                    await FeedbackDeliveryRepository.mark(
                        session=session,
                        campaign_id=campaign.id,
                        response_id=response.id,
                        user_id=user.id,
                        delivery_type="initial",
                        scheduled_at=campaign.launch_at or now,
                        sent_at=sent_at,
                        status="sent",
                    )
                    await FeedbackResponseRepository.mark_initial_sent(
                        session,
                        response.id,
                        sent_at,
                        next_reminder_at,
                    )
            except Exception as exc:
                logger.exception("lesson_feedback_initial_send_failed")
                async with SessionLocal() as session:
                    await FeedbackDeliveryRepository.mark(
                        session=session,
                        campaign_id=campaign.id,
                        response_id=response.id,
                        user_id=user.id,
                        delivery_type="initial",
                        scheduled_at=campaign.launch_at or now,
                        status="error",
                        error_text=str(exc),
                    )
                    await ErrorRepository.create(
                        session,
                        context="lesson_feedback_initial_send",
                        error_text=str(exc),
                        user_id=user.id,
                    )

        async with SessionLocal() as session:
            await FeedbackCampaignRepository.mark_active(session, campaign.id)

    def next_day_at(self, reference: datetime, time_value: str) -> datetime:
        try:
            hour, minute = (int(part) for part in time_value.split(":", 1))
            target_time = time(hour=hour, minute=minute)
        except (TypeError, ValueError):
            target_time = time(hour=12)
        local_reference = reference.astimezone(self.timezone)
        target_date = local_reference.date() + timedelta(days=1)
        return datetime.combine(target_date, target_time, tzinfo=self.timezone)

    @staticmethod
    def lesson_label(title: str, lesson_date) -> str:
        if lesson_date:
            return f"{title} ({lesson_date.strftime('%d.%m.%Y')})"
        return title

    @classmethod
    def build_initial_text(cls, title: str, lesson_date) -> str:
        return (
            "Спасибо за участие!\n\n"
            "Поделись короткой обратной связью 🙌\n"
            f"«{cls.lesson_label(title, lesson_date)}»\n\n"
            "Нам важно понимать, что было полезно, а что стоит улучшить в программе.\n"
            "Опрос займёт буквально пару минут."
        )

    @classmethod
    def build_reminder_text(cls, title: str, lesson_date) -> str:
        return (
            "Привет!\n\n"
            "Поделись, пожалуйста, короткой обратной связью 🙌\n"
            f"«{cls.lesson_label(title, lesson_date)}»\n\n"
            "Нам важно понимать, что было полезно, а что стоит улучшить в программе.\n"
            "Опрос займёт буквально пару минут."
        )
