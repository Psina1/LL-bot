from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_BUTTONS = [
    [KeyboardButton(text="Задать вопрос по организации Лиги Лидеров")],
    [KeyboardButton(text="Материалы программы"), KeyboardButton(text="Домашние задания")],
    [KeyboardButton(text="Расписание Лиги Лидеров")],
    [KeyboardButton(text="Уточнить контекст моего проекта")],
    [KeyboardButton(text="Нужна помощь с проектом")],
    [KeyboardButton(text="Помощь")],
]


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


ADMIN_MENU_BUTTONS = [
    [KeyboardButton(text="Админ: статус")],
    [KeyboardButton(text="Админ: загрузить материал"), KeyboardButton(text="Админ: материалы")],
    [KeyboardButton(text="Админ: тексты"), KeyboardButton(text="Админ: статистика")],
    [KeyboardButton(text="Админ: расходы")],
    [KeyboardButton(text="Главное меню")],
]


ADMIN_TEXTS_BUTTONS = [
    [KeyboardButton(text="Изменить приветствие")],
    [KeyboardButton(text="Изменить помощь")],
    [KeyboardButton(text="Изменить расписание")],
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


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=MAIN_MENU_BUTTONS, resize_keyboard=True)


def project_context_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=PROJECT_CONTEXT_BUTTONS, resize_keyboard=True)


def materials_season_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=MATERIALS_SEASON_BUTTONS, resize_keyboard=True)


def materials_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=MATERIALS_TYPE_BUTTONS, resize_keyboard=True)


def homework_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=HOMEWORK_MENU_BUTTONS, resize_keyboard=True)


def project_help_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=PROJECT_HELP_BUTTONS, resize_keyboard=True)


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


def admin_text_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сохранить текст", callback_data="admin_text:save"),
                InlineKeyboardButton(text="Отменить", callback_data="admin_text:cancel"),
            ]
        ]
    )
