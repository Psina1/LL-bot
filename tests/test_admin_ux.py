from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from app.bot.handlers.lesson_feedback import build_lesson_display_numbers, second_score_question_text
from app.bot.keyboards.lesson_feedback import admin_feedback_lessons_keyboard
from app.bot.keyboards.reply import ADMIN_MENU_BUTTONS, all_reply_button_labels, main_menu_keyboard


class AdminUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lessons = [
            SimpleNamespace(
                lesson_key="kickoff",
                lesson_number=None,
                lesson_title="Кик-офф",
                date_start=None,
            ),
            SimpleNamespace(
                lesson_key="block_1_lesson_1",
                lesson_number=1,
                lesson_title="Занятие 1 первого блока",
                date_start=None,
            ),
            SimpleNamespace(
                lesson_key="block_1_lesson_2",
                lesson_number=2,
                lesson_title="Занятие 2 первого блока",
                date_start=None,
            ),
            SimpleNamespace(
                lesson_key="block_2_lesson_1",
                lesson_number=1,
                lesson_title="Занятие 1 второго блока",
                date_start=None,
            ),
        ]

    def test_admin_main_menu_has_director_dashboard_section(self) -> None:
        labels = [[button.text for button in row] for row in ADMIN_MENU_BUTTONS]
        self.assertEqual(
            labels,
            [
                ["Статус и аналитика", "Управление материалами"],
                ["Обратная связь", "Уведомления и сообщения"],
                ["Тексты и оформление"],
                ["Кабинет руководителя"],
                ["Главное меню"],
            ],
        )

    def test_main_menu_hides_director_dashboard_by_default(self) -> None:
        labels = [[button.text for button in row] for row in main_menu_keyboard().keyboard]
        self.assertNotIn(["Кабинет руководителя"], labels)

    def test_main_menu_can_show_director_dashboard(self) -> None:
        labels = [[button.text for button in row] for row in main_menu_keyboard(show_director_dashboard=True).keyboard]
        self.assertIn(["Кабинет руководителя"], labels)

    def test_new_admin_buttons_are_registered_as_navigation(self) -> None:
        labels = all_reply_button_labels()
        self.assertIn("Состояние бота", labels)
        self.assertIn("Добавить материал", labels)
        self.assertIn("Добавить видео/подкаст", labels)
        self.assertIn("Настройки автоуведомлений", labels)
        self.assertIn("Контакты поддержки", labels)

    def test_feedback_numbers_follow_full_program_order(self) -> None:
        numbers = build_lesson_display_numbers(self.lessons)
        self.assertNotIn("kickoff", numbers)
        self.assertEqual(numbers["block_1_lesson_1"], 1)
        self.assertEqual(numbers["block_1_lesson_2"], 2)
        self.assertEqual(numbers["block_2_lesson_1"], 3)

    def test_feedback_keyboard_uses_display_number_not_database_id(self) -> None:
        numbers = build_lesson_display_numbers(self.lessons)
        keyboard = admin_feedback_lessons_keyboard(self.lessons[1:], numbers)
        labels = [row[0].text for row in keyboard.inline_keyboard[:-1]]
        self.assertIn("Опрос №1", labels[0])
        self.assertIn("первого блока", labels[0])
        self.assertIn("Опрос №3", labels[2])

    def test_feedback_second_question_changes_for_group_practice(self) -> None:
        self.assertEqual(
            second_score_question_text(date(2026, 6, 16)),
            "Насколько полезной для тебя была работа в группе?",
        )
        self.assertEqual(
            second_score_question_text(date(2026, 6, 2)),
            "Насколько ты доволен выступлением эксперта(-ов)?",
        )


if __name__ == "__main__":
    unittest.main()
