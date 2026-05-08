from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    chunk_index: int
    chunk_text: str


def split_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[TextChunk]:
    if not text.strip():
        return []

    sentences = _split_into_sentences(text)
    chunks: list[TextChunk] = []
    current = ""
    chunk_index = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip()
            continue

        if current:
            chunks.append(TextChunk(chunk_index=chunk_index, chunk_text=current))
            chunk_index += 1

        if len(sentence) > chunk_size:
            for part in _force_split(sentence, chunk_size):
                chunks.append(TextChunk(chunk_index=chunk_index, chunk_text=part))
                chunk_index += 1
            current = ""
        else:
            current = sentence

    if current:
        chunks.append(TextChunk(chunk_index=chunk_index, chunk_text=current))

    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    overlapped_chunks: list[TextChunk] = []
    for idx, chunk in enumerate(chunks):
        if idx == 0:
            overlapped_chunks.append(chunk)
            continue
        prev_tail = chunks[idx - 1].chunk_text[-overlap:]
        merged = f"{prev_tail}\n{chunk.chunk_text}".strip()
        overlapped_chunks.append(TextChunk(chunk_index=chunk.chunk_index, chunk_text=merged))
    return overlapped_chunks


def _split_into_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return re.split(r"(?<=[.!?])\s+", text)


def _force_split(text: str, chunk_size: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks
