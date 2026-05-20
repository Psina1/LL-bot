from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import aiofiles
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, DocumentStatusEnum, VisibilityEnum
from app.db.repositories import DocumentRepository, ErrorRepository, UserFileRepository
from app.rag.service import RAGService

UploadMode = Literal["global", "user"]


@dataclass(slots=True)
class SavedUpload:
    path: Path
    original_filename: str
    extension: str


class FileValidationError(Exception):
    pass


class DocumentService:
    def __init__(self, settings: Settings, rag_service: RAGService) -> None:
        self.settings = settings
        self.rag_service = rag_service

    def validate_file(self, filename: str | None, file_size: int | None) -> str:
        if not filename:
            raise FileValidationError("Не получилось определить имя файла")
        extension = filename.split(".")[-1].lower()
        if extension not in self.settings.extensions_set:
            raise FileValidationError("Этот формат пока не поддерживается. Пришли PDF, DOCX, PPTX или TXT.")
        if file_size and file_size > self.settings.max_file_size_bytes:
            raise FileValidationError(
                f"Файл слишком большой. Максимальный размер: {self.settings.max_file_size_mb} МБ."
            )
        return extension

    async def save_telegram_file(
        self,
        bot: Bot,
        telegram_file_id: str,
        filename: str,
        owner_telegram_id: int,
        mode: UploadMode,
    ) -> SavedUpload:
        extension = filename.split(".")[-1].lower()
        owner_dir = (
            self.settings.materials_dir if mode == "global" else self.settings.uploads_dir / str(owner_telegram_id)
        )
        owner_dir.mkdir(parents=True, exist_ok=True)
        target_path = owner_dir / filename

        file_data = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                file_info = await bot.get_file(telegram_file_id)
                file_data = await bot.download_file(file_info.file_path)
                break
            except TelegramNetworkError as exc:
                last_error = exc
                await asyncio.sleep(1 + attempt)

        if file_data is None:
            raise last_error or RuntimeError("Telegram file download failed")

        async with aiofiles.open(target_path, "wb") as out:
            await out.write(file_data.read())

        return SavedUpload(path=target_path, original_filename=filename, extension=extension)

    async def create_and_index_document(
        self,
        session: AsyncSession,
        title: str,
        saved_upload: SavedUpload,
        visibility: UploadMode,
        owner_user_id: int | None,
        telegram_file_id: str | None = None,
        module_number: int | None = None,
        module_title: str | None = None,
        lesson_key: str | None = None,
        material_type: str | None = None,
        tags: list[str] | None = None,
    ) -> Document:
        document = await DocumentRepository.create(
            session=session,
            title=title,
            original_filename=saved_upload.original_filename,
            stored_path=str(saved_upload.path),
            file_type=saved_upload.extension,
            visibility=VisibilityEnum.global_ if visibility == "global" else VisibilityEnum.user,
            owner_user_id=owner_user_id,
            module_number=module_number,
            module_title=module_title,
            lesson_key=lesson_key,
            material_type=material_type,
            tags=tags,
            status=DocumentStatusEnum.uploaded,
        )

        if telegram_file_id and owner_user_id:
            await UserFileRepository.create(
                session=session,
                user_id=owner_user_id,
                telegram_file_id=telegram_file_id,
                document_id=document.id,
                original_filename=saved_upload.original_filename,
            )

        try:
            await self.rag_service.index_document(session=session, document=document)
        except Exception as exc:
            await ErrorRepository.create(
                session=session,
                context="index_document",
                error_text=str(exc),
                user_id=owner_user_id,
            )
            raise

        refreshed = await DocumentRepository.get_by_id(session, document.id)
        if refreshed is None:
            raise RuntimeError("Документ не найден после индексации")
        return refreshed

    async def reindex_all(self, session: AsyncSession) -> tuple[int, int]:
        documents = await DocumentRepository.reindex_candidates(session)
        ok = 0
        failed = 0
        for document in documents:
            try:
                await self.rag_service.index_document(session, document)
                ok += 1
            except Exception as exc:
                failed += 1
                await ErrorRepository.create(
                    session=session,
                    context="reindex_document",
                    error_text=f"document_id={document.id}; {exc}",
                    user_id=document.owner_user_id,
                )
        return ok, failed
