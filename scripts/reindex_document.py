from __future__ import annotations

import argparse
import asyncio

from app.db.init_db import init_db
from app.db.repositories import DocumentRepository
from app.db.session import SessionLocal
from app.services.container import create_container


async def reindex_document(document_id: int) -> int:
    await init_db()
    container = create_container()

    async with SessionLocal() as session:
        document = await DocumentRepository.get_by_id(session, document_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")

        chunk_count = await container.rag_service.index_document(session=session, document=document)
        print(f"document_id={document.id}")
        print(f"title={document.title}")
        print(f"status=ready")
        print(f"chunks={chunk_count}")
        return chunk_count


async def main() -> None:
    parser = argparse.ArgumentParser(description="Reindex one document by id.")
    parser.add_argument("document_id", type=int)
    args = parser.parse_args()

    await reindex_document(args.document_id)


if __name__ == "__main__":
    asyncio.run(main())
