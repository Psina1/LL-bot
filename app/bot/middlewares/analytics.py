from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.keyboards.reply import all_reply_button_labels
from app.db.repositories import UserEventRepository, UserRepository
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

PRIVATE_CHAT_TYPES = {"private"}


class AnalyticsMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.reply_button_labels = all_reply_button_labels()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        await self._log_event(event)
        return await handler(event, data)

    async def _log_event(self, event: TelegramObject) -> None:
        event_type: str | None = None
        event_name: str | None = None
        payload: dict[str, Any] = {}

        if isinstance(event, Message):
            if event.chat.type not in PRIVATE_CHAT_TYPES:
                return
            text = (event.text or "").strip()
            if not text:
                return
            if text.startswith("/"):
                event_type = "command"
                event_name = text.split(maxsplit=1)[0]
            elif text in self.reply_button_labels:
                event_type = "reply_button"
                event_name = text
            else:
                return

        elif isinstance(event, CallbackQuery):
            if event.message and event.message.chat.type not in PRIVATE_CHAT_TYPES:
                return
            if not event.data:
                return
            event_type = "inline_button"
            event_name = _callback_event_name(event.data)
            payload = {"callback_data": event.data}
        else:
            return

        user = getattr(event, "from_user", None)
        if user is None or event_type is None or event_name is None:
            return

        try:
            async with SessionLocal() as session:
                db_user = await UserRepository.get_by_telegram_id(session, user.id)
                await UserEventRepository.create(
                    session=session,
                    telegram_id=user.id,
                    username=user.username,
                    user_id=db_user.id if db_user else None,
                    event_type=event_type,
                    event_name=event_name,
                    payload=payload,
                )
        except Exception:
            # Analytics must never break the bot flow.
            logger.exception("analytics_event_log_failed")


def _callback_event_name(callback_data: str) -> str:
    exact = {
        "menu:main": "Главное меню",
        "question_section:program": "Вопрос по программе",
        "question_section:technical": "Технический вопрос",
        "question_section:other": "Другое",
        "materials:records": "Материалы: записи и материалы",
        "materials:docs": "Материалы: текстовые материалы",
        "materials:podcasts": "Материалы: подкасты",
        "materials:podcast_text": "Материалы: текстовая подкаст-выжимка",
        "materials:summary": "Материалы: саммари",
        "homework:list": "Домашние задания: список",
        "homework:help": "Домашние задания: помощь",
        "admin_text:save": "Админ: сохранить текст",
        "admin_text:cancel": "Админ: отменить текст",
    }
    if callback_data in exact:
        return exact[callback_data]

    prefix_labels = [
        ("start_notification_time:", "Старт: выбор времени уведомлений"),
        ("homework:item:", "Домашние задания: конкретное ДЗ"),
        ("homework:help:", "Домашние задания: вопрос по конкретному ДЗ"),
        ("media:video:", "Материалы: открыть видео"),
        ("media:podcast:", "Материалы: открыть подкаст"),
        ("media:schedule_image:", "Расписание: картинка"),
        ("media:", "Материалы: открыть медиа"),
        ("schedule:season:", "Расписание: сезон"),
        ("schedule:block:", "Расписание: блок"),
        ("schedule:lesson:", "Расписание: занятие"),
        ("schedule:materials:", "Расписание: материалы занятия"),
        ("feedback:", "Оценка ответа"),
        ("feedback_reason:", "Причина оценки ответа"),
    ]
    for prefix, label in prefix_labels:
        if callback_data.startswith(prefix):
            return label
    return f"callback:{callback_data[:120]}"
