from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from app.notifications.constants import NOTIFICATION_TIME_OPTIONS


MAIN_MENU_BUTTONS = [
    [KeyboardButton(text="Материалы программы"), KeyboardButton(text="Домашние задания")],
    [KeyboardButton(text="Расписание Лиги Лидеров"), KeyboardButton(text="Настройки уведомлений")],
]

PROJECT_CONTEXT_MENU_BUTTON = [KeyboardButton(text="Уточнить контекст моего проекта")]
DIRECTOR_DASHBOARD_MENU_BUTTON = [KeyboardButton(text="Кабинет руководителя")]


PROJECT_CONTEXT_BUTTONS = [
    [KeyboardButton(text="Загрузить файл с контекстом"), KeyboardButton(text="Добавить контекст текстом")],
    [KeyboardButton(text="Главное меню")],
]


MATERIALS_SEASON_BUTTONS = [
    [KeyboardButton(text="Сезон 1. Бизнес-консалтинг")],
    [KeyboardButton(text="Главное меню")],
]


MATERIALS_TYPE_BUTTONS = [
    [KeyboardButton(text="Записи и материалы занятий"), KeyboardButton(text="Подкасты на основе занятий")],
    [KeyboardButton(text="Саммари занятий")],
    [KeyboardButton(text="Главное меню")],
]

VIDEO_LIBRARY_BUTTON = [KeyboardButton(text="Видео занятий")]


HOMEWORK_MENU_BUTTONS = [
    [KeyboardButton(text="Список заданий"), KeyboardButton(text="Помощь с домашкой")],
    [KeyboardButton(text="Главное меню")],
]


PROJECT_HELP_BUTTONS = [
    [KeyboardButton(text="Как решить конфликтную ситуацию"), KeyboardButton(text="Сложный заказчик")],
    [KeyboardButton(text="Трудности с учётом финансов")],
    [KeyboardButton(text="Главное меню")],
]


NOTIFICATION_SETTINGS_BUTTONS = [
    [KeyboardButton(text=f"Уведомления: {time_value}") for time_value in NOTIFICATION_TIME_OPTIONS[:2]],
    [KeyboardButton(text=f"Уведомления: {NOTIFICATION_TIME_OPTIONS[2]}"), KeyboardButton(text="Уведомления: отключить")],
    [KeyboardButton(text="Главное меню")],
]


ADMIN_MENU_BUTTONS = [
    [KeyboardButton(text="Статус и аналитика"), KeyboardButton(text="Управление материалами")],
    [KeyboardButton(text="Обратная связь"), KeyboardButton(text="Уведомления и сообщения")],
    [KeyboardButton(text="Тексты и оформление")],
    [KeyboardButton(text="Кабинет руководителя")],
    [KeyboardButton(text="Главное меню")],
]

ADMIN_STATUS_BUTTONS = [
    [KeyboardButton(text="Состояние бота"), KeyboardButton(text="Активность участников")],
    [KeyboardButton(text="Ошибки"), KeyboardButton(text="Расходы OpenAI")],
    [KeyboardButton(text="Скачать CSV")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_MATERIALS_BUTTONS = [
    [KeyboardButton(text="Добавить материал"), KeyboardButton(text="Добавить видео/подкаст")],
    [KeyboardButton(text="Библиотека материалов"), KeyboardButton(text="Домашние задания в базе")],
    [KeyboardButton(text="Сервисные действия")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_MATERIALS_SERVICE_BUTTONS = [
    [KeyboardButton(text="Переиндексировать материалы")],
    [KeyboardButton(text="Админ: материалы программы")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_NOTIFICATIONS_BUTTONS = [
    [KeyboardButton(text="Ближайшие уведомления"), KeyboardButton(text="Настройки автоуведомлений")],
    [KeyboardButton(text="Отправить сообщение"), KeyboardButton(text="Календарные файлы")],
    [KeyboardButton(text="История отправок")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_CALENDAR_BUTTONS = [
    [KeyboardButton(text="Загрузить ICS")],
    [KeyboardButton(text="Админ: уведомления и сообщения")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_TECH_FILES_BUTTONS = [
    [KeyboardButton(text="Техфайл: ICS календаря")],
    [KeyboardButton(text="Техфайл: картинка расписания")],
    [KeyboardButton(text="Техфайл: видео/подкаст")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_TEXTS_BUTTONS = [
    [KeyboardButton(text="Изменить приветствие"), KeyboardButton(text="Изменить помощь")],
    [KeyboardButton(text="Изменить расписание"), KeyboardButton(text="Картинка расписания")],
    [KeyboardButton(text="Контакты поддержки")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_MATERIAL_SEASON_BUTTONS = [
    [KeyboardButton(text="Материал: Сезон 1. Бизнес-консалтинг")],
    [KeyboardButton(text="Материал: Сезон 2. Люди")],
    [KeyboardButton(text="Материал: без сезона")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_MEDIA_SEASON_BUTTONS = [
    [KeyboardButton(text="Медиа: Сезон 1. Бизнес-консалтинг")],
    [KeyboardButton(text="Медиа: Сезон 2. Люди")],
    [KeyboardButton(text="Медиа: без сезона")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_MATERIAL_MODULE_BUTTONS = [
    [KeyboardButton(text="Материал: общий материал")],
    [KeyboardButton(text="Материал: урок/модуль 1"), KeyboardButton(text="Материал: урок/модуль 2")],
    [KeyboardButton(text="Материал: урок/модуль 3"), KeyboardButton(text="Материал: урок/модуль 4")],
    [KeyboardButton(text="Админ: меню")],
]


ADMIN_MATERIAL_TYPE_BUTTONS = [
    [KeyboardButton(text="Тип: материалы занятия")],
    [KeyboardButton(text="Тип: домашнее задание")],
    [KeyboardButton(text="Тип: саммари")],
    [KeyboardButton(text="Тип: транскрипция")],
    [KeyboardButton(text="Тип: расписание")],
    [KeyboardButton(text="Тип: другое")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_LESSON_DATE_BUTTONS = [
    [KeyboardButton(text="Дата: без даты")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_HOMEWORK_LINK_BUTTONS = [
    [KeyboardButton(text="Ссылка: без ссылки")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_HOMEWORK_DEADLINE_BUTTONS = [
    [KeyboardButton(text="Дедлайн: следующее занятие")],
    [KeyboardButton(text="Дедлайн: без даты")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_MEDIA_TYPE_BUTTONS = [
    [KeyboardButton(text="Медиа: видео"), KeyboardButton(text="Медиа: подкаст")],
    [KeyboardButton(text="Админ: меню")],
]

ADMIN_MEDIA_MODULE_BUTTONS = [
    [KeyboardButton(text="Медиа: общий материал")],
    [KeyboardButton(text="Медиа: урок/модуль 1"), KeyboardButton(text="Медиа: урок/модуль 2")],
    [KeyboardButton(text="Медиа: урок/модуль 3"), KeyboardButton(text="Медиа: урок/модуль 4")],
    [KeyboardButton(text="Админ: меню")],
]


def main_menu_keyboard(
    show_project_context: bool = False,
    show_director_dashboard: bool = False,
) -> ReplyKeyboardMarkup:
    keyboard = [row.copy() for row in MAIN_MENU_BUTTONS]
    if show_director_dashboard:
        keyboard.append(DIRECTOR_DASHBOARD_MENU_BUTTON.copy())
    if show_project_context:
        keyboard.append(PROJECT_CONTEXT_MENU_BUTTON.copy())
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def project_context_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=PROJECT_CONTEXT_BUTTONS, resize_keyboard=True)


def materials_season_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=MATERIALS_SEASON_BUTTONS, resize_keyboard=True)


def materials_type_keyboard(video_enabled: bool = False) -> ReplyKeyboardMarkup:
    if video_enabled:
        keyboard = [
            [KeyboardButton(text="Записи и материалы занятий"), VIDEO_LIBRARY_BUTTON[0]],
            [KeyboardButton(text="Подкасты на основе занятий"), KeyboardButton(text="Саммари занятий")],
            [KeyboardButton(text="Главное меню")],
        ]
    else:
        keyboard = [row.copy() for row in MATERIALS_TYPE_BUTTONS]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def homework_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=HOMEWORK_MENU_BUTTONS, resize_keyboard=True)


def project_help_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=PROJECT_HELP_BUTTONS, resize_keyboard=True)


def notification_settings_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=NOTIFICATION_SETTINGS_BUTTONS, resize_keyboard=True)


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MENU_BUTTONS, resize_keyboard=True)


def admin_status_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_STATUS_BUTTONS, resize_keyboard=True)


def admin_materials_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIALS_BUTTONS, resize_keyboard=True)


def admin_materials_service_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIALS_SERVICE_BUTTONS, resize_keyboard=True)


def admin_notifications_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_NOTIFICATIONS_BUTTONS, resize_keyboard=True)


def admin_calendar_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_CALENDAR_BUTTONS, resize_keyboard=True)


def admin_tech_files_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_TECH_FILES_BUTTONS, resize_keyboard=True)


def all_reply_button_labels() -> set[str]:
    keyboard_groups = [
        MAIN_MENU_BUTTONS,
        [PROJECT_CONTEXT_MENU_BUTTON],
        [DIRECTOR_DASHBOARD_MENU_BUTTON],
        PROJECT_CONTEXT_BUTTONS,
        MATERIALS_SEASON_BUTTONS,
        MATERIALS_TYPE_BUTTONS,
        [VIDEO_LIBRARY_BUTTON],
        HOMEWORK_MENU_BUTTONS,
        PROJECT_HELP_BUTTONS,
        NOTIFICATION_SETTINGS_BUTTONS,
        ADMIN_MENU_BUTTONS,
        ADMIN_STATUS_BUTTONS,
        ADMIN_MATERIALS_BUTTONS,
        ADMIN_MATERIALS_SERVICE_BUTTONS,
        ADMIN_NOTIFICATIONS_BUTTONS,
        ADMIN_CALENDAR_BUTTONS,
        ADMIN_TECH_FILES_BUTTONS,
        ADMIN_TEXTS_BUTTONS,
        ADMIN_MATERIAL_SEASON_BUTTONS,
        ADMIN_MEDIA_SEASON_BUTTONS,
        ADMIN_MATERIAL_MODULE_BUTTONS,
        ADMIN_MATERIAL_TYPE_BUTTONS,
        ADMIN_LESSON_DATE_BUTTONS,
        ADMIN_HOMEWORK_LINK_BUTTONS,
        ADMIN_HOMEWORK_DEADLINE_BUTTONS,
        ADMIN_MEDIA_TYPE_BUTTONS,
        ADMIN_MEDIA_MODULE_BUTTONS,
    ]
    labels: set[str] = set()
    for keyboard in keyboard_groups:
        for row in keyboard:
            for button in row:
                labels.add(button.text)
    return labels


def admin_texts_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_TEXTS_BUTTONS, resize_keyboard=True)


def admin_material_season_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIAL_SEASON_BUTTONS, resize_keyboard=True)


def admin_media_season_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MEDIA_SEASON_BUTTONS, resize_keyboard=True)


def admin_material_module_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIAL_MODULE_BUTTONS, resize_keyboard=True)


def admin_material_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MATERIAL_TYPE_BUTTONS, resize_keyboard=True)


def admin_lesson_date_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_LESSON_DATE_BUTTONS, resize_keyboard=True)


def admin_homework_link_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_HOMEWORK_LINK_BUTTONS, resize_keyboard=True)


def admin_homework_deadline_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_HOMEWORK_DEADLINE_BUTTONS, resize_keyboard=True)


def admin_media_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MEDIA_TYPE_BUTTONS, resize_keyboard=True)


def admin_media_module_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=ADMIN_MEDIA_MODULE_BUTTONS, resize_keyboard=True)


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


def materials_program_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Последнее занятие", callback_data="materials:last_lesson")],
            [InlineKeyboardButton(text="Выбрать занятие", callback_data="materials:choose_lesson")],
            [InlineKeyboardButton(text="Все материалы", callback_data="materials:all")],
            [InlineKeyboardButton(text="Подкасты", callback_data="materials:podcasts")],
            [InlineKeyboardButton(text="Саммари", callback_data="materials:summary")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
        ]
    )


def materials_lesson_card_keyboard(
    lesson,
    has_docs: bool = True,
    has_summary: bool = False,
    has_podcasts: bool = False,
    has_video: bool = False,
    has_homework: bool = False,
    single_video_url: str | None = None,
) -> InlineKeyboardMarkup:
    keyboard = []
    if single_video_url:
        keyboard.append([InlineKeyboardButton(text="Смотреть запись", web_app=WebAppInfo(url=single_video_url))])
        keyboard.append([InlineKeyboardButton(text="Открыть ссылкой", url=single_video_url)])
    if has_docs:
        keyboard.append([InlineKeyboardButton(text="Материалы и презентации", callback_data=f"materials:lesson_docs:{lesson.lesson_key}")])
    if has_summary:
        keyboard.append([InlineKeyboardButton(text="Саммари занятия", callback_data=f"materials:lesson_summary:{lesson.lesson_key}")])
    if has_podcasts:
        keyboard.append([InlineKeyboardButton(text="Подкаст", callback_data=f"materials:lesson_podcasts:{lesson.lesson_key}")])
    if has_video and not single_video_url:
        keyboard.append([InlineKeyboardButton(text="Видео", callback_data=f"materials:lesson_video:{lesson.lesson_key}")])
    if has_homework:
        keyboard.append([InlineKeyboardButton(text="Домашнее задание", callback_data=f"materials:lesson_homework:{lesson.lesson_key}")])
    keyboard.append([InlineKeyboardButton(text="Выбрать другое занятие", callback_data="materials:choose_lesson")])
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def materials_blocks_keyboard(blocks) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=f"Блок {block_order}. {block_title}", callback_data=f"materials:block:{block_key}")]
        for block_key, block_title, block_order in blocks
    ]
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def materials_lessons_keyboard(lessons) -> InlineKeyboardMarkup:
    keyboard = []
    for lesson in lessons:
        title = lesson.lesson_title if len(lesson.lesson_title) <= 56 else f"{lesson.lesson_title[:53]}..."
        keyboard.append([InlineKeyboardButton(text=title, callback_data=f"materials:lesson:{lesson.lesson_key}")])
    keyboard.append([InlineKeyboardButton(text="К блокам", callback_data=f"materials:choose_lesson")])
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def homework_program_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Список заданий", callback_data="homework:list")],
            [InlineKeyboardButton(text="Помощь с домашкой", callback_data="homework:help")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
        ]
    )


def homework_list_keyboard(homeworks=None, include_archive: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    for homework in (homeworks or [])[:20]:
        title = homework.title if len(homework.title) <= 54 else f"{homework.title[:51]}..."
        keyboard.append([InlineKeyboardButton(text=title, callback_data=f"homework:item:{homework.id}")])
    if include_archive:
        keyboard.append([InlineKeyboardButton(text="Архив ДЗ", callback_data="homework:archive")])
    keyboard.append([InlineKeyboardButton(text="Задай свой вопрос по заданию", callback_data="homework:help")])
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def homework_detail_keyboard(homework_id: int | None = None) -> InlineKeyboardMarkup:
    help_callback = f"homework:help:{homework_id}" if homework_id else "homework:help"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Задай свой вопрос по заданию", callback_data=help_callback)],
            [InlineKeyboardButton(text="К списку заданий", callback_data="homework:list")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
        ]
    )


def _document_button_title(document) -> str:
    date_suffix = ""
    if getattr(document, "lesson_date", None):
        date_suffix = f" ({document.lesson_date.strftime('%d.%m.%Y')})"
    title = f"{document.title}{date_suffix}"
    return title if len(title) <= 58 else f"{title[:55]}..."


def document_list_keyboard(documents, include_main_menu: bool = True) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=_document_button_title(document), callback_data=f"document:send:{document.id}")]
        for document in documents[:20]
    ]
    if include_main_menu:
        keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def summary_list_keyboard(documents, include_main_menu: bool = True) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=_document_button_title(document), callback_data=f"summary:send:{document.id}")]
        for document in documents[:20]
    ]
    if include_main_menu:
        keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _media_button_title(media) -> str:
    module_prefix = f"Модуль {media.module_number}: " if getattr(media, "module_number", None) else ""
    title = f"{module_prefix}{media.title}"
    return title if len(title) <= 58 else f"{title[:55]}..."


def media_list_keyboard(media_items, media_type: str, include_docs_button: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=_media_button_title(media), callback_data=f"media:{media_type}:{media.id}")]
        for media in media_items[:20]
    ]
    if include_docs_button:
        keyboard.append([InlineKeyboardButton(text="Текстовые материалы", callback_data="materials:docs")])
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def podcast_empty_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сделать текстовую подкаст-выжимку", callback_data="materials:podcast_text")],
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


def schedule_seasons_keyboard(seasons) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=season_title, callback_data=f"schedule:season:{season_key}")]
        for season_key, season_title in seasons
    ]
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def schedule_blocks_keyboard(blocks) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=f"Блок {block_order}. {block_title}", callback_data=f"schedule:block:{block_key}")]
        for block_key, block_title, block_order in blocks
    ]
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def schedule_lessons_keyboard(lessons) -> InlineKeyboardMarkup:
    keyboard = []
    for lesson in lessons:
        title = lesson.lesson_title if len(lesson.lesson_title) <= 56 else f"{lesson.lesson_title[:53]}..."
        keyboard.append([InlineKeyboardButton(text=title, callback_data=f"schedule:lesson:{lesson.lesson_key}")])
    keyboard.append([InlineKeyboardButton(text="К блокам сезона", callback_data=f"schedule:season:{lessons[0].season_key}" if lessons else "schedule:season:s1")])
    keyboard.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def schedule_lesson_keyboard(lesson) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Материалы занятия", callback_data=f"schedule:materials:{lesson.lesson_key}")],
            [InlineKeyboardButton(text="К занятиям блока", callback_data=f"schedule:block:{lesson.block_key}")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
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


def bot_feedback_score_keyboard(response_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(score), callback_data=f"bot_feedback:score:{response_id}:{score}")
                for score in range(1, 6)
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


def video_watch_keyboard(video_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Смотреть в Telegram", web_app=WebAppInfo(url=video_url))],
            [InlineKeyboardButton(text="Открыть ссылкой", url=video_url)],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
        ]
    )


def director_dashboard_keyboard(dashboard_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть кабинет руководителя", web_app=WebAppInfo(url=dashboard_url))],
            [InlineKeyboardButton(text="Открыть ссылкой", url=dashboard_url)],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:main")],
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


def admin_message_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отправить сообщение", callback_data="admin_message:send"),
                InlineKeyboardButton(text="Отменить", callback_data="admin_message:cancel"),
            ]
        ]
    )


def admin_overview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выгрузить CSV", callback_data="admin:export_csv")],
        ]
    )


def admin_notification_control_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Включить автоуведомления", callback_data="admin_notifications:start"),
                InlineKeyboardButton(text="Остановить", callback_data="admin_notifications:stop"),
            ],
            [InlineKeyboardButton(text="Обновить статус", callback_data="admin_notifications:refresh")],
        ]
    )
