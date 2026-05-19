from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from app.notifications.constants import NOTIFICATION_TIME_OPTIONS


MAIN_MENU_BUTTONS = [
    [KeyboardButton(text="Задать вопрос")],
    [KeyboardButton(text="Материалы программы"), KeyboardButton(text="Домашние задания")],
    [KeyboardButton(text="Расписание Лиги Лидеров")],
    [KeyboardButton(text="Настройки уведомлений")],
]

PROJECT_CONTEXT_MENU_BUTTON = [KeyboardButton(text="Уточнить контекст моего проекта")]


PROJECT_CONTEXT_BUTTONS = [
    [KeyboardButton(text="Загрузить файл с контекстом")],
    [KeyboardButton(text="Добавить контекст текстом")],
    [KeyboardButton(text="Главное меню")],
]


MATERIALS_SEASON_BUTTONS = [
    [KeyboardButton(text="Сезон 1. Бизнес-консалтинг")],
    [KeyboardButton(text="Главное меню")],
]


MATERIALS_TYPE_BUTTONS = [
    [KeyboardButton(text="Записи и материалы занятий")],
    [KeyboardButton(text="Подкасты на основе занятий")],
    [KeyboardButton(text="Саммари занятий")],
    [KeyboardButton(text="Главное меню")],
]

VIDEO_LIBRARY_BUTTON = [KeyboardButton(text="Видео занятий")]


HOMEWORK_MENU_BUTTONS = [
    [KeyboardButton(text="Список заданий")],
    [KeyboardButton(text="Помощь с домашкой")],
    [KeyboardButton(text="Главное меню")],
]


PROJECT_HELP_BUTTONS = [
    [KeyboardButton(text="Как решить конфликтную ситуацию")],
    [KeyboardButton(text="Сложный заказчик")],
    [KeyboardButton(text="Трудности с учётом финансов")],
    [KeyboardButton(text="Главное меню")],
]


NOTIFICATION_SETTINGS_BUTTONS = [
    [KeyboardButton(text=f"Уведомления: {time_value}") for time_value in NOTIFICATION_TIME_OPTIONS],
    [KeyboardButton(text="Уведомления: отключить")],
    [KeyboardButton(text="Главное меню")],
]


ADMIN_MENU_BUTTONS = [
    [KeyboardButton(text="Админ: статус")],
    [KeyboardButton(text="Админ: загрузить материал"), KeyboardButton(text="Админ: материалы")],
    [KeyboardButton(text="Админ: тексты"), KeyboardButton(text="Админ: статистика")],
    [KeyboardButton(text="Админ: напоминание"), KeyboardButton(text="Админ: загрузить ICS")],
    [KeyboardButton(text="Админ: расходы")],
    [KeyboardButton(text="Главное меню")],
]


ADMIN_TEXTS_BUTTONS = [
    [KeyboardButton(text="Изменить приветствие")],
    [KeyboardButton(text="Изменить помощь")],
    [KeyboardButton(text="Изменить расписание")],
    [KeyboardButton(text="Изменить текст уведомления")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_MATERIAL_SEASON_BUTTONS = [
    [KeyboardButton(text="Материал: Сезон 1. Бизнес-консалтинг")],
    [KeyboardButton(text="Материал: без сезона")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_MATERIAL_MODULE_BUTTONS = [
    [KeyboardButton(text="Материал: модуль 1"), KeyboardButton(text="Материал: модуль 2")],
    [KeyboardButton(text="Материал: модуль 3"), KeyboardButton(text="Материал: модуль 4")],
    [KeyboardButton(text="Материал: без модуля")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_MATERIAL_TYPE_BUTTONS = [
    [KeyboardButton(text="Тип: материалы занятия")],
    [KeyboardButton(text="Тип: домашнее задание")],
    [KeyboardButton(text="Тип: саммари")],
    [KeyboardButton(text="Тип: расписание")],
    [KeyboardButton(text="Тип: другое")],
    [KeyboardButton(text="Админ: меню")],
]


def main_menu_keyboard(show_project_context: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [row.copy() for row in MAIN_MENU_BUTTONS]
    if show_project_context:
        keyboard.insert(3, PROJECT_CONTEXT_MENU_BUTTON)
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def project_context_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=PROJECT_CONTEXT_BUTTONS, resize_keyboard=True)


def materials_season_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=MATERIALS_SEASON_BUTTONS, resize_keyboard=True)


def materials_type_keyboard(video_enabled: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [row.copy() for row in MATERIALS_TYPE_BUTTONS]
    if video_enabled:
        keyboard.insert(1, VIDEO_LIBRARY_BUTTON)
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def homework_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=HOMEWORK_MENU_BUTTONS, resize_keyboard=True)


def project_help_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=PROJECT_HELP_BUTTONS, resize_keyboard=True)


def notification_settings_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=NOTIFICATION_SETTINGS_BUTTONS, resize_keyboard=True)


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MENU_BUTTONS, resize_keyboard=True)


def admin_texts_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_TEXTS_BUTTONS, resize_keyboard=True)


def admin_material_season_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIAL_SEASON_BUTTONS, resize_keyboard=True)


def admin_material_module_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIAL_MODULE_BUTTONS, resize_keyboard=True)


def admin_material_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIAL_TYPE_BUTTONS, resize_keyboard=True)


def feedback_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Полезно", callback_data=f"feedback:{message_id}:yes"),
                InlineKeyboardButton(text="Не полезно", callback_data=f"feedback:{message_id}:no"),
            ]
        ]
    )


def question_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Вопрос по программе", callback_data="question_section:program")],
            [InlineKeyboardButton(text="Технический вопрос", callback_data="question_section:technical")],
            [InlineKeyboardButton(text="Другое", callback_data="question_section:other")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
        ]
    )


def start_notification_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=time_value, callback_data=f"start_notification_time:{time_value}")
                for time_value in NOTIFICATION_TIME_OPTIONS
            ]
        ]
    )


def feedback_reason_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Не нашёл ответ", callback_data=f"feedback_reason:{message_id}:not_found"),
                InlineKeyboardButton(text="Слишком общий", callback_data=f"feedback_reason:{message_id}:too_general"),
            ],
            [
                InlineKeyboardButton(text="Не понял вопрос", callback_data=f"feedback_reason:{message_id}:misunderstood"),
                InlineKeyboardButton(text="Другая причина", callback_data=f"feedback_reason:{message_id}:other"),
            ],
        ]
    )


def video_library_keyboard(video_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть видео внутри Telegram", web_app=WebAppInfo(url=video_url))],
            [InlineKeyboardButton(text="Открыть ссылку на видео", url=video_url)],
        ]
    )


def admin_text_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сохранить текст", callback_data="admin_text:save"),
                InlineKeyboardButton(text="Отменить", callback_data="admin_text:cancel"),
            ]
        ]
    )
