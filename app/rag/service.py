from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, DocumentStatusEnum
from app.db.repositories import ChunkMatch, ChunkRepository, DocumentRepository
from app.file_processing.extractors import TextExtractionError, clean_text, extract_text_from_file
from app.file_processing.ocr_images import OCRImage, extract_pptx_images_for_ocr
from app.llm.client import LLMClient
from app.rag.chunking import split_text


@dataclass(slots=True)
class RAGAnswerContext:
    chunks: list[ChunkMatch]
    context_text: str
    sources: list[dict[str, Any]]


class RAGService:
    def __init__(self, settings: Settings, llm_client: LLMClient) -> None:
        self.settings = settings
        self.llm_client = llm_client

    async def index_document(self, session: AsyncSession, document: Document) -> int:
        await DocumentRepository.set_status(session, document.id, DocumentStatusEnum.processing)
        try:
            file_path = Path(document.stored_path)
            text = await self._extract_text_with_ocr_fallback(file_path)
            chunks = split_text(text, chunk_size=1200, overlap=150)
            payload: list[dict[str, Any]] = []

            for chunk in chunks:
                embedding = await self.llm_client.create_embedding(chunk.chunk_text)
                payload.append(
                    {
                        "chunk_index": chunk.chunk_index,
                        "chunk_text": chunk.chunk_text,
                        "embedding": embedding,
                        "metadata": {
                            "document_title": document.title,
                            "original_filename": document.original_filename,
                            "module_number": document.module_number,
                            "module_title": document.module_title,
                            "lesson_key": document.lesson_key,
                            "lesson_date": document.lesson_date.isoformat() if document.lesson_date else None,
                            "material_type": document.material_type,
                            "tags": document.tags or [],
                            "chunk_index": chunk.chunk_index,
                        },
                    }
                )

            count = await ChunkRepository.replace_for_document(session, document.id, payload)
            await DocumentRepository.set_status(session, document.id, DocumentStatusEnum.ready)
            return count
        except Exception as exc:
            await DocumentRepository.set_status(session, document.id, DocumentStatusEnum.error, str(exc))
            raise

    async def _extract_text_with_ocr_fallback(self, file_path: Path) -> str:
        extracted_text = ""
        extraction_error: TextExtractionError | None = None
        try:
            extracted_text = extract_text_from_file(file_path)
        except TextExtractionError as exc:
            extraction_error = exc

        if not self._should_try_ocr(file_path, extracted_text):
            if extraction_error is not None:
                raise extraction_error
            return extracted_text

        ocr_text = await self._extract_ocr_text(file_path)
        combined_text = clean_text(
            "\n\n".join(
                part
                for part in [
                    extracted_text,
                    "Текст, распознанный со слайдов:\n" + ocr_text if ocr_text else "",
                ]
                if part
            )
        )
        if combined_text:
            return combined_text

        if extraction_error is not None:
            raise extraction_error
        raise TextExtractionError("Не удалось извлечь текст из файла")

    def _should_try_ocr(self, file_path: Path, extracted_text: str) -> bool:
        if not self.settings.ocr_enabled:
            return False
        if file_path.suffix.lower() != ".pptx":
            return False
        return len(extracted_text.strip()) < self.settings.ocr_min_text_chars

    async def _extract_ocr_text(self, file_path: Path) -> str:
        images = extract_pptx_images_for_ocr(
            file_path,
            max_images=self.settings.ocr_max_images_per_document,
            max_image_bytes=self.settings.ocr_max_image_size_mb * 1024 * 1024,
            min_width=self.settings.ocr_min_image_width,
            min_height=self.settings.ocr_min_image_height,
        )
        if not images:
            return ""

        parts: list[str] = []
        for image in images:
            try:
                text = await self._extract_single_image_text(image)
            except Exception:
                # OCR is a quality fallback. A single bad/oversized slide should not
                # break indexing if the document still has extractable text.
                continue
            if text:
                parts.append(f"{image.label}\n{text}")
        return clean_text("\n\n".join(parts))

    async def _extract_single_image_text(self, image: OCRImage) -> str:
        text = await self.llm_client.extract_text_from_image(
            image_bytes=image.data,
            mime_type=image.mime_type,
            label=image.label,
        )
        return clean_text(text)

    async def build_context_for_question(
        self,
        session: AsyncSession,
        question: str,
        user_id: int,
    ) -> RAGAnswerContext:
        question_embedding = await self.llm_client.create_embedding(question)
        matches = await ChunkRepository.search_relevant(
            session=session,
            question_embedding=question_embedding,
            user_id=user_id,
            top_k=self.settings.max_context_chunks,
        )

        selected_chunks: list[ChunkMatch] = []
        total_chars = 0
        for match in matches:
            if total_chars + len(match.chunk_text) > self.settings.max_context_chars:
                break
            selected_chunks.append(match)
            total_chars += len(match.chunk_text)

        context_blocks: list[str] = []
        sources: list[dict[str, Any]] = []
        for index, match in enumerate(selected_chunks, start=1):
            block = f"[Фрагмент {index} | score={match.score:.3f}]\n{match.chunk_text}"
            context_blocks.append(block)
            sources.append(self._source_from_match(match))

        context_text = "\n\n".join(context_blocks)
        return RAGAnswerContext(chunks=selected_chunks, context_text=context_text, sources=sources)

    async def build_context_for_lesson_question(
        self,
        session: AsyncSession,
        question: str,
        user_id: int,
        lesson_key: str | None = None,
        lesson_date: Any | None = None,
        document_ids: list[int] | None = None,
    ) -> RAGAnswerContext:
        question_embedding = await self.llm_client.create_embedding(question)
        matches = await ChunkRepository.search_relevant_by_lesson(
            session=session,
            question_embedding=question_embedding,
            user_id=user_id,
            top_k=self.settings.max_context_chunks,
            lesson_key=lesson_key,
            lesson_date=lesson_date,
            document_ids=document_ids,
        )

        selected_chunks: list[ChunkMatch] = []
        total_chars = 0
        for match in matches:
            if total_chars + len(match.chunk_text) > self.settings.max_context_chars:
                break
            selected_chunks.append(match)
            total_chars += len(match.chunk_text)

        context_blocks: list[str] = []
        sources: list[dict[str, Any]] = []
        for index, match in enumerate(selected_chunks, start=1):
            block = f"[Фрагмент {index} | lesson-scope | score={match.score:.3f}]\n{match.chunk_text}"
            context_blocks.append(block)
            sources.append(self._source_from_match(match))

        return RAGAnswerContext(
            chunks=selected_chunks,
            context_text="\n\n".join(context_blocks),
            sources=sources,
        )

    async def build_context_for_document_question(
        self,
        session: AsyncSession,
        question: str,
        user_id: int,
        document_id: int,
    ) -> RAGAnswerContext:
        question_embedding = await self.llm_client.create_embedding(question)
        matches = await ChunkRepository.search_relevant_in_document(
            session=session,
            question_embedding=question_embedding,
            user_id=user_id,
            document_id=document_id,
            top_k=self.settings.max_context_chunks,
        )

        selected_chunks: list[ChunkMatch] = []
        total_chars = 0
        for match in matches:
            if total_chars + len(match.chunk_text) > self.settings.max_context_chars:
                break
            selected_chunks.append(match)
            total_chars += len(match.chunk_text)

        context_blocks: list[str] = []
        sources: list[dict[str, Any]] = []
        for index, match in enumerate(selected_chunks, start=1):
            block = f"[Фрагмент {index} | document_id={document_id} | score={match.score:.3f}]\n{match.chunk_text}"
            context_blocks.append(block)
            sources.append(self._source_from_match(match))

        return RAGAnswerContext(
            chunks=selected_chunks,
            context_text="\n\n".join(context_blocks),
            sources=sources,
        )

    async def build_latest_user_file_context(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> RAGAnswerContext:
        matches = await ChunkRepository.latest_user_chunks(
            session=session,
            user_id=user_id,
            limit=self.settings.max_context_chunks,
        )
        context_blocks: list[str] = []
        sources: list[dict[str, Any]] = []
        total_chars = 0

        for index, match in enumerate(matches, start=1):
            if total_chars + len(match.chunk_text) > self.settings.max_context_chars:
                break
            context_blocks.append(f"[Фрагмент {index} | latest-user-file]\n{match.chunk_text}")
            sources.append(self._source_from_match(match))
            total_chars += len(match.chunk_text)

        return RAGAnswerContext(
            chunks=matches[: len(context_blocks)],
            context_text="\n\n".join(context_blocks),
            sources=sources,
        )

    @staticmethod
    def _source_from_match(match: ChunkMatch) -> dict[str, Any]:
        metadata = match.metadata or {}
        return {
            "document_id": match.document_id,
            "document_title": metadata.get("document_title") or match.document_title,
            "original_filename": metadata.get("original_filename") or match.original_filename,
            "module_number": metadata.get("module_number"),
            "module_title": metadata.get("module_title"),
            "lesson_key": metadata.get("lesson_key"),
            "lesson_date": metadata.get("lesson_date"),
            "material_type": metadata.get("material_type"),
            "tags": metadata.get("tags") or [],
            "chunk_index": metadata.get("chunk_index"),
            "score": round(match.score, 3),
        }
