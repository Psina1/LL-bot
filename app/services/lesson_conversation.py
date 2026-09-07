from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from typing import Mapping


LESSON_CONTEXT_TTL = timedelta(minutes=45)


def match_known_speaker_marker(text_value: str | None, markers: list[str]) -> str | None:
    text = (text_value or "").casefold().replace("ё", "е")
    normalized_markers = [marker.casefold().replace("ё", "е") for marker in markers]
    for marker in normalized_markers:
        if marker in text:
            return marker

    words = re.findall(r"[a-zа-я-]{5,}", text)
    for marker in normalized_markers:
        if " " in marker:
            continue
        for word in words:
            if abs(len(word) - len(marker)) <= 2 and SequenceMatcher(None, word, marker).ratio() >= 0.8:
                return marker
    return None


def _has_approximate_word(text: str, expected: tuple[str, ...]) -> bool:
    words = re.findall(r"[a-zа-я-]{5,}", text)
    return any(
        abs(len(word) - len(target)) <= 2 and SequenceMatcher(None, word, target).ratio() >= 0.75
        for word in words
        for target in expected
    )


def has_fresh_lesson_context(
    data: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> bool:
    raw_timestamp = data.get("conversation_lesson_context_at")
    if not data.get("conversation_lesson_key") or not isinstance(raw_timestamp, str):
        return False
    try:
        timestamp = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = (now or datetime.now(timezone.utc)) - timestamp
    return timedelta(0) <= age <= LESSON_CONTEXT_TTL


def asks_for_speaker_lesson_list(text_value: str | None) -> bool:
    text = (text_value or "").casefold().replace("ё", "е")
    if any(
        marker in text
        for marker in (
            "на каких занят",
            "на каком занят",
            "какие занятия",
            "какие встречи",
            "где был спикером",
            "где была спикером",
        )
    ):
        return True
    has_lesson_word = any(stem in text for stem in ("занят", "урок", "встреч"))
    asks_which = any(stem in text for stem in ("каки", "где", "переч", "спис"))
    has_speaker_role = any(stem in text for stem in ("спикер", "выступ", "вел", "вела"))
    return has_lesson_word and (asks_which or has_speaker_role)


def lesson_number_reference(text_value: str | None) -> int | None:
    text = (text_value or "").casefold().replace("ё", "е")
    match = re.search(r"(?:занят(?:ие|ии|ия)|урок(?:е|а)?)\s*(?:№|номер)?\s*(\d+)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\s*(?:-?(?:е|м|го|ое|ом))?\s*(?:занят\w*|урок\w*)", text)
    if match:
        return int(match.group(1))
    return None


def uses_remembered_lesson_context(text_value: str | None) -> bool:
    text = (text_value or "").casefold().replace("ё", "е").strip()
    if not text:
        return False
    if any(stem in text for stem in ("цит", "дослов", "формулиров")) or _has_approximate_word(
        text,
        ("цитаты", "цитату", "дословно"),
    ):
        return True
    if any(
        marker in text
        for marker in (
            "на этом занят",
            "об этом занят",
            "по этому занят",
            "этого занятия",
            "на этой встреч",
            "об этой встреч",
            "по занятию",
        )
    ):
        return True
    has_pronoun = bool(re.search(r"\b(он|она|они|спикер)\b", text))
    has_content_request = any(stem in text for stem in ("о чем", "о чом", "говор", "расказ", "рассказ", "тезис", "мысл"))
    return has_pronoun and has_content_request
