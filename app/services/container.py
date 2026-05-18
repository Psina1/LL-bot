from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.llm.client import LLMClient
from app.rag.service import RAGService
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.notification_service import NotificationService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    llm_client: LLMClient
    rag_service: RAGService
    chat_service: ChatService
    document_service: DocumentService
    notification_service: NotificationService


def create_container() -> AppContainer:
    settings = get_settings()
    llm_client = LLMClient(settings=settings)
    rag_service = RAGService(settings=settings, llm_client=llm_client)
    chat_service = ChatService(settings=settings, llm_client=llm_client, rag_service=rag_service)
    document_service = DocumentService(settings=settings, rag_service=rag_service)
    notification_service = NotificationService(settings=settings)
    return AppContainer(
        settings=settings,
        llm_client=llm_client,
        rag_service=rag_service,
        chat_service=chat_service,
        document_service=document_service,
        notification_service=notification_service,
    )
