from app.rag.query_normalization import normalize_rag_query


def test_normalizes_colloquial_domain_terms() -> None:
    normalized = normalize_rag_query("напомни чо было про тайм ту кеш и дз")
    assert normalized == "напомни что было про Time to Cash и домашнее задание"


def test_keeps_regular_question_readable() -> None:
    assert normalize_rag_query("Что обсуждали на занятии?") == "Что обсуждали на занятии?"
