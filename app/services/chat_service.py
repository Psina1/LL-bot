from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.db.repositories import ErrorRepository, MessageRepository
from app.llm.client import LLMClient
from app.llm.prompts import SYSTEM_PROMPT
from app.rag.service import RAGService


@dataclass(slots=True)
class ChatAnswer:
    text: str
    sources: list[dict[str, Any]]
    token_usage: dict[str, Any] | None
    mode: str
    message_id: int


class ChatService:
    CONTACTS_RULE = (
        "Если в контексте есть контакты человека, email, Telegram или телефон, обязательно укажи их прямо в ответе. "
        "Не пиши обобщённо «по почте или в Telegram», если рядом есть конкретный адрес или ник. "
        "Если контакт в тексте разбит пробелами, восстанови его в нормальный вид: "
        "`name @ domain . ru` -> `name@domain.ru`, `@ Name` -> `@Name`."
    )

    def __init__(self, settings: Settings, llm_client: LLMClient, rag_service: RAGService) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.rag_service = rag_service

    async def answer_question(
        self,
        session: AsyncSession,
        user: User,
        question: str,
        mode: str = "training_qa",
        force_rag: bool = True,
        extra_context: str | None = None,
    ) -> ChatAnswer:
        user_id = user.id
        project_context = user.project_context
        context_text = ""
        sources: list[dict[str, Any]] = []

        if force_rag:
            try:
                rag_context = await self.rag_service.build_context_for_question(
                    session=session,
                    question=question,
                    user_id=user_id,
                )
                context_text = rag_context.context_text
                sources = rag_context.sources
            except Exception as exc:
                await session.rollback()
                await ErrorRepository.create(session, context="rag_search", error_text=str(exc), user_id=user_id)
                fallback_context = await self.rag_service.build_latest_user_file_context(
                    session=session,
                    user_id=user_id,
                )
                context_text = fallback_context.context_text
                sources = fallback_context.sources

        user_context_block = project_context.strip() if project_context else "Нет"
        if force_rag and not context_text and not extra_context:
            answer_text = (
                "В загруженных материалах я не нашёл точного ответа на этот вопрос.\n\n"
                "Если вопрос срочный или организационный, задай его в общий чат программы или напиши организаторам."
            )
            message = await MessageRepository.create(
                session=session,
                user_id=user_id,
                mode=mode,
                question=question,
                answer=answer_text,
                sources=[],
                token_usage=None,
            )
            return ChatAnswer(text=answer_text, sources=[], token_usage=None, mode=mode, message_id=message.id)

        if mode == "technical_question":
            answer_text = (
                "По техническим вопросам лучше сразу написать Илье в Telegram: @reptiloid0.\n\n"
                "Он поможет с доступом, платформой ПРОГРЕСС, Moodle, записями занятий, загрузкой домашних заданий "
                "и ошибками в работе бота."
            )
            message = await MessageRepository.create(
                session=session,
                user_id=user_id,
                mode=mode,
                question=question,
                answer=answer_text,
                sources=[],
                token_usage=None,
            )
            return ChatAnswer(text=answer_text, sources=[], token_usage=None, mode=mode, message_id=message.id)
        elif context_text:
            user_prompt = (
                f"Вопрос пользователя:\n{question}\n\n"
                f"Контекст по материалам:\n{context_text}\n\n"
                f"Дополнительный контекст раздела:\n{extra_context or 'Нет'}\n\n"
                f"Описание проекта пользователя:\n{user_context_block}\n\n"
                f"{self.CONTACTS_RULE}\n"
                "Сформируй ответ в формате: Коротко / Подробнее / Что можно применить. "
                "Не добавляй блок «Источники» и не перечисляй фрагменты: источники сохраняются системой отдельно."
            )
        else:
            user_prompt = (
                f"Вопрос пользователя:\n{question}\n\n"
                f"Служебный контекст:\n{extra_context or 'Нет'}\n\n"
                "Контекст по материалам: отсутствует.\n"
                f"Описание проекта пользователя:\n{user_context_block}\n\n"
                "Если служебный контекст отвечает на вопрос, используй его. "
                "Если ответа нет, прямо скажи, что точного ответа в загруженных материалах нет. "
                "Не добавляй блок «Источники»."
            )

        result = await self.llm_client.chat_completion(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        answer_text = self._ensure_sources_block(result.answer, sources)
        message = await MessageRepository.create(
            session=session,
            user_id=user_id,
            mode=mode,
            question=question,
            answer=answer_text,
            sources=sources,
            token_usage=result.token_usage,
        )
        return ChatAnswer(text=answer_text, sources=sources, token_usage=result.token_usage, mode=mode, message_id=message.id)

    async def answer_document_question(
        self,
        session: AsyncSession,
        user: User,
        question: str,
        document_id: int,
    ) -> ChatAnswer:
        user_id = user.id
        project_context = user.project_context
        rag_context = await self.rag_service.build_context_for_document_question(
            session=session,
            question=question,
            user_id=user_id,
            document_id=document_id,
        )
        sources = rag_context.sources
        if not rag_context.context_text:
            answer_text = (
                f"Я не нашёл готовый материал с id={document_id} или у тебя нет доступа к нему.\n\n"
                "Проверь список через «Материалы программы» -> «Записи и материалы занятий»."
            )
            message = await MessageRepository.create(
                session=session,
                user_id=user_id,
                mode="material_qa",
                question=question,
                answer=answer_text,
                sources=[],
                token_usage=None,
            )
            return ChatAnswer(text=answer_text, sources=[], token_usage=None, mode="material_qa", message_id=message.id)

        user_context_block = project_context.strip() if project_context else "Нет"
        user_prompt = (
            f"Вопрос пользователя по конкретному материалу id={document_id}:\n{question}\n\n"
            f"Контекст только из выбранного материала:\n{rag_context.context_text}\n\n"
            f"Описание проекта пользователя:\n{user_context_block}\n\n"
            "Ответь только на основе выбранного материала. "
            "Если в этом материале нет ответа, прямо скажи, что точного ответа в выбранном файле нет. "
            f"{self.CONTACTS_RULE}\n"
            "Сформируй ответ в формате: Коротко / Подробнее / Что можно применить. "
            "Не добавляй блок «Источники» и не перечисляй фрагменты: источники сохраняются системой отдельно."
        )

        result = await self.llm_client.chat_completion(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        answer_text = self._ensure_sources_block(result.answer, sources)
        message = await MessageRepository.create(
            session=session,
            user_id=user_id,
            mode="material_qa",
            question=question,
            answer=answer_text,
            sources=sources,
            token_usage=result.token_usage,
        )
        return ChatAnswer(text=answer_text, sources=sources, token_usage=result.token_usage, mode="material_qa", message_id=message.id)

    async def answer_without_rag(
        self,
        session: AsyncSession,
        user: User,
        question: str,
        mode: str = "general_chat",
    ) -> ChatAnswer:
        user_id = user.id
        prompt = (
            f"Вопрос пользователя: {question}\n\n"
            "Контекст материалов отсутствует. Ответь полезно, но добавь, что это общий ответ, не из загруженных материалов."
        )
        result = await self.llm_client.chat_completion(system_prompt=SYSTEM_PROMPT, user_prompt=prompt)
        answer_text = self._ensure_sources_block(result.answer, [])
        message = await MessageRepository.create(
            session=session,
            user_id=user_id,
            mode=mode,
            question=question,
            answer=answer_text,
            sources=[],
            token_usage=result.token_usage,
        )
        return ChatAnswer(text=answer_text, sources=[], token_usage=result.token_usage, mode=mode, message_id=message.id)

    @staticmethod
    def _ensure_sources_block(answer: str, sources: list[dict[str, Any]]) -> str:
        # Keep sources in the DB, but do not expose raw chunk/file metadata in the chat UX.
        return ChatService._strip_sources_block(answer)

    @staticmethod
    def _strip_sources_block(answer: str) -> str:
        normalized = answer.strip()
        normalized = re.sub(
            r"(?ims)\n*\s*(?:\*\*)?\s*(?:Проверенные источники|Источники)\s*(?:\*\*)?\s*[:：].*\Z",
            "",
            normalized,
        )
        return normalized.strip()
