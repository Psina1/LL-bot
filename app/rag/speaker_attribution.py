from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.chunking import split_text


UNKNOWN_SPEAKER_LABELS = (
    "неизвестный говорящий",
    "неизвестный спикер",
    "unknown speaker",
)
TECHNICAL_SPEAKER_RE = re.compile(r"\bSPEAKER[_\s-]?\d{1,3}\b", re.IGNORECASE)
PERSON_QUESTION_RE = re.compile(
    r"\b(говорил[аи]?|сказал[аи]?|рассказывал[аи]?|обсуждал[аи]?|отметил[аи]?|"
    r"подчеркнул[аи]?|цитат[а-я]*|тезис[а-я]*|мысл[а-я]*|выступлен[а-я]*)\b",
    re.IGNORECASE,
)
GENERAL_DISCUSSION_RE = re.compile(
    r"\b(остальн\w*|друг\w+ участник\w*|общ\w+ обсужден\w*|неизвестн\w+ говорящ\w*)\b",
    re.IGNORECASE,
)
DIRECT_QUOTE_RE = re.compile(
    r"\b(цитат[а-я]*|дословн[а-я]*|точн[а-я]+ формулировк[а-я]*)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class SpeakerChunk:
    chunk_index: int
    chunk_text: str
    speaker_name: str | None
    speaker_status: str


def parse_lesson_speakers(speaker_field: str | None) -> list[str]:
    if not speaker_field:
        return []
    values = re.split(r"[,;\n]+|\s+и\s+", speaker_field)
    return [value.strip() for value in values if value.strip()]


def requested_speaker(question: str, speakers: list[str]) -> str | None:
    if not PERSON_QUESTION_RE.search(question):
        return None
    question_tokens = _normalize(question).split()
    for speaker in speakers:
        tokens = [token for token in _normalize(speaker).split() if len(token) >= 3]
        if any(
            _matches_inflected_name(token, question_token)
            for token in tokens
            for question_token in question_tokens
        ):
            return speaker
    return None


def requests_general_discussion(question: str) -> bool:
    return bool(GENERAL_DISCUSSION_RE.search(question))


def requests_direct_quotes(question: str) -> bool:
    return bool(DIRECT_QUOTE_RE.search(question))


def verified_quote_answer(
    chunk_texts: list[str],
    requested_name: str,
    question: str = "",
    max_quotes: int = 5,
) -> str:
    candidates: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    keywords = _quote_keywords(question, requested_name)
    for chunk_rank, chunk_text in enumerate(chunk_texts):
        for sentence_rank, sentence in enumerate(re.split(r"(?<=[.!?])\s+", chunk_text.strip())):
            sentence = sentence.strip()
            normalized = _normalize(sentence)
            if (
                not 35 <= len(sentence) <= 500
                or normalized in seen
                or sentence.startswith("...")
            ):
                continue
            seen.add(normalized)
            relevance = sum(
                1
                for keyword in keywords
                if any(token.startswith(keyword) for token in normalized.split())
            )
            candidates.append((-relevance, chunk_rank, sentence_rank, sentence))

    candidates.sort()
    quotes: list[str] = []
    used_chunks: set[int] = set()
    for negative_relevance, chunk_rank, _, sentence in candidates:
        if chunk_rank in used_chunks:
            continue
        if keywords and -negative_relevance == 0 and quotes:
            continue
        used_chunks.add(chunk_rank)
        quotes.append(sentence)
        if len(quotes) >= max_quotes:
            break

    if not quotes:
        return (
            f"В подтверждённых фрагментах спикера «{requested_name}» не нашлось цельных фраз, "
            "которые можно безопасно привести дословно."
        )

    rendered_quotes = "\n\n".join(f"{index}. «{quote}»" for index, quote in enumerate(quotes, start=1))
    return (
        f"Дословные фрагменты спикера «{requested_name}» из автоматической транскрипции "
        f"(без таймкодов):\n\n{rendered_quotes}"
    )


def _quote_keywords(question: str, requested_name: str) -> set[str]:
    ignored = {
        "приведи", "подтвержденные", "подтверждённые", "цитаты", "цитату",
        "дословно", "точная", "точную", "формулировка", "формулировку",
    }
    name_tokens = [token for token in _normalize(requested_name).split() if len(token) >= 3]
    keywords: set[str] = set()
    for token in _normalize(question).split():
        if len(token) < 5 or token in ignored:
            continue
        if any(_matches_inflected_name(name_token, token) for name_token in name_tokens):
            continue
        keywords.add(token[:7])
    return keywords


def split_transcript_by_speaker(
    text: str,
    known_speakers: list[str],
    chunk_size: int = 1200,
) -> list[SpeakerChunk]:
    labels = _speaker_labels(known_speakers)
    if not labels:
        return _unattributed_chunks(text, chunk_size)

    marker_re = re.compile("(" + "|".join(labels) + ")", re.IGNORECASE | re.MULTILINE)
    matches = list(marker_re.finditer(text))
    if not matches:
        return _unattributed_chunks(text, chunk_size)

    segments: list[tuple[str | None, str, str]] = []
    prefix = text[: matches[0].start()].strip()
    if prefix:
        _append_or_merge_segment(segments, None, "unattributed", prefix)

    for index, match in enumerate(matches):
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment_text = text[match.end() : segment_end].strip()
        if not segment_text:
            continue
        label = match.group(0)
        speaker_name, status = _classify_label(label, known_speakers)
        _append_or_merge_segment(segments, speaker_name, status, segment_text)

    chunks: list[SpeakerChunk] = []
    chunk_index = 0
    for speaker_name, status, segment_text in segments:
        chunk_index = _append_segment_chunks(
            chunks, chunk_index, segment_text, speaker_name, status, chunk_size
        )
    return chunks


def anonymous_attribution_notice(requested_name: str) -> str:
    return (
        f"В транскрипции голоса не идентифицированы, поэтому подтвердить, "
        f"что именно говорил {requested_name}, нельзя."
    )


def enforce_unconfirmed_speaker_answer(text: str, requested_name: str) -> str:
    surname_tokens = [token for token in _normalize(requested_name).split() if len(token) >= 3]
    speech_re = re.compile(
        r"\b(говорил[аи]?|сказал[аи]?|отметил[аи]?|подчеркнул[аи]?|обсуждал[аи]?)\b",
        re.IGNORECASE,
    )
    safe_sentences: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        normalized = _normalize(sentence)
        if speech_re.search(sentence) and any(token in normalized for token in surname_tokens):
            continue
        safe_sentences.append(sentence)
    remainder = neutralize_anonymous_authors(" ".join(safe_sentences)).strip()
    notice = anonymous_attribution_notice(requested_name)
    if remainder.casefold().startswith(notice.casefold()):
        return remainder
    if not remainder:
        return notice
    return f"{notice}\n\nВ общем обсуждении:\n{remainder}"


def neutralize_anonymous_authors(text: str) -> str:
    replacements = (
        (r"\b(?:Участники|Коллеги|Эксперты)\s+согласились", "В общем обсуждении была отмечена договорённость"),
        (r"\b(?:Участники|Коллеги|Эксперты)\s+(?:говорили|обсуждали)", "В общем обсуждении рассматривалось"),
        (r"\b(?:Участники|Коллеги|Эксперты)\s+(?:отметили|подчеркнули)", "В общем обсуждении отмечалось"),
    )
    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _speaker_labels(known_speakers: list[str]) -> list[str]:
    labels = [
        r"^[ \t]*\[?Неизвестный говорящий\]?",
        r"^[ \t]*\[?Неизвестный спикер\]?",
        rf"^[ \t]*{TECHNICAL_SPEAKER_RE.pattern}",
    ]
    for speaker in known_speakers:
        if len(speaker.strip()) < 3:
            continue
        labels.append(rf"^[ \t]*{re.escape(speaker)}(?=\s|$)")
        surname = _speaker_surname(speaker)
        if surname:
            full_word = r"[А-ЯЁ][а-яё-]+"
            labels.append(
                rf"^[ \t]*(?:{full_word}[ \t]+{re.escape(surname)}|"
                rf"{re.escape(surname)}[ \t]+{full_word})(?=\s|$)"
            )
    return labels


def _classify_label(label: str, known_speakers: list[str]) -> tuple[str | None, str]:
    normalized = _normalize(label)
    if any(value in normalized for value in UNKNOWN_SPEAKER_LABELS) or TECHNICAL_SPEAKER_RE.search(label):
        return None, "unknown"
    for speaker in known_speakers:
        if _normalize(speaker) == normalized:
            return speaker, "confirmed"
        surname = _speaker_surname(speaker)
        if surname and _normalize(surname) in normalized.split():
            return speaker, "confirmed"
    return None, "unattributed"


def _append_segment_chunks(
    output: list[SpeakerChunk],
    start_index: int,
    text: str,
    speaker_name: str | None,
    speaker_status: str,
    chunk_size: int,
) -> int:
    index = start_index
    for chunk in split_text(text, chunk_size=chunk_size, overlap=0):
        output.append(
            SpeakerChunk(
                chunk_index=index,
                chunk_text=chunk.chunk_text,
                speaker_name=speaker_name,
                speaker_status=speaker_status,
            )
        )
        index += 1
    return index


def _append_or_merge_segment(
    segments: list[tuple[str | None, str, str]],
    speaker_name: str | None,
    speaker_status: str,
    text: str,
) -> None:
    if segments and segments[-1][0] == speaker_name and segments[-1][1] == speaker_status:
        previous_name, previous_status, previous_text = segments[-1]
        segments[-1] = (previous_name, previous_status, f"{previous_text}\n{text}")
        return
    segments.append((speaker_name, speaker_status, text))


def _unattributed_chunks(text: str, chunk_size: int) -> list[SpeakerChunk]:
    return [
        SpeakerChunk(chunk.chunk_index, chunk.chunk_text, None, "unattributed")
        for chunk in split_text(text, chunk_size=chunk_size, overlap=0)
    ]


def _normalize(value: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", value.casefold()).strip()


def _speaker_surname(speaker: str) -> str | None:
    tokens = re.findall(r"[А-ЯЁа-яё-]+", speaker)
    candidates = [token for token in tokens if len(token) >= 3]
    if not candidates:
        return None
    return max(candidates, key=len)


def _matches_inflected_name(catalog_token: str, question_token: str) -> bool:
    if catalog_token == question_token:
        return True

    # Russian surnames and first names commonly gain case endings in a question:
    # "Семенов" -> "Семенова", "Макарова" -> "Макаровой".
    stem = catalog_token[:-1] if catalog_token.endswith(("а", "я")) else catalog_token
    return len(stem) >= 5 and question_token.startswith(stem)
