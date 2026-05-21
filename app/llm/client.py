from __future__ import annotations

import base64
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

    async def extract_text_from_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        label: str,
    ) -> str:
        if self.settings.llm_provider == "mock":
            return ""

        if self.client is None:
            raise RuntimeError("LLM client is not initialized")

        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        response = await self.client.chat.completions.create(
            model=self.settings.openai_ocr_model or self.settings.openai_chat_model,
            temperature=0,
            max_tokens=1200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты OCR-движок. Извлекай только видимый текст с изображения. "
                        "Не пересказывай, не объясняй и не добавляй факты от себя. "
                        "Сохраняй русский язык, важные заголовки, списки, даты и контакты. "
                        "Если читаемого текста нет, верни пустую строку."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Источник: {label}.\n"
                                "Распознай весь читаемый текст на изображении. "
                                "Верни только текст, без Markdown-обвязки."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded_image}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        )
        answer = response.choices[0].message.content or ""
        return "" if self._is_empty_ocr_response(answer) else answer.strip()

    def _mock_chat_completion(self, user_prompt: str) -> ChatResult:
        question = self._extract_question(user_prompt)
        answer = (
            "Это тестовый ответ mock-режима. Бот, Telegram, БД и сценарий вопрос-ответ работают.\n\n"
            f"Я получил твой вопрос: «{question}». Когда включён LLM_PROVIDER=openai, "
            "здесь будет реальный ответ модели по загруженным материалам.\n\n"
            "Сейчас можно проверить /start, меню, права админа, сохранение сообщений и загрузку файлов."
        )
        return ChatResult(answer=answer, token_usage={"provider": "mock"})

    def _mock_embedding(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], byteorder="big", signed=False)
        generator = random.Random(seed)
        return [generator.uniform(-1.0, 1.0) for _ in range(self.settings.embedding_dimensions)]

    @staticmethod
    def _is_empty_ocr_response(text: str) -> bool:
        normalized = " ".join(text.strip().lower().strip(".!").split())
        if not normalized:
            return True
        empty_markers = (
            "текст на изображении отсутствует",
            "читаемый текст отсутствует",
            "нет читаемого текста",
            "текста нет",
            "на изображении нет текста",
            "no readable text",
            "no text found",
        )
        return any(marker in normalized for marker in empty_markers)

    @staticmethod
    def _extract_question(user_prompt: str) -> str:
        marker = "Вопрос пользователя:"
        if marker not in user_prompt:
            return user_prompt[:180].strip()
        tail = user_prompt.split(marker, 1)[1].strip()
        question = tail.split("\n\n", 1)[0].strip()
        return question[:180] or "без текста"
