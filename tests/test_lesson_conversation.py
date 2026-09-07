from datetime import datetime, timedelta, timezone

from app.services.lesson_conversation import (
    asks_for_speaker_lesson_list,
    has_fresh_lesson_context,
    lesson_number_reference,
    uses_remembered_lesson_context,
)


def test_detects_speaker_lesson_list_request() -> None:
    assert asks_for_speaker_lesson_list("На каких занятиях Макарова была спикером?")
    assert not asks_for_speaker_lesson_list("Что Макарова говорила на занятии?")


def test_extracts_lesson_number_reference() -> None:
    assert lesson_number_reference("Что говорила Макарова на занятии 4?") == 4
    assert lesson_number_reference("Расскажи про занятие №3") == 3
    assert lesson_number_reference("Что было на занятии?") is None


def test_detects_contextual_followups() -> None:
    assert uses_remembered_lesson_context("О чем она рассказывала на этом занятии?")
    assert uses_remembered_lesson_context("Приведи цитаты")
    assert uses_remembered_lesson_context("Приведи цитаты Макаровой по занятию")
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
