from __future__ import annotations

from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from app.config import Settings


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    model: str


class TranscriptionService:
    DOMAIN_PROMPT = (
        "Лига лидеров, КОРУС Консалтинг, ПРОГРЕСС, Moodle, Time to Cash, "
        "Accenture, бизнес-консалтинг, домашнее задание."
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: AsyncOpenAI | None = None
        if settings.openai_transcription_api_key:
            self.client = AsyncOpenAI(
                api_key=settings.openai_transcription_api_key,
                base_url=settings.openai_transcription_base_url or None,
                timeout=httpx.Timeout(connect=20.0, read=120.0, write=60.0, pool=20.0),
                max_retries=2,
            )

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        mime_type: str = "audio/ogg",
    ) -> TranscriptionResult:
        if self.client is None:
            raise RuntimeError("OPENAI_TRANSCRIPTION_API_KEY is not configured")
        if not audio_bytes:
            raise ValueError("Voice message is empty")

        response = await self.client.audio.transcriptions.create(
            model=self.settings.openai_transcription_model,
            file=(filename, audio_bytes, mime_type),
            language="ru",
            prompt=self.DOMAIN_PROMPT,
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Transcription API returned empty text")
        return TranscriptionResult(
            text=text,
            model=self.settings.openai_transcription_model,
        )
