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
    verified_quote_answer_from_selection,
)


class SpeakerAttributionTests(unittest.TestCase):
    def test_parse_multiple_lesson_speakers(self) -> None:
        self.assertEqual(
            parse_lesson_speakers("Ю. Макарова, С. Сафронов"),
            ["Ю. Макарова", "С. Сафронов"],
        )

    def test_parse_adjacent_surname_initial_speakers(self) -> None:
        self.assertEqual(
            parse_lesson_speakers("Берштейн Т. Рахманов А."),
            ["Берштейн Т.", "Рахманов А."],
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
        self.assertTrue(requests_direct_quotes("Дай цетаты плиз"))
        self.assertTrue(requests_direct_quotes("Как он сформулировал это дословно?"))
        self.assertFalse(requests_direct_quotes("Перескажи тезисы Семенова"))

    def test_verified_quotes_are_copied_from_chunks(self) -> None:
        chunks = [
            "Стратегия помогает руководителю уйти от ручного управления.",
            "Для этого необходимо договориться о фокусе команды.",
        ]
        answer = verified_quote_answer(chunks, "Александр Семенов", "Приведи цитаты Семенова")
        quoted = re.findall(r"\d+\. «([^»]+)»", answer)
        self.assertEqual(len(quoted), 2)
        self.assertTrue(all(any(quote in chunk for chunk in chunks) for quote in quoted))

    def test_verified_quotes_prefer_question_topic_and_distinct_chunks(self) -> None:
        chunks = [
            "Стратегия требует осознанного выбора и отказа от лишних направлений. "
            "Мы также обсуждали встречу с коллегами.",
            "Для работающей стратегии необходимо определить измеримые цели.",
        ]
        answer = verified_quote_answer(
            chunks,
            "Александр Семенов",
            "Приведи цитаты Семенова о стратегии",
        )
        quoted = re.findall(r"\d+\. «([^»]+)»", answer)
        self.assertEqual(len(quoted), 2)
        self.assertTrue(all("стратег" in quote.casefold() for quote in quoted))

    def test_verified_quotes_ignore_lesson_reference_words_and_filler_fragments(self) -> None:
        chunks = [
            "Же возвращаюсь к тому, что мы сегодня обсуждали в начале занятия.",
            "Прибыль показывает, насколько устойчиво бизнес превращает выручку клиентов в финансовый результат.",
            "А у нас сегодня не будет группового занятия.",
        ]
        answer = verified_quote_answer(
            chunks,
            "С. Сафронов",
            "Дай цитаты Сафронова с первого его занятия",
        )
        self.assertIn("Прибыль показывает", answer)
        self.assertNotIn("возвращаюсь", answer)
        self.assertNotIn("не будет группового", answer)

    def test_verified_quotes_only_return_requested_topic(self) -> None:
        chunks = [
            "Сегодня мы подробно обсуждаем структуру учебного занятия.",
            "Бизнес создаёт деньги, когда ценность для клиента превышает понесённые расходы.",
            "Будущее КОРУСа зависит от качества управленческих решений и устойчивости бизнес-модели.",
        ]
        answer = verified_quote_answer(
            chunks,
            "С. Сафронов",
            "Есть цитаты о бизнесе, деньгах и будущем КОРУСа?",
        )
        self.assertNotIn("структуру учебного занятия", answer)
        self.assertIn("Бизнес создаёт деньги", answer)
        self.assertIn("Будущее КОРУСа", answer)

    def test_model_selected_quotes_must_be_verbatim_and_topic_relevant(self) -> None:
        chunks = [
            "Бизнес создаёт деньги, когда ценность для клиента превышает понесённые расходы.",
            "Сегодня мы обсуждали расписание и формат следующего занятия.",
        ]
        selection = (
            '{"quotes":['
            '"Бизнес создаёт деньги, когда ценность для клиента превышает понесённые расходы.",'
            '"Сегодня мы обсуждали расписание и формат следующего занятия.",'
            '"Бизнес создаёт большую прибыль."]}'
        )
        answer = verified_quote_answer_from_selection(
            selection,
            chunks,
            "С. Сафронов",
            "Дай цитаты о бизнесе и деньгах",
        )
        self.assertIn("Бизнес создаёт деньги", answer)
        self.assertNotIn("расписание", answer)
        self.assertNotIn("большую прибыль", answer)

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

    def test_zoom_colon_labels_classify_known_and_other_speakers(self) -> None:
        chunks = split_transcript_by_speaker(
            "Sergey Safronov: Стратегия связана с финансовыми решениями.\n"
            "Анна Усикова: Задаёт организационный вопрос.",
            ["С. Сафронов"],
        )
        self.assertEqual(chunks[0].speaker_name, "С. Сафронов")
        self.assertEqual(chunks[0].speaker_status, "confirmed")
        self.assertIsNone(chunks[1].speaker_name)
        self.assertEqual(chunks[1].speaker_status, "unknown")

    def test_timestamp_labels_classify_known_and_other_speakers(self) -> None:
        chunks = split_transcript_by_speaker(
            "[00:00:03] Татьяна Кульбякина Открывает встречу.\n"
            "[00:01:12] Александр Рахманов Рассказывает о консалтинге.",
            ["Рахманов А."],
        )
        self.assertIsNone(chunks[0].speaker_name)
        self.assertEqual(chunks[0].speaker_status, "unknown")
        self.assertEqual(chunks[1].speaker_name, "Рахманов А.")
        self.assertEqual(chunks[1].speaker_status, "confirmed")

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
