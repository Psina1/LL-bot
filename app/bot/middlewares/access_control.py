from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.db.repositories import AllowedUserRepository
from app.db.session import SessionLocal


PRIVATE_CHAT_TYPES = {"private"}
DENIED_TEXT = (
    "Пока у тебя нет доступа к боту программы «Лига лидеров».\n\n"
    "Если это ошибка, напиши организаторам программы или Илье: @reptiloid0."
)


class AccessControlMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: list[int]) -> None:
        self.admin_ids = set(admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        # Group chats are handled by dedicated group/admin handlers. The bot stays silent there by default.
        if isinstance(event, Message) and event.chat.type not in PRIVATE_CHAT_TYPES:
            return await handler(event, data)

        if user.id in self.admin_ids:
            return await handler(event, data)

        async with SessionLocal() as session:
            allowed = await AllowedUserRepository.is_allowed(
                session=session,
                telegram_id=user.id,
                username=user.username,
                admin_ids=self.admin_ids,
            )

        if allowed:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(DENIED_TEXT)
        elif isinstance(event, CallbackQuery):
            await event.answer("Нет доступа к боту", show_alert=True)
            if event.message:
                await event.message.answer(DENIED_TEXT)
        return None
