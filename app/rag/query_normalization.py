from __future__ import annotations

import re


DOMAIN_REPLACEMENTS = (
    (r"\bтайм\s+ту\s+к[еэ]ш\b", "Time to Cash"),
    (r"\bэиф\b", "экономика и финансы"),
    (r"\bдз\b", "домашнее задание"),
    (r"\bч[ео]\b", "что"),
    (r"\bшо\b", "что"),
)


def normalize_rag_query(question: str) -> str:
    normalized = " ".join(question.strip().split())
    for pattern, replacement in DOMAIN_REPLACEMENTS:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized
