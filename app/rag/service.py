from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, DocumentStatusEnum
from app.db.repositories import ChunkMatch, ChunkRepository, DocumentRepository
from app.file_processing.extractors import extract_text_from_file
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
            text = extract_text_from_file(file_path)
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
                            "material_type": document.material_type,
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
            "material_type": metadata.get("material_type"),
            "chunk_index": metadata.get("chunk_index"),
            "score": round(match.score, 3),
        }
