from app.services.lesson_conversation import (
    asks_for_speaker_lesson_list,
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
