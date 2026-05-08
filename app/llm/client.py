from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import Settings


@dataclass(slots=True)
class ChatResult:
    answer: str
    token_usage: dict[str, Any] | None


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: AsyncOpenAI | None = None
        if settings.llm_provider == "mock":
            return
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set. Fill .env or use LLM_PROVIDER=mock")
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
            timeout=httpx.Timeout(connect=20.0, read=90.0, write=20.0, pool=20.0),
            max_retries=3,
        )

    async def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> ChatResult:
        if self.settings.llm_provider == "mock":
            return self._mock_chat_completion(user_prompt)

        if self.client is None:
            raise RuntimeError("LLM client is not initialized")

        response = await self.client.chat.completions.create(
            model=self.settings.openai_chat_model,
            temperature=temperature if temperature is not None else self.settings.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = response.choices[0].message.content or ""
        usage = response.usage.model_dump() if response.usage else None
        return ChatResult(answer=answer.strip(), token_usage=usage)

    async def create_embedding(self, text: str) -> list[float]:
        if self.settings.llm_provider == "mock":
            return self._mock_embedding(text)

        if self.client is None:
            raise RuntimeError("LLM client is not initialized")

        response = await self.client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        return list(response.data[0].embedding)

    def _mock_chat_completion(self, user_prompt: str) -> ChatResult:
        question = self._extract_question(user_prompt)
        answer = (
            "Коротко:\n"
            "Это тестовый ответ mock-режима. Бот, Telegram, БД и сценарий вопрос-ответ работают.\n\n"
            "Подробнее:\n"
            f"Я получил вопрос: «{question}». Когда добавим OpenAI API key и переключим "
            "LLM_PROVIDER=openai, здесь будет реальный ответ модели по материалам.\n\n"
            "Что можно применить:\n"
            "Сейчас можно проверить /start, меню, права админа, сохранение сообщений и загрузку файлов.\n\n"
            "Источники: mock-режим, реальные источники появятся после индексации материалов."
        )
        return ChatResult(answer=answer, token_usage={"provider": "mock"})

    def _mock_embedding(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], byteorder="big", signed=False)
        generator = random.Random(seed)
        return [generator.uniform(-1.0, 1.0) for _ in range(self.settings.embedding_dimensions)]

    @staticmethod
    def _extract_question(user_prompt: str) -> str:
        marker = "Вопрос пользователя:"
        if marker not in user_prompt:
            return user_prompt[:180].strip()
        tail = user_prompt.split(marker, 1)[1].strip()
        question = tail.split("\n\n", 1)[0].strip()
        return question[:180] or "без текста"
