from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.bot.handlers.lesson_feedback import build_lesson_display_numbers, second_score_question_text
from app.bot.keyboards.lesson_feedback import admin_feedback_lessons_keyboard
from app.bot.keyboards.reply import (
    ADMIN_MATERIALS_BUTTONS,
    ADMIN_MENU_BUTTONS,
    admin_program_season_keyboard,
    all_reply_button_labels,
    main_menu_keyboard,
    materials_program_keyboard,
)
from app.db.init_db import DEFAULT_PROGRAM_LESSONS


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

    def test_main_menu_encourages_free_text_instead_of_ask_button(self) -> None:
        labels = [[button.text for button in row] for row in main_menu_keyboard().keyboard]
        self.assertNotIn("Задать вопрос", [label for row in labels for label in row])

    def test_materials_menu_keeps_only_short_fallback_navigation(self) -> None:
        labels = [row[0].text for row in materials_program_keyboard().inline_keyboard]
        self.assertEqual(labels, ["Последнее занятие", "Выбрать занятие", "Главное меню"])

    def test_admin_materials_menu_uses_bundle_flow(self) -> None:
        labels = [button.text for row in ADMIN_MATERIALS_BUTTONS for button in row]
        self.assertIn("Материалы: сезон 1", labels)
        self.assertIn("Материалы: сезон 2", labels)
        self.assertIn("Чеклист занятия", labels)
        self.assertNotIn("Добавить материал", labels)

    def test_bundle_and_checklist_offer_both_seasons(self) -> None:
        labels = [button.text for row in admin_program_season_keyboard().keyboard for button in row]
        self.assertIn("Сезон 1. Бизнес", labels)
        self.assertIn("Сезон 2. Люди", labels)
        self.assertTrue({"Сезон 1. Бизнес", "Сезон 2. Люди"}.issubset(all_reply_button_labels()))

    def test_bundle_flow_is_not_hardcoded_to_first_season(self) -> None:
        source = Path("app/bot/handlers/main.py").read_text(encoding="utf-8")
        bundle_section = source[
            source.index('F.text == "Загрузить комплект занятия"') : source.index('F.text == "Сервисные действия"')
        ]
        self.assertIn("bundle_season_key", bundle_section)
        self.assertIn("checklist_season_key", bundle_section)
        self.assertNotIn('admin_blocks_keyboard("s1")', bundle_section)

    def test_final_lesson_date_is_august_25(self) -> None:
        final_lesson = next(item for item in DEFAULT_PROGRAM_LESSONS if item["lesson_key"] == "s1_b5_final")
        self.assertEqual(final_lesson["date_start"], date(2026, 8, 25))
        self.assertIsNone(final_lesson["date_end"])

    def test_people_season_has_real_first_lesson_and_tentative_slots(self) -> None:
        people_lessons = [item for item in DEFAULT_PROGRAM_LESSONS if item["season_key"] == "s2"]
        self.assertEqual(len(people_lessons), 7)
        self.assertEqual(people_lessons[0]["date_start"], date(2026, 9, 29))
        self.assertEqual(people_lessons[0]["speaker"], "Денис Карандашев")
        self.assertTrue(all(item["date_start"] is None for item in people_lessons[1:]))
        self.assertTrue(all("ориентировочно" in item["date_text"] for item in people_lessons[1:]))

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
