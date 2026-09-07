from __future__ import annotations

import re


def asks_for_speaker_lesson_list(text_value: str | None) -> bool:
    text = (text_value or "").casefold().replace("ё", "е")
    return any(
        marker in text
        for marker in (
            "на каких занят",
            "на каком занят",
            "какие занятия",
            "какие встречи",
            "где был спикером",
            "где была спикером",
        )
    )


def lesson_number_reference(text_value: str | None) -> int | None:
    text = (text_value or "").casefold().replace("ё", "е")
    match = re.search(r"(?:занят(?:ие|ии|ия)|урок(?:е|а)?)\s*(?:№|номер)?\s*(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def uses_remembered_lesson_context(text_value: str | None) -> bool:
    text = (text_value or "").casefold().replace("ё", "е").strip()
    if not text:
        return False
    if re.search(r"\b(цитат\w*|дословн\w*|точн\w* формулировк\w*)\b", text):
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
    has_content_request = any(
        marker in text
        for marker in ("о чем", "что говорил", "что говорила", "рассказывал", "рассказывала", "тезис", "мысл")
    )
    return has_pronoun and has_content_request
