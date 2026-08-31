from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping


ACTIVE_LESSON_CONTEXT_TTL = timedelta(minutes=45)


def has_fresh_active_lesson_context(
    data: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether the in-memory lesson context is still safe to reuse."""
    if not data.get("last_lesson_key") and not data.get("last_lesson_date"):
        return False

    raw_timestamp = data.get("last_lesson_context_at")
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        return False
    try:
        timestamp = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    current_time = now or datetime.now(timezone.utc)
    return timedelta(0) <= current_time - timestamp <= ACTIVE_LESSON_CONTEXT_TTL


def is_contextual_lesson_followup(text_value: str | None) -> bool:
    """Recognise short references without guessing that a user started a new topic."""
    text = (text_value or "").strip().lower().replace("ё", "е")
    if not text:
        return False

    if any(
        marker in text
        for marker in (
            "по всем",
            "все занятия",
            "все материалы",
            "все видео",
            "все саммари",
            "в целом по программе",
            "другое занятие",
            "новая тема",
        )
    ):
        return False

    explicit_references = (
        "этого занятия",
        "этом занятии",
        "это занятие",
        "этой встречи",
        "этой встрече",
        "этого урока",
        "этом уроке",
        "по нему",
        "по ней",
        "по этому",
        "по этой",
        "об этом",
        "про это",
        "из этого",
        "оттуда",
    )
    if any(marker in text for marker in explicit_references):
        return True

    return text.startswith(("а что там", "что там", "а про ", "а по ", "а как там"))
