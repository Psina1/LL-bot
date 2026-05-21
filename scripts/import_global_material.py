from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path

from sqlalchemy import and_, select

from app.db.init_db import init_db
from app.db.models import Document, VisibilityEnum
from app.db.repositories import ProgramLessonRepository
from app.db.session import SessionLocal
from app.services.container import create_container
from app.services.document_service import SavedUpload


async def import_global_material(
    source_path: Path,
    title: str,
    lesson_key: str,
    material_type: str,
    force_duplicate: bool = False,
) -> int | None:
    await init_db()
    container = create_container()
    source_path = source_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    extension = container.document_service.validate_file(source_path.name, source_path.stat().st_size)
    target_dir = container.settings.materials_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / source_path.name

    async with SessionLocal() as session:
        lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if lesson is None:
            raise ValueError(f"Unknown lesson_key: {lesson_key}")

        if not force_duplicate:
            result = await session.execute(
                select(Document).where(
                    and_(
                        Document.visibility == VisibilityEnum.global_,
                        Document.original_filename == source_path.name,
                        Document.lesson_key == lesson_key,
                        Document.material_type == material_type,
                    )
                )
            )
            existing_document = result.scalar_one_or_none()
            if existing_document is not None:
                print(f"already_imported_document_id={existing_document.id}")
                return existing_document.id

        shutil.copy2(source_path, target_path)
        saved_upload = SavedUpload(
            path=target_path,
            original_filename=source_path.name,
            extension=extension,
        )
        tags = [
            f"lesson_key:{lesson.lesson_key}",
            f"block:{lesson.block_key}",
            f"type:{material_type}",
            "source:script_import",
        ]
        document = await container.document_service.create_and_index_document(
            session=session,
            title=title,
            saved_upload=saved_upload,
            visibility="global",
            owner_user_id=None,
            module_number=lesson.lesson_number,
            module_title=lesson.block_title,
            lesson_key=lesson.lesson_key,
            lesson_date=lesson.date_start,
            material_type=material_type,
            tags=tags,
        )
        print(f"imported_document_id={document.id}")
        print(f"status={document.status.value}")
        return document.id


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import and index a global training material.")
    parser.add_argument("source_path", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--lesson-key", required=True)
    parser.add_argument("--material-type", default="lesson_material")
    parser.add_argument("--force-duplicate", action="store_true")
    args = parser.parse_args()

    await import_global_material(
        source_path=args.source_path,
        title=args.title,
        lesson_key=args.lesson_key,
        material_type=args.material_type,
        force_duplicate=args.force_duplicate,
    )


if __name__ == "__main__":
    asyncio.run(main())
