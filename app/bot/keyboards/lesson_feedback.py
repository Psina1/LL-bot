from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def feedback_invitation_keyboard(response_id: int, final_reminder: bool = False) -> InlineKeyboardMarkup:
    if final_reminder:
        rows = [
            [
                InlineKeyboardButton(
                    text="Оценить занятие",
                    callback_data=f"lesson_feedback:start:{response_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не готов оценить",
                    callback_data=f"lesson_feedback:decline:{response_id}",
                )
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton(
                    text="Оценить занятие",
                    callback_data=f"lesson_feedback:start:{response_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не был(а) на занятии",
                    callback_data=f"lesson_feedback:not_attended:{response_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Напомнить позже",
                    callback_data=f"lesson_feedback:later:{response_id}",
                )
            ],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def feedback_score_keyboard(response_id: int, score_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(score),
                    callback_data=f"lesson_feedback:score:{score_type}:{response_id}:{score}",
                )
                for score in range(1, 6)
            ]
        ]
    )


def admin_feedback_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Запустить новый опрос",
                    callback_data="admin_lesson_feedback:new",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Активные и последние опросы",
                    callback_data="admin_lesson_feedback:list",
                )
            ],
        ]
    )


def admin_feedback_lessons_keyboard(lessons, display_numbers: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    rows = []
    display_numbers = display_numbers or {}
    for lesson in lessons:
        date_label = lesson.date_start.strftime("%d.%m.%Y") if lesson.date_start else "без даты"
        display_number = display_numbers.get(lesson.lesson_key)
        title_label = lesson.lesson_title
        if title_label.lower().startswith("занятие ") and ". " in title_label:
            title_label = title_label.split(". ", 1)[1]
        label = (
            f"Опрос №{display_number} · {date_label} · {title_label}"
            if display_number
            else f"{date_label} · {title_label}"
        )
        if len(label) > 60:
            label = f"{label[:57]}..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"admin_lesson_feedback:lesson:{lesson.lesson_key}",
                )
            ]
        )
    rows.append(
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="admin_lesson_feedback:menu",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_feedback_launch_keyboard(lesson_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Тест администраторам",
                    callback_data=f"admin_lesson_feedback:test:{lesson_key}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Запустить через 10 минут",
                    callback_data=f"admin_lesson_feedback:schedule:{lesson_key}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить вопросы",
                    callback_data=f"admin_lesson_feedback:edit_questions:{lesson_key}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_lesson_feedback:cancel",
                )
            ],
        ]
    )


def admin_feedback_campaign_keyboard(campaign_id: int, can_close: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Скачать Excel",
                callback_data=f"admin_lesson_feedback:export:{campaign_id}",
            )
        ]
    ]
    if can_close:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Закрыть опрос",
                    callback_data=f"admin_lesson_feedback:close:{campaign_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="К списку опросов",
                callback_data="admin_lesson_feedback:list",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
