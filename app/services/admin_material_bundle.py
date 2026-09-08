from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MATERIAL_KIND_LABELS = {
    "lesson_material": "материалы и презентации",
    "summary": "саммари",
    "homework": "домашнее задание",
    "transcript": "транскрипция для ИИ",
    "video": "видео",
    "podcast": "подкаст",
}

DOCUMENT_KINDS = {"lesson_material", "summary", "homework", "transcript"}
MEDIA_KINDS = {"video", "podcast"}
CHECKLIST_KINDS = tuple(MATERIAL_KIND_LABELS)


@dataclass(frozen=True)
class MaterialTypeDetection:
    kind: str
    confidence: str
    reason: str


def detect_material_type(
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    telegram_kind: str | None = None,
    text: str | None = None,
) -> MaterialTypeDetection:
    name = (filename or "").lower().replace("ё", "е")
    mime = (mime_type or "").lower()
    body = (text or "").lower().replace("ё", "е")
    extension = Path(name).suffix.lower()

    if telegram_kind == "video" or mime.startswith("video/") or extension in {".mp4", ".mov", ".m4v", ".webm"}:
        return MaterialTypeDetection("video", "high", "формат видеофайла")
    if telegram_kind in {"audio", "voice"} or mime.startswith("audio/") or extension in {".mp3", ".m4a", ".wav", ".ogg"}:
        return MaterialTypeDetection("podcast", "high", "формат аудиофайла")
    if extension in {".vtt", ".srt", ".ott"} or any(marker in name for marker in ["транскрип", "расшифров", "subtitles"]):
        return MaterialTypeDetection("transcript", "high", "расширение или название транскрипции")
    if any(marker in name for marker in ["саммари", "summary", "конспект", "выжимк"]):
        return MaterialTypeDetection("summary", "high", "название файла")
    if any(marker in name for marker in ["домаш", "homework", "дз_"]) or body.startswith("домашнее задание"):
        return MaterialTypeDetection("homework", "high", "название или текст домашнего задания")
    if body and any(marker in body[:160] for marker in ["саммари", "конспект", "краткое содержание"]):
        return MaterialTypeDetection("summary", "medium", "начало текста")
    return MaterialTypeDetection("lesson_material", "medium", "безопасный тип по умолчанию")


def allowed_kinds_for_payload(*, telegram_kind: str | None, detected_kind: str) -> tuple[str, ...]:
    if telegram_kind in {"video", "audio", "voice"} or detected_kind in MEDIA_KINDS:
        return ("video", "podcast")
    return ("lesson_material", "summary", "homework", "transcript")


def checklist_statuses(counts: dict[str, int], not_required: set[str]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for kind in CHECKLIST_KINDS:
        if counts.get(kind, 0) > 0:
            statuses[kind] = "uploaded"
        elif kind in not_required:
            statuses[kind] = "not_required"
        else:
            statuses[kind] = "missing"
    return statuses


def checklist_setting_key(lesson_key: str) -> str:
    return f"material_checklist_not_required:{lesson_key}"
