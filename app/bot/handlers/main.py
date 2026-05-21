from __future__ import annotations

import logging
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, LinkPreviewOptions, Message, ReplyKeyboardMarkup
from sqlalchemy import text

from app.bot.keyboards.reply import (
    admin_material_module_keyboard,
    admin_material_season_keyboard,
    admin_material_type_keyboard,
    admin_homework_link_keyboard,
    admin_lesson_date_keyboard,
    admin_media_module_keyboard,
    admin_media_type_keyboard,
    admin_menu_keyboard,
    admin_text_preview_keyboard,
    admin_texts_keyboard,
    feedback_reason_keyboard,
    homework_detail_keyboard,
    homework_list_keyboard,
    homework_program_keyboard,
    main_menu_keyboard,
    materials_program_keyboard,
    materials_season_keyboard,
    materials_type_keyboard,
    media_list_keyboard,
    notification_settings_keyboard,
    podcast_empty_keyboard,
    project_context_keyboard,
    project_help_keyboard,
    question_section_keyboard,
    schedule_blocks_keyboard,
    schedule_lesson_keyboard,
    schedule_lessons_keyboard,
    schedule_seasons_keyboard,
    start_notification_time_keyboard,
    video_library_keyboard,
)
from app.bot.states.forms import AdminFlow, UserFlow
from app.bot.texts import (
    ADMIN_PROMPT,
    BOT_TEXT_DEFAULTS,
    BOT_TEXT_LABELS,
    FILE_UPLOAD_PROMPT,
    HOMEWORK_HELP_PROMPT,
    HOMEWORK_MENU_PROMPT,
    MATERIALS_SEASON_PROMPT,
    MATERIALS_TYPE_PROMPT,
    PODCASTS_PROMPT,
    PROJECT_CONTEXT_UPLOAD_PROMPT,
    PROJECT_HELP_MENU_PROMPT,
    PROJECT_HELP_PLACEHOLDER_TEXT,
    PROJECT_PROMPT,
    VIDEO_LIBRARY_DISABLED_TEXT,
)
from app.db.repositories import (
    AppSettingRepository,
    BotTextRepository,
    DocumentRepository,
    ErrorRepository,
    MessageFeedbackRepository,
    MessageRepository,
    HomeworkRepository,
    ProgramLessonRepository,
    ProgramMediaRepository,
    UserNotificationSettingRepository,
    StatsRepository,
    UserRepository,
)
from app.db.session import SessionLocal
from app.notifications.constants import (
    NOTIFICATION_ICS_FILENAME_KEY,
    NOTIFICATION_ICS_PATH_KEY,
    NOTIFICATION_TEXT_KEY,
    NOTIFICATION_TIME_OPTIONS,
)
from app.services.container import AppContainer
from app.services.document_service import FileValidationError

logger = logging.getLogger(__name__)

THINKING_MESSAGES = [
    "Думаю над ответом...",
    "Лезу в архивы...",
    "Листаю материалы...",
    "Собираю ответ...",
    "Сверяю источники...",
]

FILE_PROCESSING_MESSAGES = [
    "Разбираю файл...",
    "Достаю текст из документа...",
    "Готовлю материал для вопросов...",
    "Складываю файл в личный контекст...",
]

GROUP_CHAT_TYPES = {"group", "supergroup"}
ANNOUNCEMENT_CHAT_ID_KEY = "announcement_chat_id"
ANNOUNCEMENT_CHAT_TITLE_KEY = "announcement_chat_title"
NO_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _shorten_project_context(project_context: str, limit: int = 900) -> str:
    cleaned = project_context.strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _format_rub(value: float | None) -> str:
    if value is None:
        return "нет данных"
    if value < 0.01:
        return "меньше 0.01 ₽"
    return f"{value:.2f} ₽"


def _format_tokens(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _parse_billing_started_at(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total_bytes = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total_bytes += item.stat().st_size
            except OSError:
                continue
    return total_bytes / 1024 / 1024


def _message_html_text(message: Message) -> str:
    # Telegram stores rich links and formatting in entities; html_text preserves them safely.
    html_text = getattr(message, "html_text", None)
    return (html_text or message.text or "").strip()


async def _delete_message_safely(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramNetworkError):
        return


def build_main_router(container: AppContainer) -> Router:
    router = Router(name="main")

    def user_main_menu():
        return main_menu_keyboard(show_project_context=container.settings.show_project_context_menu)

    def materials_menu_keyboard():
        return materials_type_keyboard(video_enabled=container.settings.video_library_enabled)

    def reply_keyboard_from_labels(labels: list[str], row_size: int = 2, back_button: str = "Админ: меню") -> ReplyKeyboardMarkup:
        rows: list[list[KeyboardButton]] = []
        for index in range(0, len(labels), row_size):
            rows.append([KeyboardButton(text=label) for label in labels[index : index + row_size]])
        rows.append([KeyboardButton(text=back_button)])
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

    def block_button_label(block: tuple[str, str, int]) -> str:
        _, block_title, block_order = block
        return f"Блок {block_order}. {block_title}"

    def lesson_button_label(lesson) -> str:
        return lesson.lesson_title if len(lesson.lesson_title) <= 62 else f"{lesson.lesson_title[:59]}..."

    async def admin_blocks_keyboard(season_key: str) -> ReplyKeyboardMarkup:
        async with SessionLocal() as session:
            blocks = await ProgramLessonRepository.list_blocks(session, season_key)
        return reply_keyboard_from_labels([block_button_label(block) for block in blocks])

    async def admin_lessons_keyboard(block_key: str, whole_label: str = "Материал всего блока") -> ReplyKeyboardMarkup:
        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_by_block(session, block_key)
        labels = [whole_label] + [lesson_button_label(lesson) for lesson in lessons]
        return reply_keyboard_from_labels(labels, row_size=1)

    def lesson_to_state_payload(prefix: str, lesson) -> dict[str, Any]:
        return {
            f"{prefix}_module_number": lesson.lesson_number,
            f"{prefix}_module_title": f"{lesson.block_title}: {lesson.lesson_title}",
            f"{prefix}_lesson_key": lesson.lesson_key,
            f"{prefix}_lesson_date": lesson.date_start.isoformat() if lesson.date_start else None,
        }

    def block_to_state_payload(prefix: str, block_key: str, block_title: str) -> dict[str, Any]:
        return {
            f"{prefix}_module_number": None,
            f"{prefix}_module_title": block_title,
            f"{prefix}_lesson_key": block_key,
            f"{prefix}_lesson_date": None,
        }

    async def upsert_telegram_user(telegram_user):
        async with SessionLocal() as session:
            return await UserRepository.upsert_telegram_user(
                session=session,
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                is_admin=telegram_user.id in container.settings.admin_ids,
            )

    async def ensure_user(message: Message):
        return await upsert_telegram_user(message.from_user)

    async def get_user_and_session(message: Message, telegram_user=None):
        actor = telegram_user or message.from_user
        session = SessionLocal()
        user = await UserRepository.upsert_telegram_user(
            session=session,
            telegram_id=actor.id,
            username=actor.username,
            first_name=actor.first_name,
            last_name=actor.last_name,
            is_admin=actor.id in container.settings.admin_ids,
        )
        return user, session

    def is_admin(message: Message) -> bool:
        return message.from_user.id in container.settings.admin_ids

    def is_admin_user_id(user_id: int) -> bool:
        return user_id in container.settings.admin_ids

    def is_group_chat(message: Message) -> bool:
        return message.chat.type in GROUP_CHAT_TYPES

    def command_argument(text_value: str | None) -> str:
        if not text_value:
            return ""
        parts = text_value.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    def question_section_context(section: str | None) -> tuple[str, str | None, bool]:
        if section == "technical":
            return (
                "technical_question",
                "Раздел вопроса: технический вопрос. "
                "Если вопрос про работу бота, записи занятий, доступы, технические ошибки или платформу обучения «ПРОГРЕСС», "
                "ответь коротко и предложи написать Илье в Telegram: @reptiloid0. "
                "Не выдумывай инструкции по платформе, если они не указаны в загруженных материалах.",
                False,
            )
        if section == "other":
            return (
                "other_question",
                "Раздел вопроса: другое. Сначала опирайся на загруженные материалы программы. "
                "Если ответа нет, честно скажи, что точного ответа нет, и предложи задать вопрос в общий чат программы.",
                True,
            )
        return (
            "program_question",
            "Раздел вопроса: вопрос по программе. Отвечай по загруженным материалам программы и организационному контексту.",
            True,
        )

    def looks_like_technical_question(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        direct_markers = [
            "не могу зайти",
            "не получается зайти",
            "не зайти",
            "не открывается",
            "не открыва",
            "ошибка",
            "логин",
            "пароль",
            "доступ",
            "платформ",
            "прогресс",
            "запис",
            "видео",
            "ссылка",
            "прикреп",
            "прилож",
        ]
        if any(marker in text for marker in direct_markers):
            return True
        homework_action = any(marker in text for marker in ["сдать", "отправить", "загрузить", "прикрепить", "приложить"])
        return homework_action and any(marker in text for marker in ["дз", "домаш", "задани"])

    def looks_like_schedule_question(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        return any(
            marker in text
            for marker in [
                "распис",
                "когда",
                "какого числа",
                "дата",
                "занят",
                "урок",
                "блок",
                "спикер",
                "семенов",
                "рахманов",
                "макарова",
                "сафронов",
            ]
        )

    def extract_media_payload(message: Message) -> dict[str, Any] | None:
        media = None
        telegram_kind = ""
        original_filename = None
        mime_type = None
        title_hint = None

        if message.photo:
            media = message.photo[-1]
            telegram_kind = "photo"
            title_hint = "Картинка"
        elif message.video:
            media = message.video
            telegram_kind = "video"
            title_hint = "Видео занятия"
        elif message.audio:
            media = message.audio
            telegram_kind = "audio"
            original_filename = message.audio.file_name
            mime_type = message.audio.mime_type
            title_hint = message.audio.title or message.audio.file_name or "Подкаст"
        elif message.voice:
            media = message.voice
            telegram_kind = "voice"
            mime_type = message.voice.mime_type
            title_hint = "Голосовой подкаст"
        elif message.document:
            media = message.document
            telegram_kind = "document"
            original_filename = message.document.file_name
            mime_type = message.document.mime_type
            title_hint = message.document.file_name or "Медиафайл"

        if media is None:
            return None

        caption_title = (message.caption or "").strip().splitlines()[0].strip() if message.caption else ""
        title = caption_title or (Path(title_hint).stem if title_hint else "Медиафайл")
        return {
            "title": title[:500],
            "telegram_kind": telegram_kind,
            "telegram_file_id": media.file_id,
            "telegram_file_unique_id": getattr(media, "file_unique_id", None),
            "original_filename": original_filename,
            "file_size": getattr(media, "file_size", None),
            "mime_type": mime_type,
        }

    def media_payload_matches_type(payload: dict[str, Any], media_type: str) -> bool:
        kind = payload["telegram_kind"]
        mime_type = (payload.get("mime_type") or "").lower()
        filename = (payload.get("original_filename") or "").lower()
        if media_type == "video":
            return kind == "video" or mime_type.startswith("video/") or filename.endswith((".mp4", ".mov", ".m4v"))
        if media_type == "podcast":
            return kind in {"audio", "voice"} or mime_type.startswith("audio/") or filename.endswith((".mp3", ".m4a", ".wav", ".ogg"))
        if media_type in {"image", "schedule_image"}:
            return kind == "photo" or mime_type.startswith("image/") or filename.endswith((".jpg", ".jpeg", ".png", ".webp"))
        return False

    def lesson_payload(prefix: str, season_title: str | None, text_value: str) -> dict[str, Any]:
        text = text_value.lower()
        if "общий" in text or "без модуля" in text:
            module_title = f"{season_title}, общий материал" if season_title else "Общий материал программы"
            return {
                f"{prefix}_module_number": None,
                f"{prefix}_module_title": module_title,
                f"{prefix}_lesson_key": "general",
            }

        module_match = re.search(r"(?:модуль|урок)\s+(\d+)", text_value, flags=re.IGNORECASE)
        module_number = int(module_match.group(1)) if module_match else None
        module_title = None
        lesson_key = "general"
        if module_number:
            module_title = f"{season_title}, урок/модуль {module_number}" if season_title else f"Урок/модуль {module_number}"
            lesson_key = f"lesson_{module_number}"
        return {
            f"{prefix}_module_number": module_number,
            f"{prefix}_module_title": module_title,
            f"{prefix}_lesson_key": lesson_key,
        }

    MONTHS_RU = {
        "января": 1,
        "январь": 1,
        "февраля": 2,
        "февраль": 2,
        "марта": 3,
        "март": 3,
        "апреля": 4,
        "апрель": 4,
        "мая": 5,
        "май": 5,
        "июня": 6,
        "июнь": 6,
        "июля": 7,
        "июль": 7,
        "августа": 8,
        "август": 8,
        "сентября": 9,
        "сентябрь": 9,
        "октября": 10,
        "октябрь": 10,
        "ноября": 11,
        "ноябрь": 11,
        "декабря": 12,
        "декабрь": 12,
    }

    def parse_lesson_date_input(text_value: str | None) -> date | None:
        text = (text_value or "").strip().lower()
        if not text or text in {"дата: без даты", "без даты", "нет", "-"}:
            return None

        iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
        if iso_match:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))

        numeric_match = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", text)
        if numeric_match:
            day = int(numeric_match.group(1))
            month = int(numeric_match.group(2))
            year_raw = numeric_match.group(3)
            year = datetime.now().year if year_raw is None else int(year_raw)
            if year < 100:
                year += 2000
            return date(year, month, day)

        month_names = "|".join(MONTHS_RU.keys())
        ru_match = re.search(rf"\b(\d{{1,2}})(?:-?го)?\s+({month_names})(?:\s+(\d{{4}}))?\b", text)
        if ru_match:
            day = int(ru_match.group(1))
            month = MONTHS_RU[ru_match.group(2)]
            year = int(ru_match.group(3)) if ru_match.group(3) else datetime.now().year
            return date(year, month, day)

        raise ValueError("invalid_lesson_date")

    def format_lesson_date(value: date | None) -> str:
        return value.strftime("%d.%m.%Y") if value else "без даты"

    def normalize_homework_link(text_value: str | None) -> str | None:
        text = (text_value or "").strip()
        if not text or text.lower() in {"ссылка: без ссылки", "без ссылки", "нет", "-"}:
            return None
        if not re.match(r"^https?://", text, flags=re.IGNORECASE):
            raise ValueError("invalid_homework_link")
        return text

    def homework_lesson_label(homework) -> str:
        parts = []
        if homework.module_number:
            parts.append(f"урок/модуль {homework.module_number}")
        elif homework.lesson_key:
            parts.append(homework.lesson_key)
        if homework.lesson_date:
            parts.append(format_lesson_date(homework.lesson_date))
        return ", ".join(parts) or "без привязки"

    def extract_material_lookup(text_value: str | None) -> dict[str, Any] | None:
        text = (text_value or "").strip().lower()
        if not text:
            return None

        has_material_intent = any(
            marker in text
            for marker in [
                "материал",
                "запис",
                "видео",
                "подкаст",
                "саммари",
                "конспект",
                "презентац",
                "файл",
                "урок",
                "заняти",
                "модул",
                "дз",
                "домаш",
                "задани",
            ]
        )
        if not has_material_intent:
            return None

        lesson_date = None
        try:
            lesson_date = parse_lesson_date_input(text)
        except ValueError:
            lesson_date = None

        lesson_key = None
        module_number = None
        direct_lesson_markers = [
            ("s1_b1_kickoff", ["кикоф", "kick-off", "kickoff"]),
            ("s1_b2_l1", ["time to cash", "логика консалтингового бизнеса"]),
            ("s1_b2_l2", ["организационные модели", "организационн"]),
            ("s1_b2_l3", ["практикум"]),
            ("s1_b2_l4", ["итоговая сборка блока"]),
            ("s1_b3_l1", ["стратегия как инструмент"]),
            ("s1_b3_l2", ["фокус", "стратегический выбор"]),
            ("s1_b3_l3", ["ресурсы", "сценарное планирование"]),
            ("s1_b3_l4", ["реализация стратегии", "сопротивляющейся системе"]),
            ("s1_b4_l1", ["экономика проектов", "маржа"]),
            ("s1_b4_l2", ["финансовая модель"]),
            ("s1_b4_l3", ["финансовое мышление"]),
            ("s1_b4_l4", ["интеграция и разбор"]),
            ("s1_b5_final", ["очная сессия", "подведение итогов", "спб"]),
        ]
        for candidate_key, markers in direct_lesson_markers:
            if any(marker in text for marker in markers):
                lesson_key = candidate_key
                break

        block_key = None
        if "бизнес" in text or "консалт" in text:
            block_key = "s1_b2"
        elif "стратег" in text:
            block_key = "s1_b3"
        elif "эконом" in text or "финанс" in text:
            block_key = "s1_b4"

        module_match = re.search(r"(?:урок|модуль|занятие)\s*(?:№|номер)?\s*(\d+)", text, flags=re.IGNORECASE)
        if not module_match:
            module_match = re.search(r"\b(\d+)\s*(?:урок|модуль|занятие)\b", text, flags=re.IGNORECASE)
        if module_match:
            module_number = int(module_match.group(1))
            if block_key:
                lesson_key = f"{block_key}_l{module_number}"
            elif lesson_key is None:
                lesson_key = f"lesson_{module_number}"

        if not lesson_key and lesson_date is None:
            return None

        return {
            "lesson_key": lesson_key,
            "lesson_date": lesson_date,
            "module_number": module_number,
        }

    def build_content_tags(
        *,
        lesson_key: str | None,
        module_number: int | None,
        lesson_date: date | None = None,
        season_title: str | None = None,
        material_type: str | None = None,
        media_type: str | None = None,
    ) -> list[str]:
        tags = ["scope:general"] if lesson_key == "general" or module_number is None else []
        if season_title:
            tags.append(f"season:{season_title}")
        if lesson_key:
            tags.append(f"lesson_key:{lesson_key}")
        if module_number:
            tags.extend([f"lesson:{module_number}", f"module:{module_number}"])
        if lesson_date:
            tags.append(f"date:{lesson_date.isoformat()}")
        if material_type:
            tags.append(f"type:{material_type}")
        if media_type:
            tags.append(f"media:{media_type}")
        return list(dict.fromkeys(tags))

    async def get_bot_text(key: str) -> str:
        async with SessionLocal() as session:
            return await BotTextRepository.get_value(session, key, BOT_TEXT_DEFAULTS[key])

    async def require_admin(message: Message) -> bool:
        await ensure_user(message)
        if not is_admin(message):
            await message.answer("Эта команда доступна только администратору.")
            return False
        return True

    async def get_announcement_chat(session) -> tuple[int | None, str | None]:
        chat_id_value = await AppSettingRepository.get_value(session, ANNOUNCEMENT_CHAT_ID_KEY)
        chat_title = await AppSettingRepository.get_value(session, ANNOUNCEMENT_CHAT_TITLE_KEY)
        if not chat_id_value:
            return None, chat_title
        try:
            return int(chat_id_value), chat_title
        except ValueError:
            return None, chat_title

    async def send_reminder_to_group(message: Message, text_value: str, user_id: int | None = None) -> None:
        reminder_text = text_value.strip()
        if len(reminder_text) < 3:
            await message.answer("Пришли текст напоминания. Например: /send_reminder Завтра занятие в 17:00.")
            return

        async with SessionLocal() as session:
            chat_id, chat_title = await get_announcement_chat(session)

        if chat_id is None:
            await message.answer(
                "Групповой чат ещё не привязан.\n\n"
                "Когда чат появится, добавь туда бота и отправь в этом чате команду /set_group_chat от имени админа."
            )
            return

        try:
            await message.bot.send_message(
                chat_id=chat_id,
                text=reminder_text,
                parse_mode=None,
                link_preview_options=NO_LINK_PREVIEW,
            )
        except Exception as exc:
            async with SessionLocal() as session:
                await ErrorRepository.create(
                    session=session,
                    context="send_group_reminder",
                    error_text=str(exc),
                    user_id=user_id,
                )
            await message.answer(
                "Не получилось отправить напоминание в групповой чат. "
                "Проверь, что бот добавлен в чат и имеет право писать сообщения."
            )
            return

        title_part = f" «{chat_title}»" if chat_title else ""
        await message.answer(f"Напоминание отправлено в чат{title_part}.", reply_markup=admin_menu_keyboard())

    async def answer_question(
        message: Message,
        question: str,
        state: FSMContext,
        mode: str = "training_qa",
        force_rag: bool = True,
        extra_context: str | None = None,
        lesson_key: str | None = None,
        lesson_date: date | None = None,
        document_ids: list[int] | None = None,
        telegram_user=None,
    ) -> None:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        user_id = user.id
        thinking_message: Message | None = None
        try:
            rate_count = await MessageRepository.count_last_minute(session, user_id)
            if rate_count >= container.settings.max_user_questions_per_minute:
                await message.answer("Слишком много запросов за минуту. Попробуй чуть позже.")
                return

            thinking_message = await message.answer(random.choice(THINKING_MESSAGES))
            result = await container.chat_service.answer_question(
                session=session,
                user=user,
                question=question,
                mode=mode,
                force_rag=force_rag,
                extra_context=extra_context,
                lesson_key=lesson_key,
                lesson_date=lesson_date,
                document_ids=document_ids,
            )
            await message.answer(result.text)
            await message.answer("Если хочешь продолжить, выбери действие:", reply_markup=user_main_menu())
            await state.update_data(last_question=question, last_answer=result.text)
        except Exception as exc:
            logger.exception("answer_question_failed")
            await session.rollback()
            await ErrorRepository.create(
                session=session,
                context="answer_question",
                error_text=str(exc),
                user_id=user_id,
            )
            await message.answer("Сейчас не получилось получить ответ от модели. Попробуй позже.")
        finally:
            await _delete_message_safely(thinking_message)
            await session.close()

    async def answer_material_question(
        message: Message,
        document_id: int,
        question: str,
        state: FSMContext,
    ) -> None:
        user, session = await get_user_and_session(message)
        user_id = user.id
        thinking_message: Message | None = None
        try:
            rate_count = await MessageRepository.count_last_minute(session, user_id)
            if rate_count >= container.settings.max_user_questions_per_minute:
                await message.answer("Слишком много запросов за минуту. Попробуй чуть позже.")
                return

            thinking_message = await message.answer(random.choice(THINKING_MESSAGES))
            result = await container.chat_service.answer_document_question(
                session=session,
                user=user,
                question=question,
                document_id=document_id,
            )
            await message.answer(result.text)
            await message.answer("Если хочешь продолжить, выбери действие:", reply_markup=user_main_menu())
            await state.update_data(last_question=question, last_answer=result.text)
        except Exception as exc:
            logger.exception("answer_material_question_failed")
            await session.rollback()
            await ErrorRepository.create(
                session=session,
                context="answer_material_question",
                error_text=str(exc),
                user_id=user_id,
            )
            await message.answer("Сейчас не получилось получить ответ по материалу. Попробуй позже.")
        finally:
            await _delete_message_safely(thinking_message)
            await session.close()

    async def send_materials_list(message: Message, telegram_user=None) -> None:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            docs = await DocumentRepository.list_visible_materials(session, user.id, limit=50)
        finally:
            await session.close()

        if not docs:
            await message.answer(
                "Материалы программы пока не загружены.\n\n"
                "Когда организаторы добавят материалы занятий, они появятся здесь.",
                reply_markup=user_main_menu(),
            )
            return

        lines = [
            "Материалы программы:",
            "",
        ]
        for doc in docs[:20]:
            lesson_hint = f" ({format_lesson_date(doc.lesson_date)})" if doc.lesson_date else ""
            lines.append(f"- {doc.title}{lesson_hint}")
        lines.extend(
            [
                "",
                "Можешь задать вопрос по любому из этих материалов обычным сообщением.",
            ]
        )
        await message.answer("\n".join(lines), reply_markup=user_main_menu())

    async def send_materials_by_lookup(message: Message, lookup: dict[str, Any], telegram_user=None) -> bool:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            docs = await DocumentRepository.list_visible_by_lesson(
                session=session,
                user_id=user.id,
                lesson_key=lookup.get("lesson_key"),
                lesson_date=lookup.get("lesson_date"),
                limit=50,
            )
            media_items = await ProgramMediaRepository.list_by_lesson(
                session=session,
                lesson_key=lookup.get("lesson_key"),
                lesson_date=lookup.get("lesson_date"),
                limit=20,
            )
            homeworks = await HomeworkRepository.list_by_lesson(
                session=session,
                lesson_key=lookup.get("lesson_key"),
                lesson_date=lookup.get("lesson_date"),
                limit=20,
            )
        finally:
            await session.close()

        lookup_parts = []
        if lookup.get("label"):
            lookup_parts.append(str(lookup["label"]))
        if lookup.get("module_number"):
            lookup_parts.append(f"урок/модуль {lookup['module_number']}")
        if lookup.get("lesson_date"):
            lookup_parts.append(f"дата {format_lesson_date(lookup['lesson_date'])}")
        lookup_text = ", ".join(lookup_parts) or "указанная привязка"

        if not docs and not media_items and not homeworks:
            await message.answer(
                f"Материалы по запросу «{lookup_text}» пока не добавлены.",
                reply_markup=user_main_menu(),
            )
            return True

        if docs:
            lines = [
                f"Нашёл текстовые материалы: {lookup_text}.",
                "",
            ]
            for doc in docs[:20]:
                date_hint = format_lesson_date(doc.lesson_date)
                date_suffix = f" ({date_hint})" if date_hint != "без даты" else ""
                lines.append(f"- {doc.title}{date_suffix}")
            lines.extend(
                [
                    "",
                    "Можешь задать вопрос по этим материалам обычным сообщением.",
                ]
            )
            await message.answer("\n".join(lines), reply_markup=user_main_menu())

        if homeworks:
            lines = [
                f"Нашёл домашние задания: {lookup_text}.",
                "",
            ]
            for homework in homeworks[:20]:
                lines.append(f"- {homework.title} ({homework_lesson_label(homework)})")
            lines.append("")
            lines.append("Выбери нужное задание кнопкой ниже.")
            await message.answer("\n".join(lines), reply_markup=homework_list_keyboard(homeworks))

        videos = [media for media in media_items if media.media_type == "video"]
        podcasts = [media for media in media_items if media.media_type == "podcast"]
        if videos:
            await message.answer(
                f"Нашёл видео: {lookup_text}. Выбери нужную запись:",
                reply_markup=media_list_keyboard(videos, media_type="video"),
            )
        if podcasts:
            await message.answer(
                f"Нашёл подкасты: {lookup_text}. Выбери нужный файл:",
                reply_markup=media_list_keyboard(podcasts, media_type="podcast"),
            )
        if not docs and not homeworks and (videos or podcasts):
            await message.answer("После просмотра можно вернуться в главное меню.", reply_markup=user_main_menu())
        return True

    def media_caption(media) -> str | None:
        if media.media_type == "schedule_image":
            return None
        module_text = f"Модуль {media.module_number}" if media.module_number else "Без модуля"
        date_text = format_lesson_date(media.lesson_date)
        return f"{media.title}\n{module_text}\nДата: {date_text}"

    async def send_media_asset(message: Message, media) -> None:
        caption = media_caption(media)
        try:
            if media.telegram_kind == "video":
                await message.answer_video(video=media.telegram_file_id, caption=caption, parse_mode=None)
                return
            if media.telegram_kind == "audio":
                await message.answer_audio(audio=media.telegram_file_id, caption=caption, parse_mode=None)
                return
            if media.telegram_kind == "voice":
                await message.answer_voice(voice=media.telegram_file_id, caption=caption, parse_mode=None)
                return
            if media.telegram_kind == "photo":
                await message.answer_photo(photo=media.telegram_file_id, caption=caption, parse_mode=None)
                return
            await message.answer_document(document=media.telegram_file_id, caption=caption, parse_mode=None)
        except TelegramBadRequest:
            logger.exception("send_media_asset_failed")
            await message.answer(
                f"Не получилось отправить файл «{media.title}». "
                "Попробуй открыть раздел материалов ещё раз или напиши организаторам."
            )

    async def show_media_picker(
        message: Message,
        media_type: str,
        title: str,
        empty_text: str,
        include_docs_button: bool = False,
        empty_reply_markup=None,
    ) -> bool:
        async with SessionLocal() as session:
            media_items = await ProgramMediaRepository.list_by_type(session, media_type=media_type, limit=10)

        if not media_items:
            await message.answer(empty_text, reply_markup=empty_reply_markup or user_main_menu())
            return False

        await message.answer(
            title,
            reply_markup=media_list_keyboard(
                media_items=media_items,
                media_type=media_type,
                include_docs_button=include_docs_button,
            ),
        )
        return True

    def schedule_lesson_date_text(lesson) -> str:
        if lesson.date_text:
            return lesson.date_text
        if lesson.date_start and lesson.date_end:
            return f"{format_lesson_date(lesson.date_start)} - {format_lesson_date(lesson.date_end)}"
        return format_lesson_date(lesson.date_start)

    def format_schedule_overview(lessons) -> str:
        if not lessons:
            return "Расписание пока не заполнено."

        lines = ["Расписание Лиги Лидеров"]
        current_block_key = None
        for lesson in lessons:
            if lesson.block_key != current_block_key:
                current_block_key = lesson.block_key
                lines.extend(["", f"Блок {lesson.block_order}. {lesson.block_title}"])
            lesson_line = f"- {schedule_lesson_date_text(lesson)}: {lesson.lesson_title}"
            if lesson.speaker:
                lesson_line += f" ({lesson.speaker})"
            lines.append(lesson_line)
        return "\n".join(lines)

    def format_lesson_card(lesson) -> str:
        lines = [
            lesson.lesson_title,
            "",
            f"Сезон: {lesson.season_title}",
            f"Блок: {lesson.block_title}",
            f"Дата: {schedule_lesson_date_text(lesson)}",
        ]
        if lesson.speaker:
            lines.append(f"Спикер: {lesson.speaker}")
        return "\n".join(lines)

    async def build_schedule_text_and_seasons() -> tuple[str, list[tuple[str, str]]]:
        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_active(session)
            seasons = await ProgramLessonRepository.list_seasons(session)
        return format_schedule_overview(lessons), seasons

    async def build_schedule_context_for_llm() -> str:
        schedule_text, _ = await build_schedule_text_and_seasons()
        return f"Служебное расписание программы:\n{schedule_text}"

    async def send_schedule_image(message: Message) -> None:
        async with SessionLocal() as session:
            media = await ProgramMediaRepository.latest_by_type(session, "schedule_image")
        if media is not None:
            await send_media_asset(message, media)

    async def send_records_and_materials(message: Message, telegram_user=None) -> None:
        has_video = await show_media_picker(
            message,
            media_type="video",
            title="Выбери запись занятия:",
            empty_text="Видео записей пока не загружены. Показываю текстовые материалы.",
            include_docs_button=True,
        )
        if not has_video:
            await send_materials_list(message, telegram_user=telegram_user)

    async def send_podcast_text_summary(message: Message, state: FSMContext, telegram_user=None) -> None:
        await message.answer("Собираю текстовую подкаст-выжимку по загруженным материалам.")
        await answer_question(
            message,
            "Сделай короткий текстовый подкаст-конспект по материалам занятий сезона 1. "
            "Формат: 5 ключевых мыслей, практический вывод, что попробовать на работе.",
            state,
            mode="materials_podcast_summary",
            telegram_user=telegram_user,
        )
        await state.clear()

    async def send_homework_list(message: Message) -> None:
        async with SessionLocal() as session:
            homeworks = await HomeworkRepository.list_active(session)

        if not homeworks:
            await message.answer(
                "Домашние задания пока не добавлены.\n\n"
                "Когда организаторы добавят ДЗ, они появятся здесь.",
                reply_markup=homework_list_keyboard([]),
                parse_mode=None,
            )
            return

        lines = ["Список домашних заданий:", ""]
        for homework in homeworks[:20]:
            lines.append(f"- {homework.title} ({homework_lesson_label(homework)})")
        lines.extend(["", "Выбери задание кнопкой ниже или задай свой вопрос по домашке."])
        await message.answer("\n".join(lines), reply_markup=homework_list_keyboard(homeworks))

    async def send_homework_item(message: Message, homework_id: int) -> None:
        async with SessionLocal() as session:
            homework = await HomeworkRepository.get_by_id(session, homework_id)

        if homework is None or homework.status != "active":
            await message.answer("Не нашёл такое домашнее задание. Показываю список актуальных заданий.")
            await send_homework_list(message)
            return

        lines = [
            f"Домашнее задание: {escape(homework.title)}",
            f"Привязка: {escape(homework_lesson_label(homework))}",
        ]
        if homework.description:
            lines.extend(["", escape(homework.description)])
        if homework.moodle_url:
            lines.extend(["", f"Ссылка для сдачи: {escape(homework.moodle_url)}"])
        if homework.document_id:
            lines.extend(["", "Файл задания прикреплён к этому ДЗ."])
        await message.answer("\n".join(lines), reply_markup=homework_detail_keyboard(homework.id))

    async def start_homework_help(message: Message, state: FSMContext, homework_id: int | None = None) -> None:
        await state.set_state(UserFlow.waiting_for_homework_help_question)
        await state.update_data(selected_homework_id=homework_id)
        suffix = ""
        if homework_id:
            suffix = "\n\nЯ буду учитывать выбранное домашнее задание."
        await message.answer(
            f"{HOMEWORK_HELP_PROMPT}{suffix}",
            reply_markup=user_main_menu(),
        )

    async def build_admin_status_report() -> str:
        lines = ["Статус бота:"]

        db_started = time.monotonic()
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
                totals = await StatsRepository.totals(session)
                latest_errors = await ErrorRepository.latest(session, limit=3)
            db_ms = int((time.monotonic() - db_started) * 1000)
            lines.append(f"- База данных: OK ({db_ms} мс)")
            lines.append(
                f"- RAG: документов={totals['documents']}, чанков={totals['chunks']}, вопросов={totals['messages']}"
            )
        except Exception as exc:
            lines.append(f"- База данных: ошибка ({str(exc)[:120]})")
            latest_errors = []

        if container.settings.llm_provider == "mock":
            lines.append("- LLM chat: mock-режим")
            lines.append("- Embeddings: mock-режим")
        else:
            chat_started = time.monotonic()
            try:
                await container.llm_client.chat_completion(
                    system_prompt="Ты healthcheck. Ответь только OK.",
                    user_prompt="Ответь только OK.",
                    temperature=0,
                )
                chat_ms = int((time.monotonic() - chat_started) * 1000)
                lines.append(f"- LLM chat: OK ({chat_ms} мс, модель {container.settings.openai_chat_model})")
            except Exception as exc:
                lines.append(f"- LLM chat: ошибка ({str(exc)[:120]})")

            embedding_started = time.monotonic()
            try:
                embedding = await container.llm_client.create_embedding("healthcheck")
                embedding_ms = int((time.monotonic() - embedding_started) * 1000)
                lines.append(
                    f"- Embeddings: OK ({embedding_ms} мс, размерность {len(embedding)}, модель {container.settings.openai_embedding_model})"
                )
            except Exception as exc:
                lines.append(f"- Embeddings: ошибка ({str(exc)[:120]})")

        lines.append(f"- Режим запуска: {container.settings.bot_mode}")
        lines.append(f"- Окружение: {container.settings.env}")
        lines.append(f"- Лимит файла: {container.settings.max_file_size_mb} МБ")
        lines.append(
            f"- Уведомления: {'включены' if container.settings.notifications_enabled else 'выключены'}, "
            f"таймзона={container.settings.notification_timezone}"
        )
        try:
            async with SessionLocal() as session:
                ics_filename = await AppSettingRepository.get_value(session, NOTIFICATION_ICS_FILENAME_KEY)
        except Exception:
            ics_filename = None
        lines.append(f"- ICS для уведомлений: {ics_filename or 'не загружен'}")

        lines.append("")
        lines.append("Последние ошибки:")
        if latest_errors:
            for error in latest_errors:
                lines.append(f"- {error.context}: {error.error_text[:120]}")
        else:
            lines.append("- Ошибок нет")

        return "\n".join(lines)

    def parse_caption_metadata(caption: str | None) -> dict[str, Any]:
        if not caption:
            return {}
        module_number: int | None = None
        module_title: str | None = None
        material_type: str | None = None

        module_match = re.search(r"module\s*[:=]\s*(\d+)", caption, flags=re.IGNORECASE)
        if module_match:
            module_number = int(module_match.group(1))
        module_title_match = re.search(r"module_title\s*[:=]\s*([^\n;]+)", caption, flags=re.IGNORECASE)
        if module_title_match:
            module_title = module_title_match.group(1).strip()
        type_match = re.search(r"type\s*[:=]\s*([^\n;]+)", caption, flags=re.IGNORECASE)
        if type_match:
            material_type = type_match.group(1).strip().lower()

        return {
            "module_number": module_number,
            "module_title": module_title,
            "material_type": material_type,
        }

    def parse_material_question(text_value: str | None) -> tuple[int, str] | None:
        if not text_value:
            return None
        match = re.match(
            r"^\s*(?:материал|файл|документ)\s*(?:id\s*=?\s*)?(?:№\s*)?(\d+)\s*[:\-—]\s*(.+?)\s*$",
            text_value,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        question = match.group(2).strip()
        if not question:
            return None
        return int(match.group(1)), question

    @router.callback_query(F.data.startswith("feedback:"))
    async def feedback_callback_handler(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            await callback.answer("Не получилось сохранить оценку.")
            return
        _, message_id_raw, value = parts
        if value not in {"yes", "no"}:
            await callback.answer("Не получилось сохранить оценку.")
            return
        try:
            message_id = int(message_id_raw)
        except ValueError:
            await callback.answer("Не получилось сохранить оценку.")
            return

        async with SessionLocal() as session:
            user = await UserRepository.upsert_telegram_user(
                session=session,
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                is_admin=callback.from_user.id in container.settings.admin_ids,
            )
            await MessageFeedbackRepository.upsert(
                session=session,
                message_id=message_id,
                user_id=user.id,
                value=value,
            )
        await callback.answer("Спасибо, сохранил оценку.")
        if callback.message:
            if value == "yes":
                await callback.message.answer("Спасибо! Рад, что ответ был полезен.", reply_markup=user_main_menu())
            else:
                await callback.message.answer(
                    "Спасибо, это поможет улучшить ответы. Что именно было не так?",
                    reply_markup=feedback_reason_keyboard(message_id),
                )

    @router.callback_query(F.data.startswith("feedback_reason:"))
    async def feedback_reason_callback_handler(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            await callback.answer("Не получилось сохранить причину.")
            return
        _, message_id_raw, reason = parts
        allowed_reasons = {"not_found", "too_general", "misunderstood", "other"}
        if reason not in allowed_reasons:
            await callback.answer("Не получилось сохранить причину.")
            return
        try:
            message_id = int(message_id_raw)
        except ValueError:
            await callback.answer("Не получилось сохранить причину.")
            return

        async with SessionLocal() as session:
            user = await UserRepository.upsert_telegram_user(
                session=session,
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                is_admin=is_admin_user_id(callback.from_user.id),
            )
            await MessageFeedbackRepository.upsert(
                session=session,
                message_id=message_id,
                user_id=user.id,
                value="no",
                reason=reason,
            )

        await callback.answer("Спасибо, сохранил причину.")
        if callback.message:
            await callback.message.answer(
                "Принял. Можно переформулировать вопрос или уточнить материал, а я попробую ответить точнее.",
                reply_markup=user_main_menu(),
            )

    @router.callback_query(F.data == "menu:main")
    async def inline_main_menu_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer("Выбери действие:", reply_markup=user_main_menu())

    @router.callback_query(F.data == "homework:list")
    async def homework_list_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_homework_list(callback.message)

    @router.callback_query(F.data.startswith("homework:item:"))
    async def homework_item_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        try:
            homework_id = int((callback.data or "").split(":")[-1])
        except ValueError:
            if callback.message:
                await callback.message.answer("Не понял, какое домашнее задание открыть.")
            return
        if callback.message:
            await send_homework_item(callback.message, homework_id)

    @router.callback_query(F.data.startswith("homework:help"))
    async def homework_help_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await upsert_telegram_user(callback.from_user)
        await state.clear()
        await callback.answer()
        homework_id = None
        parts = (callback.data or "").split(":")
        if len(parts) == 3:
            try:
                homework_id = int(parts[2])
            except ValueError:
                homework_id = None
        if callback.message:
            await start_homework_help(callback.message, state, homework_id=homework_id)

    @router.callback_query(F.data.startswith("start_notification_time:"))
    async def start_notification_time_callback_handler(callback: CallbackQuery) -> None:
        time_value = (callback.data or "").split(":", 1)[1]
        if time_value not in NOTIFICATION_TIME_OPTIONS:
            await callback.answer("Не понял время уведомлений.")
            return
        async with SessionLocal() as session:
            user = await UserRepository.upsert_telegram_user(
                session=session,
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                is_admin=is_admin_user_id(callback.from_user.id),
            )
            await UserNotificationSettingRepository.upsert_time(session, user.id, time_value)
        await callback.answer("Сохранил время уведомлений.")
        if callback.message:
            await callback.message.answer(
                f"Готово. Уведомления будут приходить в {time_value} по московскому времени.",
                reply_markup=user_main_menu(),
            )

    @router.callback_query(F.data.startswith("question_section:"))
    async def question_section_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        section = (callback.data or "").split(":", 1)[1]
        if section not in {"program", "technical", "other"}:
            await callback.answer("Не понял раздел вопроса.")
            return
        if section == "technical":
            await state.clear()
            await callback.answer()
            if callback.message:
                await callback.message.answer(
                    "По техническим вопросам лучше сразу написать Илье в Telegram: @reptiloid0.\n\n"
                    "Он поможет с доступом, платформой ПРОГРЕСС, Moodle, записями занятий, "
                    "загрузкой домашних заданий и ошибками в работе бота.",
                    reply_markup=user_main_menu(),
                )
            return
        await state.set_state(UserFlow.waiting_for_categorized_question)
        await state.update_data(question_section=section)
        await callback.answer()
        if callback.message:
            await callback.message.answer("Напиши свой вопрос.", reply_markup=user_main_menu())

    @router.message(Command("set_group_chat"))
    async def set_group_chat_handler(message: Message) -> None:
        if not is_group_chat(message):
            await message.answer(
                "Эту команду нужно отправить внутри группового чата программы, куда добавлен бот."
            )
            return
        if not is_admin(message):
            # В группе молчим для не-админов, чтобы не провоцировать лишний шум.
            return

        user = await ensure_user(message)
        chat_title = message.chat.title or str(message.chat.id)
        async with SessionLocal() as session:
            await AppSettingRepository.upsert(
                session,
                key=ANNOUNCEMENT_CHAT_ID_KEY,
                value=str(message.chat.id),
                updated_by_user_id=user.id,
            )
            await AppSettingRepository.upsert(
                session,
                key=ANNOUNCEMENT_CHAT_TITLE_KEY,
                value=chat_title,
                updated_by_user_id=user.id,
            )

        await message.answer(
            "Готово, этот чат привязан для напоминаний.\n\n"
            "Обычные сообщения участников я здесь буду игнорировать. "
            "Сценарий с вопросами остаётся в личном чате с ботом."
        )

    @router.message(Command("group_chat_status"))
    async def group_chat_status_handler(message: Message) -> None:
        if not is_admin(message):
            if not is_group_chat(message):
                await message.answer("Эта команда доступна только администратору.")
            return
        await ensure_user(message)
        async with SessionLocal() as session:
            chat_id, chat_title = await get_announcement_chat(session)
        if chat_id is None:
            await message.answer(
                "Групповой чат пока не привязан.\n\n"
                "Когда чат появится, добавь туда бота и отправь в этом чате /set_group_chat."
            )
            return
        title_part = f" «{chat_title}»" if chat_title else ""
        await message.answer(f"Привязанный чат для напоминаний:{title_part}\nchat_id={chat_id}")

    @router.message(Command("send_reminder"))
    async def send_reminder_command_handler(message: Message) -> None:
        if not is_admin(message):
            if not is_group_chat(message):
                await message.answer("Эта команда доступна только администратору.")
            return
        user = await ensure_user(message)
        await send_reminder_to_group(message, command_argument(message.text), user.id)

    @router.message(F.chat.type.in_(list(GROUP_CHAT_TYPES)))
    async def group_silence_handler(message: Message) -> None:
        # Односторонний режим для группы: все обычные сообщения игнорируем.
        return

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer(await get_bot_text("welcome"), reply_markup=user_main_menu(), link_preview_options=NO_LINK_PREVIEW)
        await message.answer(
            "Я буду напоминать тебе о занятиях и домашних заданиях. "
            "Выбери время, когда тебе будет удобно получать уведомления:",
            reply_markup=start_notification_time_keyboard(),
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(await get_bot_text("help"), reply_markup=user_main_menu(), link_preview_options=NO_LINK_PREVIEW)

    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer("Действие отменено. Вернул в главное меню.", reply_markup=user_main_menu())

    @router.message(Command("admin"))
    @router.message(F.text == "Админ: меню")
    async def admin_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())

    @router.message(F.text == "Админ: напоминание")
    async def admin_reminder_prompt_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            chat_id, chat_title = await get_announcement_chat(session)

        chat_line = "чат пока не привязан"
        if chat_id is not None:
            chat_line = f"привязан чат «{chat_title or chat_id}»"

        await state.set_state(AdminFlow.waiting_for_reminder_text)
        await message.answer(
            "Пришли текст напоминания одним сообщением.\n\n"
            f"Текущий статус: {chat_line}.\n\n"
            "Если удобнее командой: /send_reminder текст напоминания",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_reminder_text, F.text)
    async def admin_reminder_text_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        admin_navigation_texts = {
            "Админ: меню",
            "Админ: статус",
            "Админ: загрузить материал",
            "Админ: материалы",
            "Админ: тексты",
            "Админ: статистика",
            "Админ: напоминание",
            "Админ: загрузить ICS",
            "Админ: загрузить медиа",
            "Админ: расходы",
            "Главное меню",
        }
        if message.text in admin_navigation_texts:
            await state.clear()
            reply_markup = admin_menu_keyboard() if message.text.startswith("Админ:") else user_main_menu()
            await message.answer(
                "Напоминание не отправил. Если нужно отправить текст в чат, нажми «Админ: напоминание» ещё раз.",
                reply_markup=reply_markup,
            )
            return
        user = await ensure_user(message)
        await send_reminder_to_group(message, message.text, user.id)
        await state.clear()

    @router.message(Command("upload_global_material"))
    @router.message(F.text == "Админ: загрузить материал")
    async def admin_upload_command(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.set_state(AdminFlow.waiting_for_material_season)
        await message.answer(
            "Запускаю мастер загрузки материала.\n\n"
            "Шаг 1: выбери сезон материала.",
            reply_markup=admin_material_season_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_material_season, F.text.in_(["Материал: Сезон 1. Бизнес-консалтинг", "Материал: без сезона"]))
    async def admin_material_season_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Материал: без сезона":
            await state.update_data(material_season_key=None, material_season_title=None)
            await state.set_state(AdminFlow.waiting_for_material_module)
            await message.answer(
                "Шаг 2: выбери привязку материала.\n\n"
                "Это запасной путь для общих материалов без привязки к расписанию.",
                reply_markup=admin_material_module_keyboard(),
            )
            return

        await state.update_data(material_season_key="s1", material_season_title="Бизнес")
        await state.set_state(AdminFlow.waiting_for_material_block)
        await message.answer(
            "Шаг 2: выбери блок программы.",
            reply_markup=await admin_blocks_keyboard("s1"),
        )

    @router.message(AdminFlow.waiting_for_material_block, F.text)
    async def admin_material_block_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        data = await state.get_data()
        season_key = data.get("material_season_key") or "s1"
        async with SessionLocal() as session:
            blocks = await ProgramLessonRepository.list_blocks(session, season_key)
        block_by_label = {block_button_label(block): block for block in blocks}
        block = block_by_label.get(message.text)
        if block is None:
            await message.answer("Выбери блок кнопкой ниже или нажми «Админ: меню».", reply_markup=await admin_blocks_keyboard(season_key))
            return
        block_key, block_title, block_order = block
        await state.update_data(material_block_key=block_key, material_block_title=block_title, material_block_order=block_order)
        await state.set_state(AdminFlow.waiting_for_material_lesson)
        await message.answer(
            "Шаг 3: выбери занятие или весь блок.",
            reply_markup=await admin_lessons_keyboard(block_key),
        )

    @router.message(AdminFlow.waiting_for_material_lesson, F.text)
    async def admin_material_lesson_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        data = await state.get_data()
        block_key = data.get("material_block_key")
        block_title = data.get("material_block_title")
        if not block_key or not block_title:
            await state.clear()
            await message.answer("Потерял выбранный блок. Начни загрузку заново.", reply_markup=admin_menu_keyboard())
            return

        if message.text == "Материал всего блока":
            await state.update_data(**block_to_state_payload("material", block_key, block_title))
            await state.set_state(AdminFlow.waiting_for_material_type)
            await message.answer("Шаг 4: выбери тип материала.", reply_markup=admin_material_type_keyboard())
            return

        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_by_block(session, block_key)
        lesson_by_label = {lesson_button_label(lesson): lesson for lesson in lessons}
        lesson = lesson_by_label.get(message.text)
        if lesson is None:
            await message.answer("Выбери занятие кнопкой ниже или нажми «Админ: меню».", reply_markup=await admin_lessons_keyboard(block_key))
            return
        await state.update_data(**lesson_to_state_payload("material", lesson))
        await state.set_state(AdminFlow.waiting_for_material_type)
        await message.answer("Шаг 4: выбери тип материала.", reply_markup=admin_material_type_keyboard())

    @router.message(AdminFlow.waiting_for_material_season)
    async def admin_material_season_invalid_handler(message: Message) -> None:
        await message.answer("Выбери сезон кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_material_season_keyboard())

    @router.message(AdminFlow.waiting_for_material_module, F.text.startswith("Материал: "))
    async def admin_material_module_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        data = await state.get_data()
        payload = lesson_payload("material", data.get("material_season_title"), message.text)
        await state.update_data(**payload)
        await state.set_state(AdminFlow.waiting_for_material_date)
        await message.answer(
            "Шаг 3 из 5: укажи дату урока.\n\n"
            "Можно написать `31.05.2026`, `31.05` или `31 мая`. "
            "Если материал общий и без даты, нажми «Дата: без даты».",
            reply_markup=admin_lesson_date_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_material_module)
    async def admin_material_module_invalid_handler(message: Message) -> None:
        await message.answer("Выбери модуль кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_material_module_keyboard())

    @router.message(AdminFlow.waiting_for_material_date, F.text)
    async def admin_material_date_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        try:
            lesson_date = parse_lesson_date_input(message.text)
        except ValueError:
            await message.answer(
                "Не распознал дату. Напиши в формате `31.05.2026`, `31.05`, `31 мая` "
                "или нажми «Дата: без даты».",
                reply_markup=admin_lesson_date_keyboard(),
                parse_mode=None,
            )
            return

        await state.update_data(material_lesson_date=lesson_date.isoformat() if lesson_date else None)
        await state.set_state(AdminFlow.waiting_for_material_type)
        await message.answer("Шаг 4 из 5: выбери тип материала.", reply_markup=admin_material_type_keyboard())

    @router.message(AdminFlow.waiting_for_material_type, F.text.startswith("Тип: "))
    async def admin_material_type_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        type_map = {
            "Тип: материалы занятия": "lesson_material",
            "Тип: домашнее задание": "homework",
            "Тип: саммари": "summary",
            "Тип: расписание": "schedule",
            "Тип: другое": None,
        }
        material_type = type_map.get(message.text)
        await state.update_data(material_type=material_type)
        data = await state.get_data()
        season_title = data.get("material_season_title") or "без сезона"
        module_number = data.get("material_module_number")
        module_title = data.get("material_module_title")
        lesson_date_raw = data.get("material_lesson_date")
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
        module_text = module_title or (f"урок/модуль {module_number}" if module_number else "общий материал")
        type_text = message.text.replace("Тип: ", "")
        if material_type == "homework":
            await state.set_state(AdminFlow.waiting_for_homework_link)
            await message.answer(
                "Шаг 5 из 6: пришли ссылку на Moodle/ПРОГРЕСС для сдачи домашнего задания.\n\n"
                "Если ссылки пока нет, нажми «Ссылка: без ссылки».",
                reply_markup=admin_homework_link_keyboard(),
                parse_mode=None,
            )
            return

        await state.set_state(AdminFlow.waiting_for_global_file)
        await message.answer(
            "Шаг 5 из 5: пришли файл PDF/DOCX/PPTX/TXT.\n\n"
            f"Будет сохранено так:\n"
            f"- сезон: {season_title}\n"
            f"- привязка: {module_text}\n"
            f"- дата: {format_lesson_date(lesson_date)}\n"
            f"- тип: {type_text}",
            reply_markup=admin_menu_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_material_type)
    async def admin_material_type_invalid_handler(message: Message) -> None:
        await message.answer("Выбери тип материала кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_material_type_keyboard())

    @router.message(AdminFlow.waiting_for_homework_link, F.text)
    async def admin_homework_link_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        try:
            moodle_url = normalize_homework_link(message.text)
        except ValueError:
            await message.answer(
                "Ссылка должна начинаться с `https://` или `http://`. "
                "Если ссылки пока нет, нажми «Ссылка: без ссылки».",
                reply_markup=admin_homework_link_keyboard(),
                parse_mode=None,
            )
            return

        await state.update_data(homework_moodle_url=moodle_url)
        data = await state.get_data()
        season_title = data.get("material_season_title") or "без сезона"
        module_number = data.get("material_module_number")
        module_title = data.get("material_module_title")
        lesson_date_raw = data.get("material_lesson_date")
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
        module_text = module_title or (f"урок/модуль {module_number}" if module_number else "общий материал")
        link_text = moodle_url or "без ссылки"
        await state.set_state(AdminFlow.waiting_for_global_file)
        await message.answer(
            "Шаг 6 из 6: пришли файл PDF/DOCX/PPTX/TXT с домашним заданием.\n\n"
            f"Будет сохранено так:\n"
            f"- сезон: {season_title}\n"
            f"- привязка: {module_text}\n"
            f"- дата: {format_lesson_date(lesson_date)}\n"
            f"- тип: домашнее задание\n"
            f"- ссылка: {link_text}",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "Админ: загрузить медиа")
    async def admin_media_upload_start_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.set_state(AdminFlow.waiting_for_media_type)
        await message.answer(
            "Запускаю мастер загрузки медиа.\n\n"
            "Шаг 1 из 4: выбери тип файла.",
            reply_markup=admin_media_type_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_media_type, F.text.in_(["Медиа: видео", "Медиа: подкаст", "Медиа: картинка"]))
    async def admin_media_type_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        media_type_by_button = {
            "Медиа: видео": "video",
            "Медиа: подкаст": "podcast",
            "Медиа: картинка": "schedule_image",
        }
        media_type = media_type_by_button[message.text]
        await state.update_data(media_type=media_type)
        if media_type == "schedule_image":
            await state.update_data(
                media_module_number=None,
                media_module_title="Расписание Лиги Лидеров",
                media_lesson_key="schedule",
                media_lesson_date=None,
            )
            await state.set_state(AdminFlow.waiting_for_media_file)
            await message.answer(
                "Пришли картинку расписания.\n\n"
                "Она будет показываться пользователю в разделе «Расписание Лиги Лидеров». "
                "Название можно написать в подписи к картинке.",
                reply_markup=admin_menu_keyboard(),
            )
            return
        await state.set_state(AdminFlow.waiting_for_media_block)
        await message.answer(
            "Шаг 2: выбери блок программы.",
            reply_markup=await admin_blocks_keyboard("s1"),
        )

    @router.message(AdminFlow.waiting_for_media_type)
    async def admin_media_type_invalid_handler(message: Message) -> None:
        await message.answer("Выбери тип медиа кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_media_type_keyboard())

    @router.message(AdminFlow.waiting_for_media_block, F.text)
    async def admin_media_block_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        async with SessionLocal() as session:
            blocks = await ProgramLessonRepository.list_blocks(session, "s1")
        block_by_label = {block_button_label(block): block for block in blocks}
        block = block_by_label.get(message.text)
        if block is None:
            await message.answer("Выбери блок кнопкой ниже или нажми «Админ: меню».", reply_markup=await admin_blocks_keyboard("s1"))
            return
        block_key, block_title, block_order = block
        await state.update_data(media_block_key=block_key, media_block_title=block_title, media_block_order=block_order)
        await state.set_state(AdminFlow.waiting_for_media_lesson)
        await message.answer(
            "Шаг 3: выбери занятие или весь блок.",
            reply_markup=await admin_lessons_keyboard(block_key, whole_label="Медиа всего блока"),
        )

    @router.message(AdminFlow.waiting_for_media_lesson, F.text)
    async def admin_media_lesson_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        data = await state.get_data()
        block_key = data.get("media_block_key")
        block_title = data.get("media_block_title")
        if not block_key or not block_title:
            await state.clear()
            await message.answer("Потерял выбранный блок. Начни загрузку заново.", reply_markup=admin_menu_keyboard())
            return

        if message.text == "Медиа всего блока":
            await state.update_data(**block_to_state_payload("media", block_key, block_title))
            await state.set_state(AdminFlow.waiting_for_media_file)
            await message.answer(
                "Шаг 4: пришли файл в Telegram.\n\n"
                f"- привязка: {block_title}\n"
                "Название можно написать в подписи к файлу. Если подписи нет, возьму имя файла.",
                reply_markup=admin_menu_keyboard(),
            )
            return

        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_by_block(session, block_key)
        lesson_by_label = {lesson_button_label(lesson): lesson for lesson in lessons}
        lesson = lesson_by_label.get(message.text)
        if lesson is None:
            await message.answer(
                "Выбери занятие кнопкой ниже или нажми «Админ: меню».",
                reply_markup=await admin_lessons_keyboard(block_key, whole_label="Медиа всего блока"),
            )
            return
        await state.update_data(**lesson_to_state_payload("media", lesson))
        await state.set_state(AdminFlow.waiting_for_media_file)
        await message.answer(
            "Шаг 4: пришли файл в Telegram.\n\n"
            f"- привязка: {lesson.block_title}: {lesson.lesson_title}\n"
            f"- дата: {format_lesson_date(lesson.date_start)}\n\n"
            "Название можно написать в подписи к файлу. Если подписи нет, возьму имя файла.",
            reply_markup=admin_menu_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_media_module, F.text.startswith("Медиа: "))
    async def admin_media_module_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        payload = lesson_payload("media", "Сезон 1. Бизнес-консалтинг", message.text)
        await state.update_data(**payload)
        await state.set_state(AdminFlow.waiting_for_media_date)
        await message.answer(
            "Шаг 3 из 4: укажи дату урока.\n\n"
            "Можно написать `31.05.2026`, `31.05` или `31 мая`. "
            "Если медиа общее и без даты, нажми «Дата: без даты».",
            reply_markup=admin_lesson_date_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_media_date, F.text)
    async def admin_media_date_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return
        try:
            lesson_date = parse_lesson_date_input(message.text)
        except ValueError:
            await message.answer(
                "Не распознал дату. Напиши в формате `31.05.2026`, `31.05`, `31 мая` "
                "или нажми «Дата: без даты».",
                reply_markup=admin_lesson_date_keyboard(),
                parse_mode=None,
            )
            return

        await state.update_data(media_lesson_date=lesson_date.isoformat() if lesson_date else None)
        await state.set_state(AdminFlow.waiting_for_media_file)

        data = await state.get_data()
        media_type = data.get("media_type")
        module_number = data.get("media_module_number")
        type_text_by_media = {
            "video": "видео",
            "podcast": "аудиоподкаст",
            "image": "картинка",
            "schedule_image": "картинка расписания",
        }
        type_text = type_text_by_media.get(media_type, "медиафайл")
        module_text = f"урок/модуль {module_number}" if module_number else "общий материал"
        await message.answer(
            "Шаг 4 из 4: пришли файл в Telegram.\n\n"
            f"- тип: {type_text}\n"
            f"- привязка: {module_text}\n\n"
            f"- дата: {format_lesson_date(lesson_date)}\n\n"
            "Название можно написать в подписи к файлу. Если подписи нет, возьму имя файла.",
            reply_markup=admin_menu_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_media_module)
    async def admin_media_module_invalid_handler(message: Message) -> None:
        await message.answer("Выбери модуль кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_media_module_keyboard())

    @router.message(AdminFlow.waiting_for_media_file)
    async def admin_media_file_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Главное меню":
            await state.clear()
            await message.answer("Загрузка медиа отменена. Вернул в главное меню.", reply_markup=user_main_menu())
            return
        if message.text and message.text.startswith("Админ:"):
            await state.clear()
            await message.answer(
                "Загрузка медиа отменена. Если нужна другая админская команда, нажми её ещё раз.",
                reply_markup=admin_menu_keyboard(),
            )
            return

        payload = extract_media_payload(message)
        if payload is None:
            await message.answer("Пришли видео, аудио, картинку или файл-документ.", reply_markup=admin_menu_keyboard())
            return

        state_data = await state.get_data()
        media_type = state_data.get("media_type")
        module_number = state_data.get("media_module_number")
        module_title = state_data.get("media_module_title")
        lesson_key = state_data.get("media_lesson_key")
        lesson_date_raw = state_data.get("media_lesson_date")
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
        if media_type not in {"video", "podcast", "image", "schedule_image"}:
            await message.answer("Не понял тип медиа. Начни заново через «Админ: загрузить медиа».", reply_markup=admin_menu_keyboard())
            await state.clear()
            return

        if not media_payload_matches_type(payload, media_type):
            expected_by_media = {
                "video": "видео",
                "podcast": "аудиофайл",
                "image": "картинку",
                "schedule_image": "картинку расписания",
            }
            expected = expected_by_media.get(media_type, "медиафайл")
            await message.answer(f"Ожидал {expected}. Пришли правильный файл или начни заново.", reply_markup=admin_menu_keyboard())
            return

        user = await ensure_user(message)
        tags = build_content_tags(
            lesson_key=lesson_key,
            module_number=module_number,
            lesson_date=lesson_date,
            season_title="Сезон 1. Бизнес-консалтинг",
            media_type=media_type,
        )
        async with SessionLocal() as session:
            media = await ProgramMediaRepository.create(
                session=session,
                title=payload["title"],
                media_type=media_type,
                telegram_file_id=payload["telegram_file_id"],
                telegram_file_unique_id=payload["telegram_file_unique_id"],
                telegram_kind=payload["telegram_kind"],
                original_filename=payload["original_filename"],
                file_size=payload["file_size"],
                mime_type=payload["mime_type"],
                module_number=module_number,
                module_title=module_title,
                lesson_key=lesson_key,
                lesson_date=lesson_date,
                tags=tags,
                created_by_user_id=user.id,
            )

        type_text_by_media = {
            "video": "видео",
            "podcast": "подкаст",
            "image": "картинка",
            "schedule_image": "картинка расписания",
        }
        type_text = type_text_by_media.get(media_type, "медиа")
        module_text = f"урок/модуль {module_number}" if module_number else "общий материал"
        await message.answer(
            "Медиафайл сохранён.\n\n"
            f"- id: {media.id}\n"
            f"- тип: {type_text}\n"
            f"- название: {media.title}\n"
            f"- привязка: {module_text}\n"
            f"- дата: {format_lesson_date(lesson_date)}\n"
            f"- теги: {', '.join(tags)}\n\n"
            "Теперь он будет доступен в разделе «Материалы программы».",
            reply_markup=admin_menu_keyboard(),
        )
        await state.clear()

    @router.message(Command("list_materials"))
    @router.message(F.text == "Админ: материалы")
    async def list_materials_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            docs = await DocumentRepository.list_materials(session, limit=100)
            media_items = await ProgramMediaRepository.list_latest(session, limit=30)
            homeworks = await HomeworkRepository.list_active(session, limit=30)
        if not docs and not media_items and not homeworks:
            await message.answer("Материалы и медиа пока не загружены.")
            return

        lines = ["Последние материалы:"]
        if docs:
            for doc in docs[:30]:
                lesson_text = doc.lesson_key or "no-key"
                date_text = format_lesson_date(doc.lesson_date)
                lines.append(
                    f"- doc id={doc.id} | {doc.title} | visibility={doc.visibility.value} | "
                    f"lesson={lesson_text} | date={date_text} | type={doc.material_type or 'none'} | status={doc.status.value}"
                )
        if media_items:
            lines.append("")
            lines.append("Последние медиа:")
            for media in media_items[:20]:
                lesson_text = media.lesson_key or "no-key"
                date_text = format_lesson_date(media.lesson_date)
                lines.append(
                    f"- media id={media.id} | {media.title} | type={media.media_type} | "
                    f"lesson={lesson_text} | date={date_text}"
                )
        if homeworks:
            lines.append("")
            lines.append("Домашние задания:")
            for homework in homeworks[:20]:
                lines.append(
                    f"- homework id={homework.id} | {homework.title} | {homework_lesson_label(homework)} | "
                    f"document_id={homework.document_id or 'none'}"
                )
        await message.answer("\n".join(lines))

    @router.message(Command("reindex"))
    async def reindex_handler(message: Message) -> None:
        if not await require_admin(message):
            return

        await message.answer("Запускаю переиндексацию документов, это может занять время...")
        async with SessionLocal() as session:
            ok, failed = await container.document_service.reindex_all(session)
        await message.answer(f"Переиндексация завершена: успешно={ok}, с ошибками={failed}.")

    @router.message(Command("stats"))
    @router.message(F.text == "Админ: статистика")
    async def stats_handler(message: Message) -> None:
        if not await require_admin(message):
            return

        async with SessionLocal() as session:
            totals = await StatsRepository.dashboard(session)
            feedback_totals = await MessageFeedbackRepository.totals(session)
            feedback_reason_totals = await MessageFeedbackRepository.reason_totals(session)
            latest_errors = await ErrorRepository.latest(session, limit=5)

        data_size_mb = _dir_size_mb(container.settings.data_dir)
        reason_labels = {
            "not_found": "не нашёл ответ",
            "too_general": "слишком общий",
            "misunderstood": "не понял вопрос",
            "other": "другая причина",
        }
        lines = [
            "Админ-сводка:",
            f"- Пользователей: {totals['users']}",
            f"- С проектным контекстом: {totals['users_with_project_context']}",
            f"- Документов всего: {totals['documents']}",
            f"- Домашних заданий: {totals['active_homeworks']}",
            f"- Общих материалов: {totals['global_documents']}",
            f"- Личных файлов: {totals['user_documents']}",
            f"- Пользовательских загрузок: {totals['user_files']}",
            f"- Документов ready/error/processing: {totals['ready_documents']}/{totals['error_documents']}/{totals['processing_documents']}",
            f"- Чанков: {totals['chunks']}",
            f"- Вопросов всего: {totals['messages']}",
            f"- Вопросов за 24ч/7д/30д: {totals['messages_today']}/{totals['messages_week']}/{totals['messages_month']}",
            f"- Размер файлов в data: {data_size_mb:.1f} МБ",
            f"- Ошибок в журнале: {totals['errors']}",
            f"- Ответы полезны: {feedback_totals.get('yes', 0)}",
            f"- Ответы не полезны: {feedback_totals.get('no', 0)}",
        ]
        if feedback_reason_totals:
            lines.append("")
            lines.append("Причины «не полезно»:")
            for reason, count in feedback_reason_totals.items():
                lines.append(f"- {reason_labels.get(reason, reason)}: {count}")
        lines.extend(["", "Последние ошибки:"])
        if latest_errors:
            for error in latest_errors:
                lines.append(f"- [{error.created_at}] {error.context}: {error.error_text[:120]}")
        else:
            lines.append("- Ошибок нет")
        await message.answer("\n".join(lines), reply_markup=admin_menu_keyboard(), parse_mode=None)

    @router.message(F.text == "Админ: расходы")
    async def admin_costs_handler(message: Message) -> None:
        if not await require_admin(message):
            return

        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            usage_today = await StatsRepository.token_usage_since(session, now - timedelta(days=1))
            usage_week = await StatsRepository.token_usage_since(session, now - timedelta(days=7))
            usage_month = await StatsRepository.token_usage_since(session, now - timedelta(days=30))
            embedding_tokens_total = await StatsRepository.estimated_embedding_tokens(session)

        settings = container.settings

        def openai_chat_cost(usage: dict[str, int]) -> float:
            input_cost_usd = usage["prompt_tokens"] / 1_000_000 * settings.openai_chat_input_usd_per_1m
            output_cost_usd = usage["completion_tokens"] / 1_000_000 * settings.openai_chat_output_usd_per_1m
            return (input_cost_usd + output_cost_usd) * settings.usd_rub_rate

        def yandex_chat_cost(usage: dict[str, int]) -> float:
            input_cost_rub = usage["prompt_tokens"] / 1_000 * settings.yandexgpt_input_rub_per_1k
            output_cost_rub = usage["completion_tokens"] / 1_000 * settings.yandexgpt_output_rub_per_1k
            return input_cost_rub + output_cost_rub

        openai_embedding_rub = (
            embedding_tokens_total / 1_000_000 * settings.openai_embedding_usd_per_1m * settings.usd_rub_rate
        )
        yandex_embedding_rub = embedding_tokens_total / 1_000 * settings.yandex_embedding_rub_per_1k

        billing_started_at = _parse_billing_started_at(settings.vm_billing_started_at)
        vm_spent_line = "- VM потрачено с запуска: нет данных"
        if billing_started_at is not None:
            elapsed_hours = max((now - billing_started_at).total_seconds() / 3600, 0)
            vm_spent_line = f"- VM потрачено с {billing_started_at.date()}: {_format_rub(elapsed_hours * settings.vm_rub_per_hour)}"

        lines = [
            "Расходы и оценки:",
            "",
            "Инфраструктура:",
            f"- VM/сервер: {_format_rub(settings.vm_rub_per_hour)} в час",
            f"- VM если 24/7: {_format_rub(settings.vm_rub_per_hour * 24)} в день",
            f"- VM если 24/7: {_format_rub(settings.vm_rub_per_hour * 24 * 30)} в месяц",
            vm_spent_line,
            "",
            "LLM токены, сохранённые в БД:",
            (
                f"- 24ч: запросов={usage_today['requests']}, input={_format_tokens(usage_today['prompt_tokens'])}, "
                f"output={_format_tokens(usage_today['completion_tokens'])}, total={_format_tokens(usage_today['total_tokens'])}"
            ),
            (
                f"- 7д: запросов={usage_week['requests']}, input={_format_tokens(usage_week['prompt_tokens'])}, "
                f"output={_format_tokens(usage_week['completion_tokens'])}, total={_format_tokens(usage_week['total_tokens'])}"
            ),
            (
                f"- 30д: запросов={usage_month['requests']}, input={_format_tokens(usage_month['prompt_tokens'])}, "
                f"output={_format_tokens(usage_month['completion_tokens'])}, total={_format_tokens(usage_month['total_tokens'])}"
            ),
            "",
            "Оценка OpenAI в рублях:",
            f"- 24ч: {_format_rub(openai_chat_cost(usage_today))}",
            f"- 7д: {_format_rub(openai_chat_cost(usage_week))}",
            f"- 30д: {_format_rub(openai_chat_cost(usage_month))}",
            f"- embeddings за все загруженные чанки: ~{_format_tokens(embedding_tokens_total)} токенов, {_format_rub(openai_embedding_rub)}",
            "",
            "Оценка YandexGPT Lite в рублях:",
            f"- 24ч: {_format_rub(yandex_chat_cost(usage_today))}",
            f"- 7д: {_format_rub(yandex_chat_cost(usage_week))}",
            f"- 30д: {_format_rub(yandex_chat_cost(usage_month))}",
            f"- embeddings за все загруженные чанки: ~{_format_tokens(embedding_tokens_total)} токенов, {_format_rub(yandex_embedding_rub)}",
            "",
            "Важно:",
            "- Это оценка по успешным ответам, сохранённым в БД.",
            "- Точный счёт за VM смотри в Yandex Billing.",
            "- Точный счёт OpenAI/YandexGPT смотри в кабинете провайдера.",
        ]
        await message.answer("\n".join(lines), reply_markup=admin_menu_keyboard(), parse_mode=None)

    @router.message(F.text == "Админ: статус")
    async def admin_status_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer("Проверяю БД, LLM и RAG...")
        await message.answer(await build_admin_status_report(), reply_markup=admin_menu_keyboard(), parse_mode=None)

    @router.message(Command("upload_ics"))
    @router.message(F.text == "Админ: загрузить ICS")
    async def admin_upload_ics_prompt_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.set_state(AdminFlow.waiting_for_notification_ics)
        await message.answer(
            "Пришли файл `.ics`, который нужно прикладывать к уведомлениям.\n\n"
            "Это не материал для RAG, бот просто сохранит календарный файл и будет отправлять его вместе с уведомлением.",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_notification_ics, F.document)
    async def admin_upload_ics_file_handler(message: Message, state: FSMContext) -> None:
        user, session = await get_user_and_session(message)
        try:
            if not is_admin(message):
                await message.answer("Эта команда доступна только администратору.")
                await state.clear()
                return

            document = message.document
            filename = Path(document.file_name or "notification.ics").name
            if not filename.lower().endswith(".ics"):
                await message.answer("Нужен именно `.ics` файл.", parse_mode=None)
                return
            if document.file_size and document.file_size > container.settings.max_file_size_bytes:
                await message.answer(
                    f"Файл слишком большой. Максимальный размер: {container.settings.max_file_size_mb} МБ."
                )
                return

            notifications_dir = container.settings.data_dir / "notifications"
            notifications_dir.mkdir(parents=True, exist_ok=True)
            target_path = notifications_dir / filename
            file_info = await message.bot.get_file(document.file_id)
            file_data = await message.bot.download_file(file_info.file_path)
            target_path.write_bytes(file_data.read())

            await AppSettingRepository.upsert(
                session,
                key=NOTIFICATION_ICS_PATH_KEY,
                value=str(target_path),
                updated_by_user_id=user.id,
            )
            await AppSettingRepository.upsert(
                session,
                key=NOTIFICATION_ICS_FILENAME_KEY,
                value=filename,
                updated_by_user_id=user.id,
            )

            await message.answer(
                "ICS-файл сохранён. Теперь он будет прикладываться к уведомлениям.\n\n"
                f"Файл: {filename}",
                reply_markup=admin_menu_keyboard(),
                parse_mode=None,
            )
            await state.clear()
        except Exception as exc:
            logger.exception("notification_ics_upload_failed")
            await ErrorRepository.create(session, context="notification_ics_upload", error_text=str(exc), user_id=user.id)
            await message.answer("Не получилось сохранить ICS-файл. Попробуй ещё раз или пришли другой файл.")
        finally:
            await session.close()

    @router.message(AdminFlow.waiting_for_notification_ics)
    async def admin_upload_ics_invalid_handler(message: Message, state: FSMContext) -> None:
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer("Загрузку ICS отменил.", reply_markup=admin_menu_keyboard())
            return
        await message.answer("Нужен именно файл `.ics`. Можно отменить через /cancel.", parse_mode=None)

    @router.message(F.text == "Админ: тексты")
    async def admin_texts_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            custom_texts = {item.key for item in await BotTextRepository.list_all(session)}

        lines = ["Редактируемые тексты:"]
        for key, label in BOT_TEXT_LABELS.items():
            marker = "изменён" if key in custom_texts else "по умолчанию"
            lines.append(f"- {label}: {marker}")
        lines.append("")
        lines.append("Выбери текст, который нужно заменить. Удаления и опасных действий здесь нет.")
        await message.answer("\n".join(lines), reply_markup=admin_texts_keyboard())

    @router.message(
        F.text.in_(
            [
                "Изменить приветствие",
                "Изменить помощь",
                "Изменить расписание",
                "Изменить текст уведомления",
            ]
        )
    )
    async def admin_edit_text_prompt_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        mapping = {
            "Изменить приветствие": "welcome",
            "Изменить помощь": "help",
            "Изменить расписание": "schedule",
            "Изменить текст уведомления": NOTIFICATION_TEXT_KEY,
        }
        key = mapping[message.text]
        current_value = await get_bot_text(key)
        await state.set_state(AdminFlow.waiting_for_bot_text)
        await state.update_data(bot_text_key=key)
        await message.answer(
            f"Пришли новый текст для блока «{BOT_TEXT_LABELS[key]}» одним сообщением.\n\n"
            f"Текущий текст:\n{current_value[:1800]}",
            reply_markup=admin_texts_keyboard(),
            parse_mode=None,
            link_preview_options=NO_LINK_PREVIEW,
        )

    @router.message(AdminFlow.waiting_for_bot_text, F.text)
    async def admin_text_preview_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text in {"Админ: меню", "Главное меню"}:
            await state.clear()
            reply_markup = admin_menu_keyboard() if message.text == "Админ: меню" else user_main_menu()
            await message.answer("Редактирование текста отменено.", reply_markup=reply_markup)
            return
        data = await state.get_data()
        key = data.get("bot_text_key")
        if key not in BOT_TEXT_DEFAULTS:
            await state.clear()
            await message.answer("Не понял, какой текст нужно изменить. Вернул в админ-меню.", reply_markup=admin_menu_keyboard())
            return
        if len(message.text.strip()) < 5:
            await message.answer("Текст слишком короткий. Пришли нормальный текст или нажми /cancel.")
            return

        pending_text = _message_html_text(message)
        await state.update_data(pending_bot_text=pending_text)
        await state.set_state(AdminFlow.waiting_for_bot_text_confirm)
        await message.answer(
            f"Предпросмотр текста «{BOT_TEXT_LABELS[key]}»:\n\n{pending_text}",
            reply_markup=admin_text_preview_keyboard(),
            link_preview_options=NO_LINK_PREVIEW,
        )

    @router.callback_query(AdminFlow.waiting_for_bot_text_confirm, F.data.in_(["admin_text:save", "admin_text:cancel"]))
    async def admin_text_confirm_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin_user_id(callback.from_user.id):
            await callback.answer("Эта команда доступна только администратору.")
            await state.clear()
            return

        if callback.data == "admin_text:cancel":
            await callback.answer("Отменено.")
            await state.clear()
            if callback.message:
                await callback.message.answer("Редактирование текста отменено.", reply_markup=admin_menu_keyboard())
            return

        data = await state.get_data()
        key = data.get("bot_text_key")
        pending_text = data.get("pending_bot_text")
        if key not in BOT_TEXT_DEFAULTS or not pending_text:
            await callback.answer("Не понял, какой текст сохранить.")
            await state.clear()
            if callback.message:
                await callback.message.answer("Не получилось сохранить текст. Вернул в админ-меню.", reply_markup=admin_menu_keyboard())
            return

        session = SessionLocal()
        try:
            user = await UserRepository.upsert_telegram_user(
                session=session,
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                is_admin=True,
            )
            await BotTextRepository.upsert(session, key=key, value=pending_text, updated_by_user_id=user.id)
        finally:
            await session.close()
        await callback.answer("Сохранено.")
        await state.clear()
        if callback.message:
            await callback.message.answer(
                f"Текст «{BOT_TEXT_LABELS[key]}» обновлён. Он начнёт использоваться сразу.",
                reply_markup=admin_menu_keyboard(),
            )

    @router.message(AdminFlow.waiting_for_bot_text_confirm)
    async def admin_text_confirm_waiting_handler(message: Message) -> None:
        await message.answer("Нажми «Сохранить текст» или «Отменить» под предпросмотром.")

    @router.message(F.text == "Главное меню")
    async def main_menu_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer("Выбери действие:", reply_markup=user_main_menu())

    @router.message(F.text == "Помощь")
    async def help_button_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(await get_bot_text("help"), reply_markup=user_main_menu(), link_preview_options=NO_LINK_PREVIEW)

    @router.message(F.text.in_(["Расписание Лиги Лидеров", "Расписание программы обучения"]))
    async def schedule_handler(message: Message) -> None:
        await ensure_user(message)
        custom_text = await get_bot_text("schedule")
        try:
            await message.answer(
                custom_text,
                reply_markup=user_main_menu(),
                parse_mode="HTML",
                link_preview_options=NO_LINK_PREVIEW,
            )
        except TelegramBadRequest:
            logger.exception("schedule_html_message_failed")
            await message.answer(
                custom_text,
                reply_markup=user_main_menu(),
                parse_mode=None,
                link_preview_options=NO_LINK_PREVIEW,
            )
        await send_schedule_image(message)

    @router.callback_query(F.data.startswith("schedule:season:"))
    async def schedule_season_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        season_key = (callback.data or "").split(":")[-1]
        async with SessionLocal() as session:
            blocks = await ProgramLessonRepository.list_blocks(session, season_key)
        if callback.message:
            await callback.message.answer("Выбери блок программы:", reply_markup=schedule_blocks_keyboard(blocks))

    @router.callback_query(F.data.startswith("schedule:block:"))
    async def schedule_block_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        block_key = (callback.data or "").split(":")[-1]
        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_by_block(session, block_key)
        if not callback.message:
            return
        if not lessons:
            await callback.message.answer("Не нашёл занятия этого блока.", reply_markup=user_main_menu())
            return
        await callback.message.answer(
            f"{lessons[0].block_title}. Выбери занятие:",
            reply_markup=schedule_lessons_keyboard(lessons),
        )

    @router.callback_query(F.data.startswith("schedule:lesson:"))
    async def schedule_lesson_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        lesson_key = (callback.data or "").split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if not callback.message:
            return
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие в расписании.", reply_markup=user_main_menu())
            return
        await callback.message.answer(format_lesson_card(lesson), reply_markup=schedule_lesson_keyboard(lesson), parse_mode=None)

    @router.callback_query(F.data.startswith("schedule:materials:"))
    async def schedule_materials_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        lesson_key = (callback.data or "").split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if callback.message is None:
            return
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие в расписании.", reply_markup=user_main_menu())
            return
        await send_materials_by_lookup(
            callback.message,
            {
                "lesson_key": lesson.lesson_key,
                "lesson_date": lesson.date_start,
                "module_number": lesson.lesson_number,
                "label": lesson.lesson_title,
            },
            telegram_user=callback.from_user,
        )

    @router.message(F.text.in_(["Настройки уведомлений", "Настройка уведомлений"]))
    async def notification_settings_handler(message: Message) -> None:
        user, session = await get_user_and_session(message)
        try:
            setting = await UserNotificationSettingRepository.get_for_user(session, user.id)
            if setting is None or not setting.enabled:
                current_line = "Сейчас уведомления не настроены."
            else:
                current_line = f"Сейчас уведомления будут приходить в {setting.notification_time}."

            await message.answer(
                "Настройка уведомлений.\n\n"
                f"{current_line}\n\n"
                "Выбери удобное время. Настройка времени одна для всех типов уведомлений: "
                "организационные моменты, домашние задания и будущие напоминания по программе.",
                reply_markup=notification_settings_keyboard(),
            )
        finally:
            await session.close()

    @router.message(F.text.startswith("Уведомления: "))
    async def notification_time_handler(message: Message) -> None:
        user, session = await get_user_and_session(message)
        try:
            choice = message.text.replace("Уведомления: ", "", 1).strip()
            if choice == "отключить":
                await UserNotificationSettingRepository.disable(session, user.id)
                await message.answer("Уведомления отключены.", reply_markup=user_main_menu())
                return
            if choice not in NOTIFICATION_TIME_OPTIONS:
                await message.answer("Выбери время кнопкой ниже.", reply_markup=notification_settings_keyboard())
                return

            await UserNotificationSettingRepository.upsert_time(session, user.id, choice)
            await message.answer(
                f"Готово. Уведомления будут приходить в {choice} по московскому времени.\n\n"
                "Пока текст тестовый, позже здесь будут разные уведомления по направлениям программы.",
                reply_markup=user_main_menu(),
            )
        finally:
            await session.close()

    @router.message(F.text.in_(["Задать вопрос", "Задать вопрос по организации Лиги Лидеров", "Задать вопрос по обучению"]))
    async def ask_training_question_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer("Выбери раздел по своему вопросу:", reply_markup=question_section_keyboard())

    @router.message(F.text == "Материалы программы")
    async def materials_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer("Выбери раздел материалов программы:", reply_markup=materials_program_keyboard())

    @router.callback_query(F.data == "materials:records")
    async def materials_records_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_records_and_materials(callback.message, telegram_user=callback.from_user)

    @router.callback_query(F.data == "materials:docs")
    async def materials_docs_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_materials_list(callback.message, telegram_user=callback.from_user)

    @router.callback_query(F.data == "materials:podcasts")
    async def materials_podcasts_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message:
            return
        await show_media_picker(
            callback.message,
            media_type="podcast",
            title="Выбери подкаст:",
            empty_text="Аудиоподкасты пока не загружены. Могу сделать текстовую подкаст-выжимку по материалам.",
            empty_reply_markup=podcast_empty_keyboard(),
        )

    @router.callback_query(F.data == "materials:podcast_text")
    async def materials_podcast_text_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_podcast_text_summary(callback.message, state, telegram_user=callback.from_user)

    @router.callback_query(F.data == "materials:summary")
    async def materials_summary_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message:
            return
        await answer_question(
            callback.message,
            "Сделай краткое саммари занятий сезона 1 по загруженным материалам. "
            "Выдели основные темы, инструменты и важные выводы для участника.",
            state,
            mode="materials_summary",
            telegram_user=callback.from_user,
        )
        await state.clear()

    @router.callback_query(F.data.startswith("media:"))
    async def media_send_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return

        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.message.answer("Не понял, какой файл нужно отправить.", reply_markup=user_main_menu())
            return
        _, media_type, media_id_raw = parts
        try:
            media_id = int(media_id_raw)
        except ValueError:
            await callback.message.answer("Не понял номер файла.", reply_markup=user_main_menu())
            return

        async with SessionLocal() as session:
            media = await ProgramMediaRepository.get_by_id(session, media_id)

        if media is None or media.media_type != media_type:
            await callback.message.answer(
                "Этот файл не найден. Попробуй открыть раздел материалов ещё раз.",
                reply_markup=user_main_menu(),
            )
            return

        await send_media_asset(callback.message, media)
        await callback.message.answer("Если хочешь продолжить, выбери действие:", reply_markup=user_main_menu())

    @router.message(F.text == "Сезон 1. Бизнес-консалтинг")
    async def materials_season_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(MATERIALS_TYPE_PROMPT, reply_markup=materials_menu_keyboard())

    @router.message(F.text == "Записи и материалы занятий")
    async def materials_records_handler(message: Message) -> None:
        await ensure_user(message)
        await send_records_and_materials(message)

    @router.message(F.text == "Видео занятий")
    async def materials_video_handler(message: Message) -> None:
        await ensure_user(message)
        if not container.settings.video_library_enabled:
            await message.answer(VIDEO_LIBRARY_DISABLED_TEXT, reply_markup=materials_menu_keyboard(), parse_mode=None)
            return

        video_url = (container.settings.video_library_url or "").strip()
        if not video_url:
            await message.answer(
                "Видео-раздел скоро появится. Пока ссылка на записи не добавлена.",
                reply_markup=materials_menu_keyboard(),
            )
            return

        await message.answer(
            f"{container.settings.video_library_title}\n\n{container.settings.video_access_note}",
            reply_markup=video_library_keyboard(video_url),
            parse_mode=None,
        )
        await message.answer("После просмотра можно вернуться в главное меню.", reply_markup=user_main_menu())

    @router.message(F.text == "Подкасты на основе занятий")
    async def materials_podcasts_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await show_media_picker(
            message,
            media_type="podcast",
            title="Выбери подкаст:",
            empty_text=PODCASTS_PROMPT,
            empty_reply_markup=podcast_empty_keyboard(),
        )

    @router.message(F.text == "Саммари занятий")
    async def materials_summary_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await answer_question(
            message,
            "Сделай краткое саммари занятий сезона 1 по загруженным материалам. "
            "Выдели основные темы, инструменты и важные выводы для участника.",
            state,
            mode="materials_summary",
        )
        await state.clear()

    @router.message(F.text == "Домашние задания")
    async def homework_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(HOMEWORK_MENU_PROMPT, reply_markup=homework_program_keyboard())

    @router.message(F.text == "Список заданий")
    async def homework_list_handler(message: Message) -> None:
        await ensure_user(message)
        await send_homework_list(message)

    @router.message(F.text == "Помощь с домашкой")
    async def homework_help_prompt_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await start_homework_help(message, state)

    @router.message(F.text.in_(["Уточнить контекст моего проекта", "Контекст моего проекта", "Мой проект"]))
    async def project_handler(message: Message, state: FSMContext) -> None:
        user, session = await get_user_and_session(message)
        try:
            if not user.project_context:
                await state.clear()
                await message.answer(
                    PROJECT_CONTEXT_UPLOAD_PROMPT,
                    reply_markup=project_context_keyboard(),
                )
                return

            await state.clear()
            await message.answer(
                "Контекст проекта уже сохранён.\n\n"
                f"{_shorten_project_context(user.project_context)}\n\n"
                "Можно обновить его текстом или загрузить файл с дополнительным контекстом.",
                reply_markup=project_context_keyboard(),
            )
        finally:
            await session.close()

    @router.message(F.text.in_(["Добавить контекст текстом", "Добавить / обновить контекст проекта", "Обновить описание проекта"]))
    async def project_update_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.set_state(UserFlow.waiting_for_project_context)
        await message.answer(PROJECT_PROMPT, reply_markup=project_context_keyboard())

    @router.message(F.text == "Что бот знает о моём проекте?")
    async def project_context_preview_handler(message: Message) -> None:
        user, session = await get_user_and_session(message)
        try:
            if not user.project_context:
                await message.answer(
                    "Пока контекст проекта не сохранён. Нажми «Добавить контекст текстом» или «Загрузить файл с контекстом».",
                    reply_markup=project_context_keyboard(),
                )
                return
            await message.answer(
                "Сейчас я учитываю такой контекст проекта:\n\n"
                f"{_shorten_project_context(user.project_context, limit=1800)}",
                reply_markup=project_context_keyboard(),
            )
        finally:
            await session.close()

    @router.message(F.text.in_(["Загрузить файл с контекстом", "Загрузить файл"]))
    async def upload_file_prompt_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.set_state(UserFlow.waiting_for_user_file)
        await message.answer(FILE_UPLOAD_PROMPT, reply_markup=project_context_keyboard())

    @router.message(F.text == "Нужна помощь с проектом")
    async def project_help_prompt_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer(PROJECT_HELP_MENU_PROMPT, reply_markup=project_help_keyboard())

    @router.message(F.text.in_(["Как решить конфликтную ситуацию", "Сложный заказчик", "Трудности с учётом финансов"]))
    async def project_help_template_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer(PROJECT_HELP_PLACEHOLDER_TEXT, reply_markup=user_main_menu())

    @router.message(UserFlow.waiting_for_training_question, F.text)
    async def training_question_input_handler(message: Message, state: FSMContext) -> None:
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            await state.clear()
            return
        material_lookup = extract_material_lookup(message.text)
        if material_lookup is not None:
            await send_materials_by_lookup(message, material_lookup)
            await state.clear()
            return
        extra_context = await build_schedule_context_for_llm() if looks_like_schedule_question(message.text) else None
        await answer_question(message, message.text, state, mode="training_qa", extra_context=extra_context)
        await state.clear()

    @router.message(UserFlow.waiting_for_categorized_question, F.text)
    async def categorized_question_input_handler(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        section = data.get("question_section")
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            await state.clear()
            return
        material_lookup = extract_material_lookup(message.text)
        if material_lookup is not None:
            await send_materials_by_lookup(message, material_lookup)
            await state.clear()
            return

        if section != "technical" and looks_like_technical_question(message.text):
            section = "technical"

        mode, extra_context, force_rag = question_section_context(section)
        if section != "technical" and looks_like_schedule_question(message.text):
            schedule_context = await build_schedule_context_for_llm()
            extra_context = f"{extra_context or ''}\n\n{schedule_context}".strip()
        await answer_question(
            message,
            message.text,
            state,
            mode=mode,
            force_rag=force_rag,
            extra_context=extra_context,
        )
        await state.clear()

    @router.message(UserFlow.waiting_for_project_help_question, F.text)
    async def project_help_question_input_handler(message: Message, state: FSMContext) -> None:
        await answer_question(message, message.text, state, mode="project_help")
        await state.clear()

    @router.message(UserFlow.waiting_for_homework_help_question, F.text)
    async def homework_help_question_input_handler(message: Message, state: FSMContext) -> None:
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            await state.clear()
            return
        material_lookup = extract_material_lookup(message.text)
        if material_lookup is not None:
            await send_materials_by_lookup(message, material_lookup)
            await state.clear()
            return
        if looks_like_technical_question(message.text):
            mode, extra_context, force_rag = question_section_context("technical")
            await answer_question(
                message,
                message.text,
                state,
                mode=mode,
                force_rag=force_rag,
                extra_context=extra_context,
            )
            await state.clear()
            return

        data = await state.get_data()
        selected_homework_id = data.get("selected_homework_id")
        async with SessionLocal() as session:
            if selected_homework_id:
                homework = await HomeworkRepository.get_by_id(session, int(selected_homework_id))
                homeworks = [homework] if homework and homework.status == "active" else []
            else:
                homeworks = await HomeworkRepository.list_active(session, limit=10)

        if homeworks:
            homework_blocks = []
            for homework in homeworks:
                block_lines = [
                    f"id={homework.id}",
                    f"название: {homework.title}",
                    f"привязка: {homework_lesson_label(homework)}",
                ]
                if homework.description:
                    block_lines.append(f"описание: {homework.description}")
                if homework.moodle_url:
                    block_lines.append(f"ссылка для сдачи: {homework.moodle_url}")
                if homework.document_id:
                    block_lines.append(f"связанный материал/document_id: {homework.document_id}")
                homework_blocks.append("\n".join(block_lines))
            homework_context = "\n\n".join(homework_blocks)
            first_homework = homeworks[0]
            if selected_homework_id:
                rag_lesson_key = first_homework.lesson_key
                rag_lesson_date = first_homework.lesson_date
                rag_document_ids = [first_homework.document_id] if first_homework.document_id else None
            else:
                rag_lesson_key = None
                rag_lesson_date = None
                rag_document_ids = [homework.document_id for homework in homeworks if homework.document_id]
                if not rag_document_ids:
                    rag_document_ids = None
        else:
            await message.answer(
                "Домашние задания пока не добавлены.\n\n"
                "Входная диагностика и тестирования после кикофа не считаются домашним заданием, "
                "если организаторы отдельно не обозначили это как ДЗ.\n\n"
                "Если сомневаешься, лучше уточнить вопрос в общем чате программы или у организаторов.",
                reply_markup=homework_program_keyboard(),
            )
            await state.clear()
            return

        extra_context = (
            "Раздел: помощь с домашним заданием.\n"
            "Используй список домашних заданий ниже как основной контекст. "
            "Не считай входную диагностику, тестирование, анкету, кикоф или обычное мероприятие домашним заданием, "
            "если они явно не добавлены в таблицу домашних заданий ниже. "
            "Если выбрано конкретное ДЗ, используй только материалы того же урока, модуля, даты или связанный файл. "
            "Если точного ответа нет в описании ДЗ или загруженных материалах, скажи об этом "
            "и предложи уточнить вопрос у организаторов.\n\n"
            f"Домашние задания из базы:\n{homework_context}"
        )
        await answer_question(
            message,
            message.text,
            state,
            mode="homework_help",
            force_rag=bool(rag_lesson_key or rag_lesson_date or rag_document_ids),
            extra_context=extra_context,
            lesson_key=rag_lesson_key,
            lesson_date=rag_lesson_date,
            document_ids=rag_document_ids,
        )
        await state.clear()

    @router.message(UserFlow.waiting_for_file_question, F.text)
    async def file_question_input_handler(message: Message, state: FSMContext) -> None:
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            await state.clear()
            return
        await answer_question(message, message.text, state, mode="user_file_qa")
        await state.clear()

    @router.message(UserFlow.waiting_for_followup, F.text)
    async def followup_input_handler(message: Message, state: FSMContext) -> None:
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            await state.clear()
            return
        material_lookup = extract_material_lookup(message.text)
        if material_lookup is not None:
            await send_materials_by_lookup(message, material_lookup)
            await state.clear()
            return
        await answer_question(message, message.text, state, mode="followup")
        await state.clear()

    @router.message(UserFlow.waiting_for_project_context, F.text)
    async def project_context_input_handler(message: Message, state: FSMContext) -> None:
        user, session = await get_user_and_session(message)
        try:
            await UserRepository.update_project_context(session, user.id, message.text)
            await message.answer(
                "Контекст проекта сохранён. Теперь я буду учитывать его в ответах по проекту и рабочим ситуациям.",
                reply_markup=project_context_keyboard(),
            )
            await state.clear()
        except Exception as exc:
            await ErrorRepository.create(session, context="save_project_context", error_text=str(exc), user_id=user.id)
            await message.answer("Не удалось сохранить описание проекта. Попробуй ещё раз.")
        finally:
            await session.close()

    @router.message(AdminFlow.waiting_for_global_file, F.document)
    async def admin_global_file_upload_handler(message: Message, state: FSMContext) -> None:
        user, session = await get_user_and_session(message)
        processing_message: Message | None = None
        try:
            if message.from_user.id not in container.settings.admin_ids:
                await message.answer("Эта команда доступна только администратору.")
                await state.clear()
                return

            document = message.document
            extension = container.document_service.validate_file(document.file_name, document.file_size)
            processing_message = await message.answer(random.choice(FILE_PROCESSING_MESSAGES))
            state_data = await state.get_data()
            caption_metadata = parse_caption_metadata(message.caption)

            module_number = state_data.get("material_module_number") or caption_metadata.get("module_number")
            season_title = state_data.get("material_season_title")
            module_title = state_data.get("material_module_title") or caption_metadata.get("module_title")
            lesson_key = state_data.get("material_lesson_key")
            lesson_date_raw = state_data.get("material_lesson_date")
            lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
            if lesson_key is None:
                lesson_key = f"lesson_{module_number}" if module_number else "general"
            if module_title is None and season_title and module_number:
                module_title = f"{season_title}, урок/модуль {module_number}"
            elif module_title is None and season_title:
                module_title = f"{season_title}, общий материал"
            elif module_title is None:
                module_title = "Общий материал программы" if lesson_key == "general" else None

            material_type_from_state = state_data.get("material_type") if "material_type" in state_data else None
            material_type = material_type_from_state or caption_metadata.get("material_type")
            if material_type is None and "material_type" not in state_data and "домаш" in (document.file_name or "").lower():
                material_type = "homework"
            moodle_url = state_data.get("homework_moodle_url")
            tags = build_content_tags(
                lesson_key=lesson_key,
                module_number=module_number,
                lesson_date=lesson_date,
                season_title=season_title,
                material_type=material_type,
            )

            saved = await container.document_service.save_telegram_file(
                bot=message.bot,
                telegram_file_id=document.file_id,
                filename=document.file_name,
                owner_telegram_id=message.from_user.id,
                mode="global",
            )

            indexed_document = await container.document_service.create_and_index_document(
                session=session,
                title=document.file_name.rsplit(".", 1)[0],
                saved_upload=saved,
                visibility="global",
                owner_user_id=user.id,
                telegram_file_id=document.file_id,
                module_number=module_number,
                module_title=module_title,
                lesson_key=lesson_key,
                lesson_date=lesson_date,
                material_type=material_type,
                tags=tags,
            )
            homework = None
            if material_type == "homework":
                homework = await HomeworkRepository.create(
                    session=session,
                    title=document.file_name.rsplit(".", 1)[0],
                    description=(message.caption or "").strip() or None,
                    document_id=indexed_document.id,
                    moodle_url=moodle_url,
                    module_number=module_number,
                    module_title=module_title,
                    lesson_key=lesson_key,
                    lesson_date=lesson_date,
                    created_by_user_id=user.id,
                )
            module_text = f"урок/модуль {module_number}" if module_number else "общий материал"
            type_text = material_type or "другое"
            homework_line = ""
            link_line = ""
            if homework is not None:
                homework_line = f"- домашнее задание id: {homework.id}\n"
                link_line = f"- ссылка: {moodle_url or 'без ссылки'}\n"
            await message.answer(
                "Материал загружен и обработан.\n\n"
                f"- id: {indexed_document.id}\n"
                f"{homework_line}"
                f"- файл: {document.file_name}\n"
                f"- формат: {extension}\n"
                f"- привязка: {module_text}\n"
                f"- дата: {format_lesson_date(lesson_date)}\n"
                f"- тип: {type_text}\n"
                f"{link_line}"
                f"- теги: {', '.join(tags)}\n"
                "- видимость: общий материал программы\n\n"
                f"Чтобы спросить именно по этому файлу, напиши: материал {indexed_document.id}: твой вопрос",
                reply_markup=admin_menu_keyboard(),
            )
            await state.clear()
        except FileValidationError as exc:
            await message.answer(str(exc))
        except Exception as exc:
            logger.exception("global_upload_failed")
            await ErrorRepository.create(session, context="global_upload", error_text=str(exc), user_id=user.id)
            await message.answer("Не получилось обработать файл. Попробуй другой файл или обратись к администратору.")
        finally:
            await _delete_message_safely(processing_message)
            await session.close()

    @router.message(UserFlow.waiting_for_user_file, F.document)
    async def user_file_upload_handler(message: Message, state: FSMContext) -> None:
        user, session = await get_user_and_session(message)
        processing_message: Message | None = None
        try:
            document = message.document
            container.document_service.validate_file(document.file_name, document.file_size)
            processing_message = await message.answer(random.choice(FILE_PROCESSING_MESSAGES))
            saved = await container.document_service.save_telegram_file(
                bot=message.bot,
                telegram_file_id=document.file_id,
                filename=document.file_name,
                owner_telegram_id=message.from_user.id,
                mode="user",
            )
            indexed_document = await container.document_service.create_and_index_document(
                session=session,
                title=document.file_name.rsplit(".", 1)[0],
                saved_upload=saved,
                visibility="user",
                owner_user_id=user.id,
                telegram_file_id=document.file_id,
            )
            await message.answer(
                "Спасибо! Теперь я знаком с этим контекстом и материалами.",
                reply_markup=user_main_menu(),
            )
            await state.clear()
        except FileValidationError as exc:
            await message.answer(str(exc))
        except Exception as exc:
            logger.exception("user_upload_failed")
            await ErrorRepository.create(session, context="user_upload", error_text=str(exc), user_id=user.id)
            await message.answer("Не получилось обработать файл. Попробуй другой файл или напиши организаторам.")
        finally:
            await _delete_message_safely(processing_message)
            await session.close()

    @router.message(AdminFlow.waiting_for_global_file)
    @router.message(UserFlow.waiting_for_user_file)
    async def waiting_file_but_not_document_handler(message: Message) -> None:
        await message.answer("Нужен именно файл. Пришли PDF, DOCX, PPTX или TXT.")

    @router.message(F.text)
    async def fallback_text_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            return
        material_lookup = extract_material_lookup(message.text)
        if material_lookup is not None:
            await send_materials_by_lookup(message, material_lookup)
            return
        if looks_like_technical_question(message.text):
            mode, extra_context, force_rag = question_section_context("technical")
            await answer_question(
                message,
                message.text,
                state,
                mode=mode,
                force_rag=force_rag,
                extra_context=extra_context,
            )
            return
        # Вертикальный срез: любой текстовый вопрос -> LLM -> ответ -> лог в БД.
        await answer_question(message, message.text, state, mode="free_text")

    return router
