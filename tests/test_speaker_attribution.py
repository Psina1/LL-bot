from __future__ import annotations

import re
import unittest

from app.rag.speaker_attribution import (
    enforce_unconfirmed_speaker_answer,
    neutralize_anonymous_authors,
    parse_lesson_speakers,
    requested_speaker,
    requests_direct_quotes,
    requests_general_discussion,
    split_transcript_by_speaker,
    verified_quote_answer,
)


class SpeakerAttributionTests(unittest.TestCase):
    def test_parse_multiple_lesson_speakers(self) -> None:
        self.assertEqual(
            parse_lesson_speakers("Ю. Макарова, С. Сафронов"),
            ["Ю. Макарова", "С. Сафронов"],
        )

    def test_requested_speaker_matches_surname(self) -> None:
        self.assertEqual(
            requested_speaker(
                "Что говорил Сафронов на занятии?",
                ["Ю. Макарова", "С. Сафронов"],
            ),
            "С. Сафронов",
        )

    def test_requested_speaker_matches_inflected_surname(self) -> None:
        self.assertEqual(
            requested_speaker(
                "Какие основные тезисы Семенова прозвучали на занятии?",
                ["Александр Семенов"],
            ),
            "Александр Семенов",
        )
        self.assertEqual(
            requested_speaker(
                "Что было важным в выступлении Макаровой?",
                ["Ю. Макарова"],
            ),
            "Ю. Макарова",
        )

    def test_detects_question_about_other_speakers(self) -> None:
        self.assertTrue(requests_general_discussion("О чем говорили остальные участники?"))
        self.assertTrue(requests_general_discussion("Какие мысли прозвучали в общем обсуждении?"))
        self.assertFalse(requests_general_discussion("О чем говорил Александр Семенов?"))

    def test_detects_direct_quote_request(self) -> None:
        self.assertTrue(requests_direct_quotes("Приведи подтвержденные цитаты Семенова"))
        self.assertTrue(requests_direct_quotes("Как он сформулировал это дословно?"))
        self.assertFalse(requests_direct_quotes("Перескажи тезисы Семенова"))

    def test_verified_quotes_are_copied_from_chunks(self) -> None:
        chunks = [
            "Стратегия помогает руководителю уйти от ручного управления. "
            "Для этого необходимо договориться о фокусе команды.",
        ]
        answer = verified_quote_answer(chunks, "Александр Семенов")
        quoted = re.findall(r"«([^»]+)»", answer)
        self.assertEqual(len(quoted), 2)
        self.assertTrue(all(quote in chunks[0] for quote in quoted))

    def test_transcript_chunks_do_not_cross_speakers(self) -> None:
        chunks = split_transcript_by_speaker(
            "Александр Семенов Стратегия помогает уйти от ручного управления.\n"
            "SPEAKER_01 А как это применить в команде?",
            ["Александр Семенов"],
        )
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].speaker_name, "Александр Семенов")
        self.assertEqual(chunks[0].speaker_status, "confirmed")
        self.assertIsNone(chunks[1].speaker_name)
        self.assertEqual(chunks[1].speaker_status, "unknown")

    def test_unknown_transcript_stays_anonymous(self) -> None:
        chunks = split_transcript_by_speaker(
            "[Неизвестный говорящий] Обсуждались финансовые показатели.",
            ["Александр Семенов"],
        )
        self.assertEqual(chunks[0].speaker_status, "unknown")
        self.assertIsNone(chunks[0].speaker_name)

    def test_adjacent_unknown_turns_are_coalesced(self) -> None:
        chunks = split_transcript_by_speaker(
            "SPEAKER_01 Первая мысль.\nSPEAKER_02 Вторая мысль.",
            ["Александр Семенов"],
        )
        self.assertEqual(len(chunks), 1)
        self.assertIn("Первая мысль", chunks[0].chunk_text)
        self.assertIn("Вторая мысль", chunks[0].chunk_text)

    def test_initial_and_surname_catalog_matches_full_transcript_name(self) -> None:
        chunks = split_transcript_by_speaker(
            "Александр Семенов\nСтратегия помогает уйти от ручного управления.",
            ["Семенов А."],
        )
        self.assertEqual(chunks[0].speaker_name, "Семенов А.")
        self.assertEqual(chunks[0].speaker_status, "confirmed")

    def test_neutralizes_unconfirmed_author_role(self) -> None:
        self.assertEqual(
            neutralize_anonymous_authors("Участники согласились проверить гипотезу."),
            "В общем обсуждении была отмечена договорённость проверить гипотезу.",
        )

    def test_unconfirmed_speaker_answer_gets_deterministic_refusal(self) -> None:
        answer = enforce_unconfirmed_speaker_answer(
            "Семенов подчеркнул важность фокуса. Участники согласились проверить гипотезу.",
            "Александр Семенов",
        )
        self.assertIn("подтвердить, что именно говорил Александр Семенов, нельзя", answer)
        self.assertNotIn("Семенов подчеркнул", answer)
        self.assertNotIn("Участники", answer)


if __name__ == "__main__":
    unittest.main()
