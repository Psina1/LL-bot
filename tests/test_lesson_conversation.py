from datetime import datetime, timedelta, timezone

from app.services.lesson_conversation import (
    asks_for_speaker_lesson_list,
    has_fresh_lesson_context,
    lesson_number_reference,
    looks_like_lesson_overview,
    match_known_speaker_marker,
    uses_remembered_lesson_context,
)


def test_detects_speaker_lesson_list_request() -> None:
    assert asks_for_speaker_lesson_list("На каких занятиях Макарова была спикером?")
    assert not asks_for_speaker_lesson_list("Что Макарова говорила на занятии?")
    assert asks_for_speaker_lesson_list("на какиз занятиях выступала макарова")
    assert asks_for_speaker_lesson_list("какие уроки вела макарова")


def test_extracts_lesson_number_reference() -> None:
    assert lesson_number_reference("Что говорила Макарова на занятии 4?") == 4
    assert lesson_number_reference("Расскажи про занятие №3") == 3
    assert lesson_number_reference("Что было на занятии?") is None
    assert lesson_number_reference("а на 4м занятии что было") == 4


def test_detects_contextual_followups() -> None:
    assert uses_remembered_lesson_context("О чем она рассказывала на этом занятии?")
    assert uses_remembered_lesson_context("Приведи цитаты")
    assert uses_remembered_lesson_context("Приведи цитаты Макаровой по занятию")
    assert uses_remembered_lesson_context("дай цетаты плиз")
    assert uses_remembered_lesson_context("а што она там расказывала")
    assert not uses_remembered_lesson_context("Когда следующее занятие?")


def test_lesson_context_expires_after_45_minutes() -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    fresh = {
        "conversation_lesson_key": "s1_b4_l3",
        "conversation_lesson_context_at": (now - timedelta(minutes=10)).isoformat(),
    }
    stale = {
        "conversation_lesson_key": "s1_b4_l3",
        "conversation_lesson_context_at": (now - timedelta(minutes=46)).isoformat(),
    }
    assert has_fresh_lesson_context(fresh, now=now)
    assert not has_fresh_lesson_context(stale, now=now)


def test_speaker_marker_tolerates_small_typos() -> None:
    markers = ["макарова", "сафронов", "семенов"]
    assert match_known_speaker_marker("что говорила макарва", markers) == "макарова"
    assert match_known_speaker_marker("о чем сафрнов рассказывал", markers) == "сафронов"
    assert match_known_speaker_marker("когда следующее занятие", markers) is None


def test_colloquial_overview_request_is_detected() -> None:
    assert looks_like_lesson_overview("напомни чо было про тайм ту кеш")
    assert looks_like_lesson_overview("шо было на прошлом занятии")
    assert not looks_like_lesson_overview("дай видео занятия")
