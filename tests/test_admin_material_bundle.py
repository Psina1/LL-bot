from app.services.admin_material_bundle import (
    allowed_kinds_for_payload,
    checklist_statuses,
    detect_material_type,
)


def test_detects_video_and_audio_by_format() -> None:
    assert detect_material_type(filename="record.mp4", mime_type="video/mp4").kind == "video"
    assert detect_material_type(filename="podcast.mp3", mime_type="audio/mpeg").kind == "podcast"


def test_detects_transcripts_and_named_documents() -> None:
    assert detect_material_type(filename="meeting.vtt").kind == "transcript"
    assert detect_material_type(filename="транскрипция 25.08.docx").kind == "transcript"
    assert detect_material_type(filename="Саммари занятия.docx").kind == "summary"
    assert detect_material_type(filename="Домашнее задание 1.pdf").kind == "homework"


def test_unknown_document_defaults_to_lesson_material() -> None:
    result = detect_material_type(filename="presentation.pdf")
    assert result.kind == "lesson_material"
    assert result.confidence == "medium"


def test_text_homework_and_summary_are_detected() -> None:
    assert detect_material_type(text="Домашнее задание №1\nЧто нужно сделать").kind == "homework"
    assert detect_material_type(text="Саммари занятия\nОсновные мысли").kind == "summary"


def test_allowed_types_prevent_media_document_mixup() -> None:
    assert allowed_kinds_for_payload(telegram_kind="video", detected_kind="video") == ("video", "podcast")
    assert "transcript" in allowed_kinds_for_payload(telegram_kind="document", detected_kind="summary")


def test_checklist_distinguishes_all_three_states() -> None:
    statuses = checklist_statuses({"video": 1}, {"podcast"})
    assert statuses["video"] == "uploaded"
    assert statuses["podcast"] == "not_required"
    assert statuses["summary"] == "missing"
