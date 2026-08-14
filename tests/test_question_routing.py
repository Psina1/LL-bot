from __future__ import annotations

import unittest

from app.services.question_routing import route_direct_question


class QuestionRoutingTests(unittest.TestCase):
    def test_voice_capability_question(self) -> None:
        route = route_direct_question("Привет! Я могу общаться с тобой голосом?")
        self.assertIsNotNone(route)
        self.assertEqual(route.mode, "bot_voice_capabilities")

    def test_voice_message_question(self) -> None:
        route = route_direct_question("Можно тебе отправить голосовое сообщение?")
        self.assertIsNotNone(route)
        self.assertEqual(route.mode, "bot_voice_capabilities")

    def test_general_capabilities_question(self) -> None:
        route = route_direct_question("Что ты умеешь?")
        self.assertIsNotNone(route)
        self.assertEqual(route.mode, "bot_capabilities")

    def test_obvious_off_topic_question(self) -> None:
        route = route_direct_question("Расскажи анекдот")
        self.assertIsNotNone(route)
        self.assertEqual(route.mode, "off_topic")

    def test_program_question_stays_in_rag(self) -> None:
        self.assertIsNone(route_direct_question("О чём говорил Рахманов на втором занятии?"))

    def test_voice_of_customer_is_not_bot_capability(self) -> None:
        self.assertIsNone(
            route_direct_question("Как применить метод голоса клиента к моему проекту?")
        )

    def test_project_question_stays_in_rag(self) -> None:
        self.assertIsNone(
            route_direct_question("Какие риски есть у моего проекта?")
        )


if __name__ == "__main__":
    unittest.main()
