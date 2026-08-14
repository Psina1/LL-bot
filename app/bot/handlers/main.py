from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import csv
from io import BytesIO, StringIO
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

import aiofiles
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramEntityTooLarge, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import text

from app.bot.keyboards.reply import (
    admin_calendar_keyboard,
    admin_material_module_keyboard,
    admin_material_season_keyboard,
    admin_material_type_keyboard,
    admin_materials_keyboard,
    admin_materials_service_keyboard,
    admin_message_preview_keyboard,
    admin_homework_deadline_keyboard,
    admin_homework_link_keyboard,
    admin_lesson_date_keyboard,
    admin_media_module_keyboard,
    admin_media_type_keyboard,
    admin_menu_keyboard,
    admin_notification_control_keyboard,
    admin_notifications_keyboard,
    admin_overview_keyboard,
    admin_status_keyboard,
    admin_tech_files_keyboard,
    admin_text_preview_keyboard,
    admin_texts_keyboard,
    all_reply_button_labels,
    bot_feedback_score_keyboard,
    document_list_keyboard,
    director_dashboard_keyboard,
    feedback_reason_keyboard,
    homework_detail_keyboard,
    homework_list_keyboard,
    homework_program_keyboard,
    main_menu_keyboard,
    materials_blocks_keyboard,
    materials_lesson_card_keyboard,
    materials_lessons_keyboard,
    materials_program_keyboard,
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
    summary_list_keyboard,
    video_library_keyboard,
    video_watch_keyboard,
)
from app.bot.states.forms import AdminFlow, UserFlow
from app.bot.texts import (
    ADMIN_PROMPT,
    BOT_TEXT_DEFAULTS,
    BOT_TEXT_LABELS,
    FILE_UPLOAD_PROMPT,
    HOMEWORK_HELP_PROMPT,
    HOMEWORK_MENU_PROMPT,
    PODCASTS_PROMPT,
    PROJECT_CONTEXT_UPLOAD_PROMPT,
    PROJECT_HELP_MENU_PROMPT,
    PROJECT_HELP_PLACEHOLDER_TEXT,
    PROJECT_PROMPT,
    VIDEO_LIBRARY_DISABLED_TEXT,
)
from app.db.repositories import (
    AllowedUserRepository,
    AppSettingRepository,
    BotFeedbackRepository,
    BotTextRepository,
    ChunkRepository,
    DirectorAssignmentRepository,
    DocumentRepository,
    ErrorRepository,
    MessageFeedbackRepository,
    MessageRepository,
    HomeworkRepository,
    ProgramLessonRepository,
    ProgramMediaRepository,
    UserNotificationSettingRepository,
    StatsRepository,
    UserEventRepository,
    UserRepository,
)
from app.db.session import SessionLocal
from app.notifications.constants import (
    NOTIFICATION_ACTIVE_KEY,
    NOTIFICATION_EXPIRES_AT_KEY,
    NOTIFICATION_ICS_FILENAME_KEY,
    NOTIFICATION_ICS_PATH_KEY,
    NOTIFICATION_TEXT_KEY,
    NOTIFICATION_TIME_OPTIONS,
)
from app.services.container import AppContainer
from app.services.director_dashboard import is_director_dashboard_demo_user
from app.services.document_service import FileValidationError, SavedUpload
from app.services.question_routing import route_direct_question
from app.services.video_links import build_director_dashboard_url, build_video_watch_url

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
TELEGRAM_BOT_UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024
USER_ANALYTICS_BUTTONS = [
    "Задать вопрос",
    "Вопрос по программе",
    "Технический вопрос",
    "Другое",
    "Материалы программы",
    "Материалы: записи и материалы",
    "Материалы: текстовые материалы",
    "Материалы: видео занятия",
    "Материалы: подкасты",
    "Материалы: саммари",
    "Домашние задания",
    "Домашние задания: список",
    "Домашние задания: помощь",
    "Расписание Лиги Лидеров",
    "Расписание: сезон",
    "Расписание: блок",
    "Расписание: занятие",
    "Расписание: материалы занятия",
    "Настройки уведомлений",
    "Старт: выбор времени уведомлений",
    "Уведомления: 09:00",
    "Уведомления: 12:00",
    "Уведомления: 15:00",
    "Уведомления: отключить",
    "Главное меню",
]


def _format_admin_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M")


def _setting_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


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

    def user_main_menu(show_director_dashboard: bool = False):
        return main_menu_keyboard(
            show_project_context=container.settings.show_project_context_menu,
            show_director_dashboard=show_director_dashboard,
        )

    async def has_director_dashboard_access(telegram_id: int | None) -> bool:
        if telegram_id is None:
            return False
        if telegram_id in container.settings.admin_ids:
            return True
        if is_director_dashboard_demo_user(telegram_id):
            return True
        try:
            async with SessionLocal() as session:
                return await DirectorAssignmentRepository.has_active_team(session, telegram_id)
        except Exception:
            logger.exception("director_menu_access_check_failed telegram_id=%s", telegram_id)
            return False

    async def user_main_menu_for_actor(actor) -> ReplyKeyboardMarkup:
        telegram_id = getattr(actor, "id", None)
        return user_main_menu(show_director_dashboard=await has_director_dashboard_access(telegram_id))

    async def user_main_menu_for_message(message: Message, telegram_user=None) -> ReplyKeyboardMarkup:
        return await user_main_menu_for_actor(telegram_user or message.from_user)

    async def user_main_menu_for_callback(callback: CallbackQuery) -> ReplyKeyboardMarkup:
        return await user_main_menu_for_actor(callback.from_user)

    def materials_menu_keyboard():
        return materials_program_keyboard()

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

    async def start_bot_feedback_flow(message: Message, state: FSMContext, source: str = "deep_link") -> None:
        user = await ensure_user(message)
        async with SessionLocal() as session:
            response = await BotFeedbackRepository.create(
                session=session,
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                full_name=user.full_name,
                source=source,
            )
        await state.set_state(UserFlow.waiting_for_bot_feedback_score)
        await state.update_data(bot_feedback_response_id=response.id)
        await message.answer(
            "Спасибо, что готов оставить обратную связь о боте.\n\n"
            "Опрос короткий: оценка и три открытых вопроса. "
            "На открытые вопросы можно ответить текстом или голосом.\n\n"
            "Насколько бот сейчас полезен тебе в программе?",
            reply_markup=bot_feedback_score_keyboard(response.id),
            parse_mode=None,
        )

    async def transcribe_bot_feedback_voice(message: Message) -> str | None:
        voice = message.voice
        if voice is None:
            return None
        if voice.duration > container.settings.max_voice_duration_seconds:
            await message.answer(
                f"Голосовое слишком длинное. Максимум "
                f"{container.settings.max_voice_duration_seconds // 60} минуты."
            )
            return None
        if voice.file_size and voice.file_size > container.settings.max_voice_size_bytes:
            await message.answer(f"Голосовое слишком большое. Максимум {container.settings.max_voice_size_mb} МБ.")
            return None
        if not container.transcription_service.enabled:
            await message.answer("Голосовые ответы пока не подключены. Напиши, пожалуйста, текстом.")
            return None

        processing_message = await message.answer("Расшифровываю голосовое сообщение...")
        try:
            buffer = BytesIO()
            await message.bot.download(voice.file_id, destination=buffer)
            transcription = await container.transcription_service.transcribe(
                buffer.getvalue(),
                filename="bot_feedback_voice.ogg",
                mime_type=voice.mime_type or "audio/ogg",
            )
            text = transcription.text.strip()
            if text:
                await message.answer(f"Распознал ответ:\n{text}", parse_mode=None)
            return text
        except Exception as exc:
            logger.exception("bot_feedback_voice_transcription_failed")
            user = await ensure_user(message)
            async with SessionLocal() as session:
                await ErrorRepository.create(
                    session,
                    context="bot_feedback_voice_transcription",
                    error_text=str(exc),
                    user_id=user.id,
                )
            await message.answer("Не получилось расшифровать голосовое. Попробуй ещё раз или напиши текстом.")
            return None
        finally:
            await _delete_message_safely(processing_message)

    async def bot_feedback_message_text(message: Message) -> str | None:
        if message.text:
            text = message.text.strip()
            if text == "Главное меню":
                return None
            return text
        if message.voice:
            return await transcribe_bot_feedback_voice(message)
        await message.answer("Ответ можно отправить текстом или голосовым сообщением.")
        return None

    def question_section_context(section: str | None) -> tuple[str, str | None, bool]:
        if section == "technical":
            return (
                "technical_question",
                "Раздел вопроса: технический вопрос. "
                "Если вопрос про работу бота, записи занятий, доступы, технические ошибки или платформу обучения «ПРОГРЕСС», "
                "не придумывай самостоятельные инструкции: используй сохранённые контакты технической поддержки. "
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

    def should_send_schedule_image_for_question(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        if not text:
            return False
        if any(marker in text for marker in ["распис", "программа обучения", "календар"]):
            return True
        time_markers = ["когда", "какого числа", "дата", "дату", "следующ", "ближайш", "сегодня", "завтра"]
        lesson_markers = ["заняти", "урок", "встреч", "модул", "блок"]
        if any(marker in text for marker in time_markers) and any(marker in text for marker in lesson_markers):
            return True
        if "спикер" in text and any(marker in text for marker in lesson_markers):
            return True
        return False

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
            original_filename = getattr(message.video, "file_name", None)
            mime_type = message.video.mime_type
            title_hint = original_filename or "Видео занятия"
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

    def default_media_extension(media_type: str, telegram_kind: str, mime_type: str | None = None) -> str:
        mime = (mime_type or "").lower()
        if mime == "video/quicktime":
            return ".mov"
        if mime in {"video/mp4", "application/mp4"}:
            return ".mp4"
        if mime == "audio/mpeg":
            return ".mp3"
        if mime in {"audio/mp4", "audio/x-m4a"}:
            return ".m4a"
        if mime in {"audio/ogg", "application/ogg"} or telegram_kind == "voice":
            return ".ogg"
        if mime == "image/png":
            return ".png"
        if mime == "image/webp":
            return ".webp"
        if mime.startswith("image/"):
            return ".jpg"
        if media_type == "video":
            return ".mp4"
        if media_type == "podcast":
            return ".mp3"
        if media_type in {"image", "schedule_image"}:
            return ".jpg"
        return ".bin"

    def safe_media_filename(payload: dict[str, Any], media_type: str) -> str:
        original_filename = (payload.get("original_filename") or "").strip()
        if original_filename:
            candidate = Path(original_filename).name
        else:
            extension = default_media_extension(media_type, payload.get("telegram_kind") or "", payload.get("mime_type"))
            candidate = f"{payload.get('title') or 'media'}{extension}"

        candidate = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", candidate).strip(" ._")
        if not candidate:
            candidate = f"media{default_media_extension(media_type, payload.get('telegram_kind') or '', payload.get('mime_type'))}"
        if "." not in candidate:
            candidate = f"{candidate}{default_media_extension(media_type, payload.get('telegram_kind') or '', payload.get('mime_type'))}"
        suffix = Path(candidate).suffix
        if len(candidate) <= 180:
            return candidate
        if suffix:
            stem = Path(candidate).stem[: 180 - len(suffix)]
            return f"{stem}{suffix}"
        return candidate[:180]

    async def save_media_file_to_storage(message: Message, payload: dict[str, Any], media_type: str) -> str | None:
        directory_by_type = {
            "video": "videos",
            "podcast": "podcasts",
            "image": "images",
            "schedule_image": "schedule",
        }
        media_dir = container.settings.data_dir / "media" / directory_by_type.get(media_type, "other")
        media_dir.mkdir(parents=True, exist_ok=True)

        filename = safe_media_filename(payload, media_type)
        unique_part = (payload.get("telegram_file_unique_id") or datetime.now().strftime("%Y%m%d%H%M%S"))[:16]
        target_path = media_dir / f"{unique_part}_{filename}"

        file_data = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                file_info = await message.bot.get_file(payload["telegram_file_id"])
                file_data = await message.bot.download_file(file_info.file_path)
                break
            except TelegramNetworkError as exc:
                last_error = exc
                await asyncio.sleep(1 + attempt)
            except TelegramBadRequest as exc:
                last_error = exc
                break

        if file_data is None:
            logger.warning("media_file_download_failed media_type=%s error=%s", media_type, last_error)
            return None

        try:
            async with aiofiles.open(target_path, "wb") as out:
                await out.write(file_data.read())
        except OSError as exc:
            logger.warning("media_file_save_failed path=%s error=%s", target_path, exc)
            return None
        return str(target_path)

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

    def parse_notification_expiry(text_value: str | None) -> datetime | None:
        text = (text_value or "").strip()
        if not text:
            return None
        normalized = text.replace("T", " ")

        iso_match = re.search(
            r"\b(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})\b",
            normalized,
        )
        if iso_match:
            return datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
                int(iso_match.group(4)),
                int(iso_match.group(5)),
            )

        numeric_match = re.search(
            r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s+(\d{1,2}):(\d{2})\b",
            normalized,
        )
        if numeric_match:
            day = int(numeric_match.group(1))
            month = int(numeric_match.group(2))
            year_raw = numeric_match.group(3)
            year = datetime.now().year if year_raw is None else int(year_raw)
            if year < 100:
                year += 2000
            return datetime(year, month, day, int(numeric_match.group(4)), int(numeric_match.group(5)))

        return None

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
        module_title = (getattr(homework, "module_title", None) or "").strip()
        if module_title:
            if ":" in module_title:
                block_title, lesson_title = (part.strip() for part in module_title.split(":", 1))
                lesson_title = re.sub(
                    r"^занятие\s+(\d+)\s*[.:]\s*",
                    r"занятие \1: ",
                    lesson_title,
                    flags=re.IGNORECASE,
                ).strip()
                if block_title and lesson_title:
                    return f"Блок «{block_title}», {lesson_title}"
            return f"Блок «{module_title}»"

        ordinal_by_number = {
            1: "первого",
            2: "второго",
            3: "третьего",
            4: "четвёртого",
            5: "пятого",
            6: "шестого",
            7: "седьмого",
            8: "восьмого",
            9: "девятого",
            10: "десятого",
        }
        if homework.module_number:
            ordinal = ordinal_by_number.get(homework.module_number)
            if ordinal:
                return f"ДЗ после {ordinal} занятия"
            return f"ДЗ после занятия {homework.module_number}"
        if homework.lesson_date:
            return f"ДЗ после занятия {format_lesson_date(homework.lesson_date)}"
        return "ДЗ"

    def homework_deadline_label(homework) -> str:
        return format_lesson_date(homework.deadline_date) if getattr(homework, "deadline_date", None) else "не указан"

    def homework_is_expired(homework, today: date | None = None) -> bool:
        deadline = getattr(homework, "deadline_date", None)
        return bool(deadline and deadline < (today or date.today()))

    def current_homeworks(homeworks: list[Any], today: date | None = None) -> list[Any]:
        return [homework for homework in homeworks if not homework_is_expired(homework, today)]

    def archived_homeworks(homeworks: list[Any], today: date | None = None) -> list[Any]:
        return [homework for homework in homeworks if homework_is_expired(homework, today)]

    def homework_description_for_user(description: str | None) -> str:
        if not description:
            return ""

        hidden_prefixes = ("открыто с", "срок сдачи", "ссылка для сдачи")
        cleaned_lines = []
        previous_blank = False
        for raw_line in description.splitlines():
            line = raw_line.rstrip()
            normalized = line.strip().lower()
            if normalized.startswith(hidden_prefixes) and ":" in normalized:
                continue
            if not normalized:
                if not previous_blank:
                    cleaned_lines.append("")
                previous_blank = True
                continue
            cleaned_lines.append(line)
            previous_blank = False
        return "\n".join(cleaned_lines).strip()

    def strip_lesson_topic_for_homework(module_title: str | None) -> str:
        title = (module_title or "").strip()
        if not title:
            return ""
        if ":" in title:
            tail = title.rsplit(":", 1)[-1].strip()
            if tail:
                title = tail
        title = re.sub(r"^занятие\s+\d+\s*[.:]\s*", "", title, flags=re.IGNORECASE).strip()
        return title

    def default_homework_title(module_number: int | None, module_title: str | None, lesson_date: date | None) -> str:
        topic = strip_lesson_topic_for_homework(module_title)
        if module_number and topic:
            return f"Домашнее задание {module_number}. {topic}"
        if module_number:
            return f"Домашнее задание {module_number}"
        if topic:
            return f"Домашнее задание. {topic}"
        if lesson_date:
            return f"Домашнее задание от {format_lesson_date(lesson_date)}"
        return "Домашнее задание"

    def split_homework_title_and_description(
        raw_text: str | None,
        *,
        module_number: int | None,
        module_title: str | None,
        lesson_date: date | None,
        fallback_title: str | None = None,
    ) -> tuple[str, str | None]:
        text = (raw_text or "").strip()
        default_title = default_homework_title(module_number, module_title, lesson_date)
        if not text:
            return (fallback_title or default_title), None

        lines = [line.rstrip() for line in text.splitlines()]
        first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
        if first_index is None:
            return (fallback_title or default_title), None

        first_line = lines[first_index].strip()
        rest_lines = lines[first_index + 1 :]
        while rest_lines and not rest_lines[0].strip():
            rest_lines.pop(0)

        generic_homework_title = bool(
            re.fullmatch(r"домашнее\s+задание\s*(?:№|#)?\s*\d*\.?", first_line.lower())
        )
        title = default_title if generic_homework_title else first_line
        if len(title) > 140:
            title = fallback_title or default_title
            description = text
        else:
            description = "\n".join(rest_lines).strip() or None
        return title, description

    def text_material_filename(material_type: str, lesson_key: str | None) -> str:
        safe_key = re.sub(r"[^a-zA-Z0-9_-]+", "_", lesson_key or "general").strip("_") or "general"
        safe_type = re.sub(r"[^a-zA-Z0-9_-]+", "_", material_type or "material").strip("_") or "material"
        return f"{safe_type}_{safe_key}_{int(time.time())}.txt"

    async def save_text_material_as_upload(text: str, lesson_key: str | None, material_type: str) -> SavedUpload:
        container.settings.materials_dir.mkdir(parents=True, exist_ok=True)
        filename = text_material_filename(material_type, lesson_key)
        target_path = container.settings.materials_dir / filename
        async with aiofiles.open(target_path, "w", encoding="utf-8") as out:
            await out.write(text.strip() + "\n")
        return SavedUpload(path=target_path, original_filename=filename, extension="txt")

    async def save_homework_text_as_upload(text: str, lesson_key: str | None) -> SavedUpload:
        return await save_text_material_as_upload(text, lesson_key, "homework")

    def default_summary_title(module_number: int | None, module_title: str | None, lesson_date: date | None) -> str:
        topic = strip_lesson_topic_for_homework(module_title)
        if topic:
            return f"Саммари. {topic}"
        if module_number:
            return f"Саммари занятия {module_number}"
        if lesson_date:
            return f"Саммари от {format_lesson_date(lesson_date)}"
        return "Саммари"

    def split_summary_title_and_text(
        raw_text: str | None,
        *,
        module_number: int | None,
        module_title: str | None,
        lesson_date: date | None,
    ) -> tuple[str, str]:
        text = (raw_text or "").strip()
        default_title = default_summary_title(module_number, module_title, lesson_date)
        if not text:
            return default_title, ""

        lines = [line.rstrip() for line in text.splitlines()]
        first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
        if first_index is None:
            return default_title, ""

        first_line = lines[first_index].strip()
        generic_summary_title = bool(re.fullmatch(r"(саммари|summary)\s*(?:занятия)?\s*(?:№|#)?\s*\d*\.?", first_line.lower()))
        if generic_summary_title or len(first_line) > 140:
            return default_title, text
        return first_line, text

    def resolve_stored_file_path(stored_path: str | None) -> Path | None:
        if not stored_path:
            return None
        path = Path(stored_path)
        if path.is_absolute():
            return path
        return Path.cwd() / path

    def document_caption(document) -> str:
        lines = [document.title]
        if getattr(document, "lesson_date", None):
            lines.append(f"Дата: {format_lesson_date(document.lesson_date)}")
        if getattr(document, "original_filename", None):
            lines.append(f"Файл: {document.original_filename}")
        caption = "\n".join(lines)
        return caption if len(caption) <= 1000 else f"{caption[:997]}..."

    async def send_document_original(message: Message, document) -> None:
        file_path = resolve_stored_file_path(document.stored_path)
        if file_path is None or not file_path.exists() or not file_path.is_file():
            logger.warning("document_file_missing document_id=%s path=%s", document.id, document.stored_path)
            await message.answer(
                f"Не получилось найти оригинал файла «{document.title}». "
                "Напиши организаторам, они проверят материал."
            )
            return

        try:
            await message.answer_document(
                document=FSInputFile(file_path, filename=document.original_filename),
                caption=document_caption(document),
                parse_mode=None,
            )
        except TelegramBadRequest:
            logger.exception("send_document_original_failed document_id=%s", document.id)
            await message.answer(
                f"Не получилось отправить файл «{document.title}». "
                "Возможно, файл слишком большой или был перемещён на сервере."
            )

    def split_telegram_text(text_value: str, limit: int = 3800) -> list[str]:
        text_value = text_value.strip()
        if len(text_value) <= limit:
            return [text_value]

        parts: list[str] = []
        current = ""
        for paragraph in text_value.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                parts.append(current)
                current = ""
            while len(paragraph) > limit:
                cut_at = paragraph.rfind("\n", 0, limit)
                if cut_at < limit // 2:
                    cut_at = paragraph.rfind(" ", 0, limit)
                if cut_at < limit // 2:
                    cut_at = limit
                parts.append(paragraph[:cut_at].strip())
                paragraph = paragraph[cut_at:].strip()
            current = paragraph
        if current:
            parts.append(current)
        return parts

    def read_text_file(path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return path.read_text(encoding=encoding).strip()
            except UnicodeDecodeError:
                continue
        return path.read_text(errors="ignore").strip()

    async def summary_text_for_document(document) -> str:
        file_path = resolve_stored_file_path(document.stored_path)
        if file_path and file_path.exists() and file_path.is_file() and file_path.suffix.lower() == ".txt":
            text_value = read_text_file(file_path)
            if text_value:
                return text_value

        async with SessionLocal() as session:
            chunk_texts = await ChunkRepository.list_texts_by_document(session, document.id)
        return "\n\n".join(text.strip() for text in chunk_texts if text and text.strip()).strip()

    async def send_summary_document_text(message: Message, document) -> None:
        text_value = await summary_text_for_document(document)
        if not text_value:
            await message.answer(
                f"Саммари «{document.title}» есть в базе, но текст не получилось прочитать. "
                "Напиши организаторам, они проверят материал.",
                reply_markup=materials_program_keyboard(),
            )
            return

        full_text = f"Саммари: {document.title}\n\n{text_value}"
        parts = split_telegram_text(full_text)
        for index, part in enumerate(parts, start=1):
            suffix = f"\n\nПродолжение {index}/{len(parts)}" if len(parts) > 1 and index < len(parts) else ""
            await message.answer(f"{part}{suffix}", parse_mode=None)

    async def send_summary_documents(message: Message, summaries: list[Any], empty_text: str | None = None) -> None:
        if not summaries:
            await message.answer(
                empty_text
                or "Саммари занятий пока не добавлены.\n\nКогда организаторы добавят саммари, они появятся здесь.",
                reply_markup=materials_program_keyboard(),
            )
            return
        if len(summaries) == 1:
            await send_summary_document_text(message, summaries[0])
            return

        lines = ["Выбери саммари, которое открыть в чате:", ""]
        for document in summaries[:20]:
            date_suffix = f" ({format_lesson_date(document.lesson_date)})" if document.lesson_date else ""
            lines.append(f"- {document.title}{date_suffix}")
        await message.answer(
            "\n".join(lines),
            reply_markup=summary_list_keyboard(summaries),
            parse_mode=None,
        )

    USER_HIDDEN_MATERIAL_TYPES = {"transcript"}
    NON_MATERIAL_CARD_TYPES = {"summary", "homework", "transcript"}

    def user_visible_documents(docs: list[Any]) -> list[Any]:
        return [
            doc
            for doc in docs
            if (doc.material_type or "") not in USER_HIDDEN_MATERIAL_TYPES
        ]

    def material_docs_for_lesson(docs: list[Any]) -> list[Any]:
        return [
            doc
            for doc in docs
            if (doc.material_type or "") not in NON_MATERIAL_CARD_TYPES
        ]

    def summary_docs_for_lesson(docs: list[Any]) -> list[Any]:
        return [doc for doc in docs if doc.material_type == "summary"]

    async def get_lesson_content(lesson, user_id: int) -> tuple[list[Any], list[Any], list[Any]]:
        async with SessionLocal() as session:
            docs = await DocumentRepository.list_visible_by_lesson(
                session=session,
                user_id=user_id,
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                limit=50,
            )
            media_items = await ProgramMediaRepository.list_by_lesson(
                session=session,
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                limit=20,
            )
            homeworks = await HomeworkRepository.list_by_lesson(
                session=session,
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                limit=20,
            )
        return docs, media_items, homeworks

    def build_video_watch_url_for_media(media) -> str | None:
        base_url = (container.settings.video_base_url or "").strip()
        if not base_url:
            return None
        local_path = resolve_stored_file_path(getattr(media, "stored_path", None))
        if not local_path or not local_path.exists() or not local_path.is_file():
            return None
        return build_video_watch_url(
            base_url=base_url,
            media_id=media.id,
            secret=container.settings.video_link_secret,
            ttl_hours=container.settings.video_link_ttl_hours,
        )

    async def send_materials_lesson_card(message: Message, lesson, telegram_user=None) -> None:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        await session.close()

        docs, media_items, homeworks = await get_lesson_content(lesson, user.id)
        material_docs = material_docs_for_lesson(docs)
        summary_docs = summary_docs_for_lesson(docs)
        actual_homeworks = current_homeworks(homeworks)
        videos = [media for media in media_items if media.media_type == "video"]
        podcasts = [media for media in media_items if media.media_type == "podcast"]
        single_video_url = build_video_watch_url_for_media(videos[0]) if len(videos) == 1 else None

        lines = [
            lesson.lesson_title,
            f"Дата: {schedule_lesson_date_text(lesson)}",
        ]
        if lesson.speaker:
            lines.append(f"Спикер: {lesson.speaker}")
        lines.extend(
            [
                "",
                "Что доступно:",
                f"- материалы и презентации: {len(material_docs)}",
                f"- саммари: {len(summary_docs)}",
                f"- подкасты: {len(podcasts)}",
                f"- видео: {len(videos)}",
                f"- домашнее задание: {'есть' if actual_homeworks else 'нет'}",
                "",
                "Выбери, что открыть:",
            ]
        )
        await message.answer(
            "\n".join(lines),
            reply_markup=materials_lesson_card_keyboard(
                lesson,
                has_docs=bool(material_docs),
                has_summary=bool(summary_docs),
                has_podcasts=bool(podcasts),
                has_video=bool(videos),
                has_homework=bool(actual_homeworks),
                single_video_url=single_video_url,
            ),
            parse_mode=None,
        )

    async def send_lesson_documents_by_type(message: Message, lesson, doc_type: str, telegram_user=None) -> None:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            docs = await DocumentRepository.list_visible_by_lesson(
                session=session,
                user_id=user.id,
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                limit=50,
            )
        finally:
            await session.close()

        if doc_type == "summary":
            selected_docs = summary_docs_for_lesson(docs)
            title = f"Саммари: {lesson.lesson_title}"
            empty_text = "Саммари по этому занятию пока не добавлено."
        else:
            selected_docs = material_docs_for_lesson(docs)
            title = f"Материалы: {lesson.lesson_title}"
            empty_text = "Материалы по этому занятию пока не добавлены."

        if not selected_docs:
            await message.answer(empty_text, reply_markup=materials_program_keyboard())
            return

        if doc_type == "summary":
            for document in selected_docs[:5]:
                await send_summary_document_text(message, document)
            return

        lines = [title, ""]
        for doc in selected_docs[:20]:
            lines.append(f"- {doc.title}")
        lines.extend(["", "Нажми на материал ниже, чтобы скачать оригинал."])
        await message.answer("\n".join(lines), reply_markup=document_list_keyboard(selected_docs), parse_mode=None)

    async def send_lesson_media_by_type(message: Message, lesson, media_type: str) -> None:
        async with SessionLocal() as session:
            media_items = await ProgramMediaRepository.list_by_lesson(
                session=session,
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                limit=20,
            )
        selected_items = [media for media in media_items if media.media_type == media_type]
        if not selected_items:
            label = "Подкасты" if media_type == "podcast" else "Видео"
            await message.answer(f"{label} по этому занятию пока не добавлены.", reply_markup=materials_program_keyboard())
            return
        if media_type == "video" and len(selected_items) == 1:
            await send_media_asset(message, selected_items[0])
            return
        title = "Выбери подкаст:" if media_type == "podcast" else "Выбери видео:"
        await message.answer(title, reply_markup=media_list_keyboard(selected_items, media_type=media_type))

    async def send_materials_block_picker(message: Message) -> None:
        async with SessionLocal() as session:
            blocks = await ProgramLessonRepository.list_blocks(session, "s1")
        if not blocks:
            await message.answer("Пока не нашёл блоки программы.", reply_markup=materials_program_keyboard())
            return
        await message.answer("Выбери блок программы:", reply_markup=materials_blocks_keyboard(blocks))

    def has_material_delivery_intent(text: str) -> bool:
        delivery_markers = [
            "дай",
            "дайте",
            "пришли",
            "пришлите",
            "скинь",
            "скиньте",
            "отправь",
            "отправьте",
            "покажи",
            "показать",
            "открой",
            "открыть",
            "скачай",
            "скачать",
            "получить",
            "хочу посмотреть",
            "посмотреть",
            "хочу послушать",
            "послушать",
            "где найти",
            "где посмотреть",
            "ссылка",
            "ссылку",
        ]
        return any(marker in text for marker in delivery_markers)

    def has_answer_question_intent(text: str) -> bool:
        question_markers = [
            "что было",
            "что написано",
            "что значит",
            "что такое",
            "как ",
            "как?",
            "можно ли",
            "почему",
            "зачем",
            "объясни",
            "объясните",
            "расскажи",
            "расскажите",
            "поясни",
            "поясните",
            "о чем",
            "про что",
        ]
        return text.endswith("?") or any(marker in text for marker in question_markers)

    def has_homework_lookup_intent(text: str) -> bool:
        lookup_markers = [
            "какое дз",
            "какая домаш",
            "какое домаш",
            "что задали",
            "что задано",
            "задали",
            "где сдать",
            "куда сдать",
            "как сдать",
            "сдать",
            "сдавать",
            "сдачи",
            "дедлайн",
            "deadline",
            "срок",
            "ссылка",
            "ссылку",
            "покажи",
            "дай",
            "пришли",
            "скинь",
            "отправь",
        ]
        return any(marker in text for marker in lookup_markers)

    def has_material_lookup_intent(text: str) -> bool:
        lookup_markers = [
            "где леж",
            "где найти",
            "где посмотреть",
            "где скачать",
            "ссылка",
            "ссылку",
            "открой",
            "открыть",
            "дай",
            "дайте",
            "пришли",
            "пришлите",
            "скинь",
            "скиньте",
            "отправь",
            "отправьте",
            "покажи",
            "показать",
            "скачай",
            "скачать",
            "получить",
            "хочу посмотреть",
            "посмотреть",
            "хочу послушать",
            "послушать",
        ]
        return any(marker in text for marker in lookup_markers)

    def wants_lesson_card_lookup(text: str, content_type: str) -> bool:
        if content_type != "materials":
            return False
        if any(marker in text for marker in ["все по", "всё по", "все материалы", "всё материалы", "что доступно"]):
            return True
        if "материал" in text and not any(marker in text for marker in ["презентац", "файл", "документ", "pdf", "ppt", "pptx"]):
            return True
        return False

    DIRECT_LESSON_MARKERS = [
        ("s1_b1_kickoff", ["кикоф", "kick-off", "kickoff"]),
        ("s1_b2_l1", ["time to cash", "тайм ту кэш", "логика консалтингового бизнеса", "экспертизу в выручку", "cash"]),
        ("s1_b2_l2", ["организационные модели", "организационн", "зрелый консалтинговый бизнес", "берштейн"]),
        ("s1_b2_l3", ["практикум"]),
        ("s1_b2_l4", ["итоговая сборка блока", "итоговая сборка"]),
        ("s1_b3_l1", ["стратегия как инструмент"]),
        ("s1_b3_l2", ["сценарное планирование", "сценарн", "ярослав павлов", "павлов"]),
        ("s1_b3_l3", ["разработка стратегии", "компании дар", "дар", "елена лашманова", "лашманова"]),
        ("s1_b3_l4", ["управленческий совет", "защита стратегических проектов", "стратегические проекты"]),
        ("s1_b4_l1", ["экономика и финансы", "введение", "карлик", "м.а. карлик", "дз и кз", "дебитор", "кредитор"]),
        ("s1_b4_l2", ["как заработать прибыль", "прибыль", "золотая формула бизнеса", "сафронов", "учетная политика", "учётная политика", "факторный анализ"]),
        ("s1_b4_l3", ["отчеты и показатели", "отчёты и показатели", "эиф", "p&l", "pl", "cf", "макарова", "kpi"]),
        ("s1_b4_l4", ["групповая работа по итогам блока", "итоги блока эиф", "итогам блока эиф", "онлайн работа", "обратная связь по финансам"]),
        ("s1_b5_final", ["очная сессия", "подведение итогов", "спб"]),
    ]

    def direct_lesson_key_from_text(text: str) -> str | None:
        for candidate_key, markers in DIRECT_LESSON_MARKERS:
            if any(marker in text for marker in markers):
                return candidate_key
        return None

    def extract_material_lookup(text_value: str | None) -> dict[str, Any] | None:
        text = (text_value or "").strip().lower()
        if not text:
            return None

        wants_summary = any(marker in text for marker in ["саммари", "конспект", "выжимк"])
        wants_podcast = "подкаст" in text
        wants_video = any(marker in text for marker in ["видео", "запис"])
        wants_homework = any(marker in text for marker in ["дз", "домаш", "задани"])
        wants_docs = any(marker in text for marker in ["материал", "презентац", "презу", "слайды", "файл", "документ", "pdf", "ppt", "pptx"])
        has_material_intent = wants_summary or wants_podcast or wants_video or wants_homework or wants_docs
        if not has_material_intent:
            return None
        delivery_intent = has_material_delivery_intent(text) or has_material_lookup_intent(text)
        homework_lookup_intent = wants_homework and has_homework_lookup_intent(text)
        if has_answer_question_intent(text) and not delivery_intent and not homework_lookup_intent:
            return None

        if wants_summary:
            content_type = "summary"
        elif wants_podcast:
            content_type = "podcast"
        elif wants_video:
            content_type = "video"
        elif wants_homework:
            content_type = "homework"
        else:
            content_type = "materials"
        if wants_lesson_card_lookup(text, content_type):
            content_type = "lesson_card"

        lesson_date = None
        try:
            lesson_date = parse_lesson_date_input(text)
        except ValueError:
            lesson_date = None

        lesson_key = None
        module_number = None
        wants_latest_with_content = bool(
            any(marker in text for marker in ["последн", "предыдущ", "прошл"])
            and any(marker in text for marker in ["заняти", "урок", "встреч"])
        )
        lesson_key = direct_lesson_key_from_text(text)

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
        else:
            ordinal_markers = [
                (1, ["перв", "1-й", "1ый"]),
                (2, ["втор", "2-й", "2ой"]),
                (3, ["трет", "треть", "3-й", "3ий"]),
                (4, ["четвер", "4-й", "4ый"]),
                (5, ["пят", "5-й", "5ый"]),
            ]
            if any(marker in text for marker in ["урок", "модул", "заняти", "встреч"]):
                for number, markers in ordinal_markers:
                    if any(marker in text for marker in markers):
                        module_number = number
                        break

        if module_number and lesson_key is None:
            if block_key:
                lesson_key = f"{block_key}_l{module_number}"
            else:
                return {
                    "lesson_key": None,
                    "lesson_date": lesson_date,
                    "module_number": module_number,
                    "content_type": content_type,
                    "latest_with_content": wants_latest_with_content,
                    "ambiguous_module_number": True,
                }

        if (
            not lesson_key
            and lesson_date is None
            and not wants_latest_with_content
            and not block_key
            and content_type not in {"summary", "podcast", "video", "homework"}
        ):
            return None

        return {
            "lesson_key": lesson_key,
            "lesson_date": lesson_date,
            "module_number": module_number,
            "block_key": block_key,
            "content_type": content_type,
            "latest_with_content": wants_latest_with_content,
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

    async def send_reminder_to_group(
        message: Message,
        text_value: str,
        user_id: int | None = None,
        parse_mode: str | None = None,
    ) -> None:
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
                parse_mode=parse_mode,
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
        await message.answer(
            f"Напоминание отправлено в чат{title_part}.",
            reply_markup=admin_notifications_keyboard(),
        )

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
        show_followup_menu: bool = True,
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
            if show_followup_menu:
                await message.answer(
                    "Если хочешь продолжить, выбери действие:",
                    reply_markup=await user_main_menu_for_message(message, telegram_user=telegram_user),
                )
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

    async def answer_direct_question_if_supported(
        message: Message,
        question: str,
        state: FSMContext,
        telegram_user=None,
    ) -> bool:
        route = route_direct_question(question)
        if route is None:
            return False

        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            rate_count = await MessageRepository.count_last_minute(session, user.id)
            if rate_count >= container.settings.max_user_questions_per_minute:
                await message.answer("Слишком много запросов за минуту. Попробуй чуть позже.")
                return True

            result = await container.chat_service.answer_direct(
                session=session,
                user=user,
                question=question,
                answer=route.answer,
                mode=route.mode,
            )
            await message.answer(result.text, parse_mode=None)
            await message.answer(
                "Если хочешь продолжить, выбери действие:",
                reply_markup=await user_main_menu_for_message(message, telegram_user=telegram_user),
            )
            await state.update_data(last_question=question, last_answer=result.text)
            return True
        finally:
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
            await message.answer(
                "Если хочешь продолжить, выбери действие:",
                reply_markup=await user_main_menu_for_message(message),
            )
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

    async def send_materials_list(
        message: Message,
        telegram_user=None,
        material_type: str | None = None,
        title: str = "Материалы программы",
        empty_text: str | None = None,
    ) -> None:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            if material_type:
                docs = await DocumentRepository.list_visible_by_material_type(
                    session=session,
                    user_id=user.id,
                    material_type=material_type,
                    limit=50,
                )
            else:
                docs = await DocumentRepository.list_visible_materials(session, user.id, limit=50)
        finally:
            await session.close()

        docs = user_visible_documents(docs)

        if not docs:
            await message.answer(
                empty_text
                or "Материалы программы пока не загружены.\n\n"
                "Когда организаторы добавят материалы занятий, они появятся здесь.",
                reply_markup=await user_main_menu_for_message(message, telegram_user=telegram_user),
            )
            return

        lines = [
            f"{title}:",
            "",
        ]
        for doc in docs[:20]:
            lesson_hint = f" ({format_lesson_date(doc.lesson_date)})" if doc.lesson_date else ""
            lines.append(f"- {doc.title}{lesson_hint}")
        lines.extend(
            [
                "",
                "Нажми на материал ниже, чтобы скачать оригинал.",
                "Если хочешь уточнить что-то по материалам, напиши вопрос обычным сообщением.",
            ]
        )
        await message.answer("\n".join(lines), reply_markup=document_list_keyboard(docs))

    async def send_materials_by_lookup(message: Message, lookup: dict[str, Any], telegram_user=None) -> bool:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            lookup = dict(lookup)
            if lookup.get("ambiguous_module_number"):
                module_number = lookup.get("module_number")
                await message.answer(
                    "Нужно уточнить блок программы, потому что занятия нумеруются внутри каждого блока.\n\n"
                    f"Напиши, например: «материалы по стратегии, занятие {module_number}» "
                    f"или «видео по бизнес-консалтингу, занятие {module_number}».",
                    reply_markup=materials_program_keyboard(),
                    parse_mode=None,
                )
                return True

            if lookup.get("latest_with_content"):
                lesson = await ProgramLessonRepository.latest_started_with_content(session, date.today())
                if lesson is None:
                    await message.answer(
                        "Пока не нашёл прошедших занятий с загруженными материалами.",
                        reply_markup=materials_program_keyboard(),
                    )
                    return True
                lookup.update(
                    {
                        "lesson_key": lesson.lesson_key,
                        "lesson_date": lesson.date_start,
                        "module_number": lesson.lesson_number,
                        "label": lesson.lesson_title,
                    }
                )

            content_type = lookup.get("content_type") or "materials"
            has_lesson_scope = bool(lookup.get("lesson_key") or lookup.get("lesson_date"))

            if not has_lesson_scope and lookup.get("block_key"):
                lessons = await ProgramLessonRepository.list_by_block(session, lookup["block_key"])
                if not lessons:
                    await message.answer(
                        "Не нашёл занятия этого блока.",
                        reply_markup=materials_program_keyboard(),
                    )
                    return True
                await message.answer(
                    f"{lessons[0].block_title}. Выбери занятие:",
                    reply_markup=materials_lessons_keyboard(lessons),
                    parse_mode=None,
                )
                return True

            if content_type == "lesson_card" and has_lesson_scope:
                lesson = None
                if lookup.get("lesson_key"):
                    lesson = await ProgramLessonRepository.get_by_key(session, lookup["lesson_key"])
                elif lookup.get("lesson_date"):
                    lesson = await ProgramLessonRepository.get_by_date(session, lookup["lesson_date"])
                if lesson is None:
                    await message.answer(
                        "Не нашёл это занятие в расписании. Попробуй указать дату или название занятия.",
                        reply_markup=materials_program_keyboard(),
                    )
                    return True
                await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
                return True

            if has_lesson_scope:
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
            else:
                docs = []
                media_items = []
                homeworks = []
                if content_type == "summary":
                    docs = await DocumentRepository.list_visible_by_material_type(
                        session=session,
                        user_id=user.id,
                        material_type="summary",
                        limit=20,
                    )
                elif content_type in {"podcast", "video"}:
                    media_items = await ProgramMediaRepository.list_by_type(session, media_type=content_type, limit=20)
                elif content_type == "homework":
                    homeworks = await HomeworkRepository.list_active(session, limit=20)
        finally:
            await session.close()

        lookup_parts = []
        if lookup.get("label"):
            lookup_parts.append(str(lookup["label"]))
        if lookup.get("module_number"):
            lookup_parts.append(f"урок/модуль {lookup['module_number']}")
        if lookup.get("lesson_date"):
            lookup_parts.append(f"дата {format_lesson_date(lookup['lesson_date'])}")
        lookup_text = ", ".join(lookup_parts) or "указанный раздел"

        if content_type == "summary":
            summaries = summary_docs_for_lesson(docs) if has_lesson_scope else docs
            await send_summary_documents(
                message,
                summaries[:20],
                empty_text=f"Саммари по запросу «{lookup_text}» пока не добавлено.",
            )
            return True

        if content_type in {"podcast", "video"}:
            selected_media = [media for media in media_items if media.media_type == content_type]
            if not selected_media:
                label = "Подкасты" if content_type == "podcast" else "Видео"
                await message.answer(f"{label} по запросу «{lookup_text}» пока не добавлены.", reply_markup=materials_program_keyboard())
                return True
            title = "Выбери подкаст:" if content_type == "podcast" else "Выбери видео:"
            await message.answer(title, reply_markup=media_list_keyboard(selected_media, media_type=content_type))
            return True

        if content_type == "homework":
            archived_count = len(archived_homeworks(homeworks))
            homeworks = current_homeworks(homeworks)
            if not homeworks:
                archive_hint = " Старые задания можно посмотреть через «Домашние задания» -> «Архив ДЗ»." if archived_count else ""
                await message.answer(
                    f"Актуальные домашние задания по запросу «{lookup_text}» пока не добавлены.{archive_hint}",
                    reply_markup=homework_program_keyboard(),
                )
                return True
            lines = [f"Нашёл домашние задания: {lookup_text}.", ""]
            for homework in homeworks[:20]:
                deadline_text = f"; срок сдачи: {homework_deadline_label(homework)}" if homework.deadline_date else ""
                lines.append(f"- {homework.title} ({homework_lesson_label(homework)}{deadline_text})")
            lines.extend(["", "Выбери нужное задание кнопкой ниже."])
            await message.answer(
                "\n".join(lines),
                reply_markup=homework_list_keyboard(homeworks, include_archive=bool(archived_count)),
                parse_mode=None,
            )
            return True

        docs = material_docs_for_lesson(docs)
        if not docs and not media_items and not homeworks:
            await message.answer(
                f"Материалы по запросу «{lookup_text}» пока не добавлены.",
                reply_markup=await user_main_menu_for_message(message, telegram_user=telegram_user),
            )
            return True

        if docs:
            lines = [
                f"Нашёл материалы и презентации: {lookup_text}.",
                "",
            ]
            for doc in docs[:20]:
                date_hint = format_lesson_date(doc.lesson_date)
                date_suffix = f" ({date_hint})" if date_hint != "без даты" else ""
                lines.append(f"- {doc.title}{date_suffix}")
            lines.extend(
                [
                    "",
                    "Нажми на материал ниже, чтобы скачать оригинал.",
                    "Если хочешь уточнить что-то по этим материалам, напиши вопрос обычным сообщением.",
                ]
            )
            await message.answer("\n".join(lines), reply_markup=document_list_keyboard(docs))

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
                await message.answer(
                    "После просмотра можно вернуться в главное меню.",
                    reply_markup=await user_main_menu_for_message(message, telegram_user=telegram_user),
                )
        return True

    def extract_speaker_marker(text_value: str | None) -> str | None:
        text = (text_value or "").lower()
        speaker_markers = [
            "рахманов",
            "берштейн",
            "павлов",
            "лашманова",
            "семенов",
            "семёнов",
            "сытин",
            "сафронов",
            "макарова",
            "карлик",
        ]
        for marker in speaker_markers:
            if marker in text:
                return marker.replace("ё", "е")
        return None

    def has_lesson_context_words(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        return any(marker in text for marker in ["занят", "урок", "встреч", "материал", "дз", "домаш", "задан", "саммари", "подкаст", "видео", "запис"])

    def relative_lesson_lookup(text_value: str | None) -> tuple[str, int] | None:
        text = (text_value or "").lower()
        if not any(marker in text for marker in ["занят", "урок", "встреч"]):
            return None
        if any(marker in text for marker in ["предпослед"]):
            return ("past", 1)
        if any(marker in text for marker in ["последн", "прошл"]):
            return ("past", 0)
        if any(marker in text for marker in ["следующ", "ближайш"]):
            return ("future", 0)
        return None

    def wants_lesson_overview(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        return any(marker in text for marker in ["что было", "расскажи", "расскажите", "о чем", "про что", "что обсуждали", "что проходили"])

    def wants_lesson_card_request(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        return any(marker in text for marker in ["карточк", "что доступно", "все по", "всё по", "все материалы", "всё материалы"])

    def wants_lesson_date(text_value: str | None) -> bool:
        text = (text_value or "").lower()
        return any(marker in text for marker in ["когда", "какого числа", "дата", "дату"])

    async def select_relative_lesson(direction: str, offset: int):
        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_active(session)
        today = date.today()
        if direction == "future":
            candidates = [
                lesson for lesson in lessons if lesson.date_start and lesson.date_start >= today
            ]
            candidates.sort(key=lambda lesson: (lesson.date_start, lesson.sort_order))
        else:
            candidates = [
                lesson for lesson in lessons if lesson.date_start and lesson.date_start <= today
            ]
            candidates.sort(key=lambda lesson: (lesson.date_start, lesson.sort_order), reverse=True)
        if offset >= len(candidates):
            return None
        return candidates[offset]

    async def send_lesson_overview(
        message: Message,
        lesson,
        state: FSMContext | None = None,
        question_text: str | None = None,
        telegram_user=None,
    ) -> None:
        user, session = await get_user_and_session(message, telegram_user=telegram_user)
        try:
            docs = await DocumentRepository.list_visible_by_lesson(
                session=session,
                user_id=user.id,
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                limit=50,
            )
        finally:
            await session.close()
        summaries = summary_docs_for_lesson(docs)
        if summaries:
            await send_summary_documents(message, summaries[:5])
            await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
            return
        if state is not None and question_text:
            await answer_question(
                message,
                question_text,
                state,
                mode="lesson_overview",
                lesson_key=lesson.lesson_key,
                lesson_date=lesson.date_start,
                telegram_user=telegram_user,
                show_followup_menu=False,
            )
            await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
            return
        await message.answer(
            "Саммари по этому занятию пока не добавлено. Показываю карточку занятия с доступными материалами.",
            parse_mode=None,
        )
        await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)

    async def answer_structured_lesson_question_if_supported(
        message: Message,
        text_value: str | None,
        state: FSMContext,
        telegram_user=None,
    ) -> bool:
        text = (text_value or "").lower()
        relative_lookup = relative_lesson_lookup(text)
        if relative_lookup is not None:
            direction, offset = relative_lookup
            lesson = await select_relative_lesson(direction, offset)
            if lesson is None:
                await message.answer(
                    "Не нашёл подходящее занятие в расписании.",
                    reply_markup=await user_main_menu_for_message(message, telegram_user=telegram_user),
                )
                return True
            if has_homework_lookup_intent(text) or "дз" in text or "домаш" in text:
                await send_materials_by_lookup(
                    message,
                    {
                        "lesson_key": lesson.lesson_key,
                        "lesson_date": lesson.date_start,
                        "module_number": lesson.lesson_number,
                        "content_type": "homework",
                        "label": lesson.lesson_title,
                    },
                    telegram_user=telegram_user,
                )
                return True
            if wants_lesson_date(text):
                await message.answer(format_lesson_card(lesson), reply_markup=schedule_lesson_keyboard(lesson), parse_mode=None)
                if should_send_schedule_image_for_question(text):
                    await send_schedule_image(message)
                return True
            if wants_lesson_card_request(text):
                await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
                return True
            if wants_lesson_overview(text):
                await send_lesson_overview(
                    message,
                    lesson,
                    state=state,
                    question_text=text_value,
                    telegram_user=telegram_user,
                )
                return True
            await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
            return True

        direct_lesson_key = direct_lesson_key_from_text(text)
        if direct_lesson_key and has_lesson_context_words(text) and wants_lesson_overview(text):
            async with SessionLocal() as session:
                lesson = await ProgramLessonRepository.get_by_key(session, direct_lesson_key)
            if lesson is not None:
                await send_lesson_overview(
                    message,
                    lesson,
                    state=state,
                    question_text=text_value,
                    telegram_user=telegram_user,
                )
                return True

        speaker_marker = extract_speaker_marker(text)
        if speaker_marker and has_lesson_context_words(text):
            async with SessionLocal() as session:
                lessons = await ProgramLessonRepository.list_active(session)
            lessons = [
                lesson
                for lesson in lessons
                if speaker_marker in (lesson.speaker or "").lower().replace("ё", "е")
            ]
            if not lessons:
                return False
            if len(lessons) > 1:
                lines = [
                    f"Нашёл несколько занятий со спикером «{speaker_marker}».",
                    "Выбери, какое занятие имеешь в виду:",
                    "",
                ]
                for lesson in lessons:
                    lines.append(f"- {lesson.lesson_title} ({schedule_lesson_date_text(lesson)})")
                await message.answer("\n".join(lines), reply_markup=materials_lessons_keyboard(lessons), parse_mode=None)
                return True
            lesson = lessons[0]
            if has_homework_lookup_intent(text) or "дз" in text or "домаш" in text:
                await send_materials_by_lookup(
                    message,
                    {
                        "lesson_key": lesson.lesson_key,
                        "lesson_date": lesson.date_start,
                        "module_number": lesson.lesson_number,
                        "content_type": "homework",
                        "label": lesson.lesson_title,
                    },
                    telegram_user=telegram_user,
                )
                return True
            if wants_lesson_card_request(text):
                await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
                return True
            if wants_lesson_overview(text):
                await send_lesson_overview(
                    message,
                    lesson,
                    state=state,
                    question_text=text_value,
                    telegram_user=telegram_user,
                )
                return True
            await send_materials_lesson_card(message, lesson, telegram_user=telegram_user)
            return True

        return False

    def media_caption(media) -> str | None:
        if media.media_type == "schedule_image":
            return None
        module_text = f"Модуль {media.module_number}" if media.module_number else "Без модуля"
        date_text = format_lesson_date(media.lesson_date)
        return f"{media.title}\n{module_text}\nДата: {date_text}"

    def has_reusable_telegram_file_id(media) -> bool:
        telegram_file_id = (getattr(media, "telegram_file_id", None) or "").strip()
        return bool(telegram_file_id) and not telegram_file_id.startswith("server-local:")

    async def answer_media_too_large(message: Message, media, file_size: int | None = None) -> None:
        size_text = ""
        if file_size:
            size_text = f" Сейчас размер файла примерно {file_size / 1024 / 1024:.0f} МБ."
        await message.answer(
            f"Видео «{media.title}» пока слишком большое для отправки прямо в Telegram.{size_text}\n\n"
            "Мы уже видим его в библиотеке, но для текущей версии нужно сжать файл примерно до 50 МБ "
            "или позже подключить выдачу по ссылке/стримингу.",
            reply_markup=materials_program_keyboard(),
            parse_mode=None,
        )

    async def answer_video_watch_link(message: Message, media) -> bool:
        video_url = build_video_watch_url_for_media(media)
        if not video_url:
            return False
        await message.answer(
            f"Запись доступна по кнопке ниже.\n\n{media_caption(media)}",
            reply_markup=video_watch_keyboard(video_url),
            parse_mode=None,
        )
        return True

    async def send_media_asset(message: Message, media) -> None:
        caption = media_caption(media)
        try:
            if media.media_type == "video" and await answer_video_watch_link(message, media):
                return

            local_path = resolve_stored_file_path(getattr(media, "stored_path", None))
            if local_path and local_path.exists() and local_path.is_file():
                file_size = local_path.stat().st_size
                if file_size > TELEGRAM_BOT_UPLOAD_LIMIT_BYTES and not has_reusable_telegram_file_id(media):
                    await answer_media_too_large(message, media, file_size=file_size)
                    return
                if file_size > TELEGRAM_BOT_UPLOAD_LIMIT_BYTES and has_reusable_telegram_file_id(media):
                    local_path = None
                else:
                    local_file = FSInputFile(local_path, filename=media.original_filename or local_path.name)

            if local_path and local_path.exists() and local_path.is_file():
                if media.media_type == "video" or media.telegram_kind == "video":
                    await message.answer_video(video=local_file, caption=caption, parse_mode=None)
                    return
                if media.media_type == "podcast" or media.telegram_kind == "audio":
                    await message.answer_audio(audio=local_file, caption=caption, parse_mode=None)
                    return
                if media.telegram_kind == "voice":
                    await message.answer_voice(voice=local_file, caption=caption, parse_mode=None)
                    return
                if media.telegram_kind == "photo":
                    await message.answer_photo(photo=local_file, caption=caption, parse_mode=None)
                    return
                await message.answer_document(document=local_file, caption=caption, parse_mode=None)
                return

            if not media.telegram_file_id:
                await message.answer(
                    f"Не получилось найти файл «{media.title}». "
                    "Напиши организаторам, они проверят материал."
                )
                return

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
        except TelegramEntityTooLarge:
            logger.exception("send_media_asset_too_large media_id=%s", getattr(media, "id", None))
            await answer_media_too_large(message, media, file_size=getattr(media, "file_size", None))
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
            await message.answer(
                empty_text,
                reply_markup=empty_reply_markup or await user_main_menu_for_message(message),
            )
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
            empty_text="Видео записей пока не загружены. Ниже — материалы занятий и презентации.",
            include_docs_button=True,
        )
        if not has_video:
            await send_materials_list(
                message,
                telegram_user=telegram_user,
                title="Записи и материалы занятий",
            )

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
            all_homeworks = await HomeworkRepository.list_active(session)

        homeworks = current_homeworks(all_homeworks)
        archive = archived_homeworks(all_homeworks)

        if not all_homeworks:
            await message.answer(
                "Домашние задания пока не добавлены.\n\n"
                "Когда организаторы добавят ДЗ, они появятся здесь.",
                reply_markup=homework_list_keyboard([]),
                parse_mode=None,
            )
            return

        if not homeworks:
            await message.answer(
                "Актуальных домашних заданий сейчас нет.\n\n"
                "Старые задания можно посмотреть в архиве.",
                reply_markup=homework_list_keyboard([], include_archive=bool(archive)),
                parse_mode=None,
            )
            return

        lines = ["Список домашних заданий:", ""]
        for homework in homeworks[:20]:
            deadline_text = f"; срок сдачи: {homework_deadline_label(homework)}" if homework.deadline_date else ""
            lines.append(f"- {homework.title} ({homework_lesson_label(homework)}{deadline_text})")
        lines.extend(["", "Выбери задание кнопкой ниже или задай свой вопрос по домашке."])
        await message.answer(
            "\n".join(lines),
            reply_markup=homework_list_keyboard(homeworks, include_archive=bool(archive)),
        )

    async def send_homework_archive(message: Message) -> None:
        async with SessionLocal() as session:
            all_homeworks = await HomeworkRepository.list_active(session, limit=100)

        homeworks = archived_homeworks(all_homeworks)
        if not homeworks:
            await message.answer(
                "В архиве пока нет домашних заданий с прошедшим сроком сдачи.",
                reply_markup=homework_list_keyboard([]),
                parse_mode=None,
            )
            return

        lines = ["Архив домашних заданий:", ""]
        for homework in homeworks[:30]:
            deadline_text = f"; срок сдачи: {homework_deadline_label(homework)}" if homework.deadline_date else ""
            lines.append(f"- {homework.title} ({homework_lesson_label(homework)}{deadline_text})")
        lines.extend(["", "Эти задания уже не показываются в основном списке, но их можно открыть для справки."])
        await message.answer("\n".join(lines), reply_markup=homework_list_keyboard(homeworks), parse_mode=None)

    async def send_homework_item(message: Message, homework_id: int) -> None:
        async with SessionLocal() as session:
            homework = await HomeworkRepository.get_by_id(session, homework_id)
            related_documents = []
            if homework is not None:
                related_documents = await DocumentRepository.list_ready_global_by_lesson_and_type(
                    session=session,
                    material_type="homework",
                    lesson_key=homework.lesson_key,
                    lesson_date=homework.lesson_date,
                    limit=10,
                )

        if homework is None or homework.status != "active":
            await message.answer("Не нашёл такое домашнее задание. Показываю список актуальных заданий.")
            await send_homework_list(message)
            return

        lines = [
            f"Домашнее задание: {escape(homework.title)}",
            escape(homework_lesson_label(homework)),
        ]
        if homework.deadline_date:
            lines.append(f"Срок сдачи: {escape(homework_deadline_label(homework))}")
        description = homework_description_for_user(homework.description)
        if description:
            lines.extend(["", escape(description)])
        if homework.moodle_url:
            lines.extend(["", f"Ссылка для сдачи: {escape(homework.moodle_url)}"])
        if related_documents:
            lines.extend(["", "Файлы к заданию отправлю ниже."])
        elif homework.document_id and not description:
            lines.extend(["", "Файл задания прикреплён к этому ДЗ."])
        await message.answer("\n".join(lines), reply_markup=homework_detail_keyboard(homework.id))
        for document in related_documents:
            await send_document_original(message, document)

    async def start_homework_help(message: Message, state: FSMContext, homework_id: int | None = None) -> None:
        await state.set_state(UserFlow.waiting_for_homework_help_question)
        await state.update_data(selected_homework_id=homework_id)
        suffix = ""
        if homework_id:
            suffix = "\n\nЯ буду учитывать выбранное домашнее задание."
        await message.answer(
            f"{HOMEWORK_HELP_PROMPT}{suffix}",
            reply_markup=await user_main_menu_for_message(message),
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
                notification_active = await AppSettingRepository.get_value(session, NOTIFICATION_ACTIVE_KEY)
                notification_expires_at = await AppSettingRepository.get_value(session, NOTIFICATION_EXPIRES_AT_KEY)
        except Exception:
            ics_filename = None
            notification_active = None
            notification_expires_at = None
        active_text = "активно" if _setting_enabled(notification_active) else "остановлено"
        if notification_expires_at:
            active_text += f", до {notification_expires_at}"
        lines.append(f"- Рассылка уведомления: {active_text}")
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
                await callback.message.answer(
                    "Спасибо! Рад, что ответ был полезен.",
                    reply_markup=await user_main_menu_for_callback(callback),
                )
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
                reply_markup=await user_main_menu_for_callback(callback),
            )

    @router.callback_query(F.data == "menu:main")
    async def inline_main_menu_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Выбери действие:",
                reply_markup=await user_main_menu_for_callback(callback),
            )

    @router.callback_query(F.data == "homework:list")
    async def homework_list_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_homework_list(callback.message)

    @router.callback_query(F.data == "homework:archive")
    async def homework_archive_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_homework_archive(callback.message)

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
                reply_markup=await user_main_menu_for_callback(callback),
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
                    await get_bot_text("support_contacts"),
                    reply_markup=await user_main_menu_for_callback(callback),
                )
            return
        await state.set_state(UserFlow.waiting_for_categorized_question)
        await state.update_data(question_section=section)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "Напиши свой вопрос.",
                reply_markup=await user_main_menu_for_callback(callback),
            )

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
        if command_argument(message.text) == "bot_feedback":
            await start_bot_feedback_flow(message, state)
            return
        await message.answer(
            await get_bot_text("welcome"),
            reply_markup=await user_main_menu_for_message(message),
            link_preview_options=NO_LINK_PREVIEW,
        )
        await message.answer(
            "Я буду напоминать тебе о занятиях и домашних заданиях. "
            "Выбери время, когда тебе будет удобно получать уведомления:",
            reply_markup=start_notification_time_keyboard(),
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(
            await get_bot_text("help"),
            reply_markup=await user_main_menu_for_message(message),
            link_preview_options=NO_LINK_PREVIEW,
        )

    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer(
            "Действие отменено. Вернул в главное меню.",
            reply_markup=await user_main_menu_for_message(message),
        )

    @router.message(Command("admin"))
    @router.message(F.text == "Админ: меню")
    async def admin_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())

    @router.message(F.text == "Кабинет руководителя")
    async def director_dashboard_handler(message: Message, state: FSMContext) -> None:
        user = await ensure_user(message)
        demo_access = is_director_dashboard_demo_user(user.telegram_id)
        async with SessionLocal() as session:
            has_team = await DirectorAssignmentRepository.has_active_team(session, user.telegram_id)

        if not is_admin(message) and not has_team and not demo_access:
            await message.answer(
                "Кабинет руководителя пока доступен только руководителям с назначенной командой. "
                "Если доступ нужен, напиши организаторам программы.",
                reply_markup=await user_main_menu_for_message(message),
                parse_mode=None,
            )
            return

        base_url = (container.settings.video_base_url or "").strip()
        if not base_url:
            await message.answer(
                "Кабинет руководителя пока не настроен: не задан адрес mini app.",
                reply_markup=(
                    admin_menu_keyboard()
                    if is_admin(message)
                    else await user_main_menu_for_message(message)
                ),
                parse_mode=None,
            )
            return

        await state.clear()
        dashboard_url = build_director_dashboard_url(
            base_url=base_url,
            telegram_id=user.telegram_id,
            secret=container.settings.video_link_secret,
            ttl_hours=container.settings.video_link_ttl_hours,
        )
        access_note = (
            "Это тестовый режим для администраторов. "
            "В реальном режиме руководитель увидит только сотрудников, которые будут явно назначены ему в базе."
            if is_admin(message) or demo_access
            else "Ты увидишь только сотрудников, назначенных тебе в базе программы."
        )
        await message.answer(
            "Кабинет руководителя\n\n"
            "Здесь будет безопасная сводка по обучению команды: вход в бота, уведомления, активность, обратная связь "
            "и, позже, статусы домашних заданий из выгрузок ПРОГРЕССа.\n\n"
            "Личные вопросы участников, ответы ИИ и тексты обратной связи руководителям не показываются.\n\n"
            f"{access_note}",
            reply_markup=director_dashboard_keyboard(dashboard_url),
            parse_mode=None,
        )

    @router.message(F.text.in_(["Статус и аналитика"]))
    async def admin_status_section_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(
            "Здесь можно проверить состояние бота и посмотреть, как им пользуются участники.\n\n"
            "Доступны состояние сервисов, активность, ошибки, примерные расходы OpenAI и выгрузка данных. "
            "Никакие сообщения пользователям из этого раздела не отправляются.",
            reply_markup=admin_status_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text.in_(["Управление материалами", "Админ: материалы программы"]))
    async def admin_materials_section_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(
            "Здесь можно добавлять и просматривать материалы программы: презентации, саммари, "
            "домашние задания, видео, подкасты и транскрипции занятий.\n\n"
            "Мини-чеклист после занятия:\n"
            "1. Загрузить презентации и дополнительные материалы.\n"
            "2. Загрузить саммари, если оно есть.\n"
            "3. Загрузить ДЗ и проверить дедлайн сдачи.\n"
            "4. Загрузить видео/подкаст, если они готовы.\n"
            "5. Загрузить транскрипцию как «Тип: транскрипция» — участники её не видят отдельной кнопкой, "
            "но ИИ использует её как дополнительный контекст.\n\n"
            "«Добавить материал» - для файлов, по которым ИИ должен отвечать.\n"
            "«Добавить видео/подкаст» - для медиафайлов, которые бот просто отдаёт участникам.\n\n"
            "При добавлении бот проведёт по шагам и привяжет материал к нужному занятию. "
            "Участникам ничего не отправится автоматически.",
            reply_markup=admin_materials_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "Сервисные действия")
    async def admin_materials_service_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(
            "Сервисные действия нужны редко.\n\n"
            "Переиндексация заново создаёт RAG-индекс для загруженных документов и может занять время. "
            "Она не удаляет материалы и не отправляет сообщения участникам.",
            reply_markup=admin_materials_service_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text.in_(["Уведомления и сообщения", "Админ: уведомления и сообщения"]))
    async def admin_notifications_section_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(
            "Здесь управляются автоматические напоминания о занятиях и домашних заданиях, "
            "а также ручные сообщения в общий чат.\n\n"
            "Перед ручной отправкой бот покажет текст и попросит подтверждение.",
            reply_markup=admin_notifications_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text.in_(["Тексты и оформление", "Админ: тексты"]))
    async def admin_content_section_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        async with SessionLocal() as session:
            custom_texts = {item.key for item in await BotTextRepository.list_all(session)}
        changed = sum(1 for key in BOT_TEXT_DEFAULTS if key in custom_texts and key != NOTIFICATION_TEXT_KEY)
        await message.answer(
            "Здесь можно изменить тексты и изображения, которые видят участники: приветствие, помощь, "
            "расписание, картинку расписания и контакты поддержки.\n\n"
            f"Изменённых текстов сейчас: {changed}. Перед сохранением бот покажет предпросмотр. "
            "Рассылки из этого раздела не запускаются.",
            reply_markup=admin_texts_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "Календарные файлы")
    async def admin_calendar_section_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        async with SessionLocal() as session:
            filename = await AppSettingRepository.get_value(session, NOTIFICATION_ICS_FILENAME_KEY)
        await message.answer(
            "Здесь хранится календарный `.ics`-файл, который бот прикладывает к уведомлениям.\n\n"
            f"Текущий файл: {filename or 'не загружен'}.\n"
            "Загрузка нового файла заменит текущий. ИИ этот файл не использует.",
            reply_markup=admin_calendar_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "Домашние задания в базе")
    async def admin_homeworks_section_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            homeworks = await HomeworkRepository.list_active(session, limit=30)
        if not homeworks:
            await message.answer("Домашние задания пока не добавлены.", reply_markup=admin_materials_keyboard())
            return
        lines = ["Домашние задания в базе:", ""]
        for homework in homeworks:
            lines.append(
                f"- {homework.title}\n"
                f"  {homework_lesson_label(homework)} · срок: {homework_deadline_label(homework)}"
            )
        lines.extend(["", "Чтобы добавить новое ДЗ, выбери «Добавить материал» и тип «домашнее задание»."])
        await message.answer("\n".join(lines), reply_markup=admin_materials_keyboard(), parse_mode=None)

    @router.message(F.text == "Ошибки")
    async def admin_errors_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            errors = await ErrorRepository.latest(session, limit=10)
        if not errors:
            await message.answer("Ошибок в журнале нет.", reply_markup=admin_status_keyboard())
            return
        lines = ["Последние ошибки:"]
        for error in errors:
            lines.append(f"- {_format_admin_datetime(error.created_at)} · {error.context}: {error.error_text[:180]}")
        await message.answer("\n".join(lines), reply_markup=admin_status_keyboard(), parse_mode=None)

    @router.message(F.text == "Ближайшие уведомления")
    async def admin_upcoming_notifications_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer(
            await build_notification_admin_report(),
            reply_markup=admin_notifications_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "История отправок")
    async def admin_notification_history_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT nd.delivery_date, nd.scheduled_time, nd.notification_key, nd.status,
                           u.full_name, u.username, u.telegram_id
                    FROM notification_deliveries nd
                    JOIN users u ON u.id = nd.user_id
                    ORDER BY nd.created_at DESC
                    LIMIT 15
                    """
                )
            )
            rows = list(result.mappings().all())
        if not rows:
            await message.answer("История автоматических отправок пока пуста.", reply_markup=admin_notifications_keyboard())
            return
        lines = ["Последние автоматические отправки:"]
        for row in rows:
            recipient = row["full_name"] or (f"@{row['username']}" if row["username"] else str(row["telegram_id"]))
            notification_type = "занятие" if str(row["notification_key"]).startswith("lesson:") else "домашнее задание"
            lines.append(
                f"- {row['delivery_date']} {row['scheduled_time']} · {notification_type} · "
                f"{recipient} · {row['status']}"
            )
        await message.answer("\n".join(lines), reply_markup=admin_notifications_keyboard(), parse_mode=None)

    @router.message(F.text.in_(["Отправить сообщение", "Админ: ручное сообщение", "Админ: напоминание"]))
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
            "Это ручная разовая отправка в общий чат. Она не связана с автоуведомлениями по событиям и домашкам.\n\n"
            "После ввода бот покажет предпросмотр и только потом предложит отправить сообщение.",
            reply_markup=admin_notifications_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_reminder_text, F.text)
    async def admin_reminder_text_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        admin_navigation_texts = all_reply_button_labels()
        if message.text in admin_navigation_texts:
            await state.clear()
            await message.answer(
                "Ручное сообщение не отправил. Если нужно начать заново, выбери «Отправить сообщение».",
                reply_markup=admin_notifications_keyboard(),
            )
            return
        pending_text = _message_html_text(message)
        await state.update_data(pending_reminder_text=pending_text)
        await state.set_state(AdminFlow.waiting_for_reminder_confirm)
        await message.answer(
            f"Предпросмотр сообщения:\n\n{pending_text}\n\n"
            "Проверь текст. После подтверждения сообщение сразу уйдёт в привязанный групповой чат.",
            reply_markup=admin_message_preview_keyboard(),
            parse_mode="HTML",
            link_preview_options=NO_LINK_PREVIEW,
        )

    @router.callback_query(
        AdminFlow.waiting_for_reminder_confirm,
        F.data.in_(["admin_message:send", "admin_message:cancel"]),
    )
    async def admin_reminder_confirm_handler(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin_user_id(callback.from_user.id):
            await callback.answer("Эта кнопка доступна только администратору.", show_alert=True)
            await state.clear()
            return
        if callback.data == "admin_message:cancel":
            await callback.answer("Отменено.")
            await state.clear()
            if callback.message:
                await callback.message.answer(
                    "Сообщение не отправлено.",
                    reply_markup=admin_notifications_keyboard(),
                )
            return
        data = await state.get_data()
        pending_text = data.get("pending_reminder_text")
        if not pending_text or callback.message is None:
            await callback.answer("Текст сообщения потерян. Начни заново.", show_alert=True)
            await state.clear()
            return
        user = await upsert_telegram_user(callback.from_user)
        await callback.answer("Отправляю.")
        await send_reminder_to_group(callback.message, pending_text, user.id, parse_mode="HTML")
        await state.clear()

    @router.message(AdminFlow.waiting_for_reminder_confirm)
    async def admin_reminder_confirm_waiting_handler(message: Message) -> None:
        await message.answer("Нажми «Отправить сообщение» или «Отменить» под предпросмотром.")

    async def build_admin_overview_report() -> str:
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(days=1)
        since_7d = now - timedelta(days=7)
        exclude_admin_ids = container.settings.admin_ids

        db_started = time.monotonic()
        latest_errors = []
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
                totals = await StatsRepository.dashboard(session)
                latest_errors = await ErrorRepository.latest(session, limit=3)
                allowed_count = await AllowedUserRepository.count_active(session)
                recent_users = await UserRepository.list_recent(session, limit=5)
                active_24h = await UserEventRepository.active_users_since(
                    session,
                    since_24h,
                    exclude_telegram_ids=exclude_admin_ids,
                )
                active_7d = await UserEventRepository.active_users_since(
                    session,
                    since_7d,
                    exclude_telegram_ids=exclude_admin_ids,
                )
                button_events_24h = await UserEventRepository.count_events_since(
                    session,
                    since_24h,
                    event_types=["reply_button", "inline_button"],
                    exclude_telegram_ids=exclude_admin_ids,
                )
                top_7d = await UserEventRepository.top_events(
                    session,
                    ["reply_button", "inline_button"],
                    since=since_7d,
                    limit=5,
                    exclude_telegram_ids=exclude_admin_ids,
                )
                usage_today = await StatsRepository.token_usage_since(session, since_24h)
                usage_week = await StatsRepository.token_usage_since(session, since_7d)
                active_value = await AppSettingRepository.get_value(session, NOTIFICATION_ACTIVE_KEY)
                tomorrow = datetime.now().date() + timedelta(days=1)
                due_lessons = await ProgramLessonRepository.list_by_start_date(session, tomorrow)
                due_homeworks = await HomeworkRepository.list_by_deadline(session, tomorrow)
            db_ms = int((time.monotonic() - db_started) * 1000)
            db_status = f"OK ({db_ms} мс)"
        except Exception as exc:
            totals = {}
            allowed_count = active_24h = active_7d = button_events_24h = 0
            top_7d = []
            recent_users = []
            usage_today = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            usage_week = usage_today
            active_value = "false"
            due_lessons = []
            due_homeworks = []
            db_status = f"ошибка ({str(exc)[:120]})"

        llm_status = "не проверял"
        try:
            chat_started = time.monotonic()
            await container.llm_client.chat_completion(
                system_prompt="Ты healthcheck. Ответь только OK.",
                user_prompt="Ответь только OK.",
                temperature=0,
            )
            llm_status = f"OK ({int((time.monotonic() - chat_started) * 1000)} мс)"
        except Exception as exc:
            llm_status = f"ошибка ({str(exc)[:120]})"

        settings = container.settings

        def openai_chat_cost(usage: dict[str, int]) -> float:
            input_cost_usd = usage["prompt_tokens"] / 1_000_000 * settings.openai_chat_input_usd_per_1m
            output_cost_usd = usage["completion_tokens"] / 1_000_000 * settings.openai_chat_output_usd_per_1m
            return (input_cost_usd + output_cost_usd) * settings.usd_rub_rate

        data_size_mb = _dir_size_mb(container.settings.data_dir)
        lines = [
            "Админ-обзор:",
            "",
            "Состояние:",
            f"- база данных: {db_status}",
            f"- LLM: {llm_status}",
            f"- автоуведомления: {'включены' if _setting_enabled(active_value) else 'остановлены'}",
            f"- завтра к отправке: событий={len(due_lessons)}, домашек={len(due_homeworks)}",
            "",
            "Контент и RAG:",
            f"- документов: {totals.get('documents', 0)}",
            f"- чанков: {totals.get('chunks', 0)}",
            f"- ДЗ: {totals.get('active_homeworks', 0)}",
            f"- личных файлов: {totals.get('user_documents', 0)}",
            f"- размер data: {data_size_mb:.1f} МБ",
            "",
            "Пользователи и активность:",
            f"- в списке доступа: {allowed_count}",
            f"- пользователей в БД: {totals.get('users', 0)}",
            f"- активных за 24ч/7д: {active_24h}/{active_7d}",
            f"- вопросов за 24ч/7д/30д: {totals.get('messages_today', 0)}/{totals.get('messages_week', 0)}/{totals.get('messages_month', 0)}",
            f"- кликов по кнопкам за 24ч: {button_events_24h}",
            "",
            "Расходы OpenAI, примерно:",
            f"- 24ч: {_format_rub(openai_chat_cost(usage_today))}",
            f"- 7д: {_format_rub(openai_chat_cost(usage_week))}",
            "",
            "Топ кнопок за 7д:",
        ]
        if top_7d:
            for stat in top_7d:
                lines.append(f"- {stat.event_name}: {stat.count}")
        else:
            lines.append("- пока нет данных")

        lines.extend(["", "Последние пользователи:"])
        if recent_users:
            for user in recent_users:
                name = user.full_name or user.username or str(user.telegram_id)
                username = f"@{user.username}" if user.username else "без username"
                lines.append(f"- {name} ({username}), id={user.telegram_id}")
        else:
            lines.append("- пока нет данных")

        lines.extend(["", "Последние ошибки:"])
        if latest_errors:
            for error in latest_errors:
                lines.append(f"- {error.context}: {error.error_text[:120]}")
        else:
            lines.append("- ошибок нет")

        return "\n".join(lines)

    async def build_notification_admin_report() -> str:
        async with SessionLocal() as session:
            active_value = await AppSettingRepository.get_value(session, NOTIFICATION_ACTIVE_KEY)
            recipients_by_time = {
                time_value: len(await UserNotificationSettingRepository.list_due_recipients(session, time_value))
                for time_value in NOTIFICATION_TIME_OPTIONS
            }
            tomorrow = datetime.now().date() + timedelta(days=1)
            due_lessons = await ProgramLessonRepository.list_by_start_date(session, tomorrow)
            due_homeworks = await HomeworkRepository.list_by_deadline(session, tomorrow)

        active = _setting_enabled(active_value)
        lines = [
            "Автоуведомления:",
            f"- статус: {'включены' if active else 'остановлены'}",
            "",
            "Есть только две автоматические логики:",
            "- события: за 1 день до даты занятия",
            "- домашки: за 1 день до дедлайна сдачи",
            "- время: то, которое выбрал пользователь",
            f"- к отправке завтра: событий={len(due_lessons)}, домашек={len(due_homeworks)}",
            "",
            "Получателей по выбранному времени:",
        ]
        for time_value, count in recipients_by_time.items():
            lines.append(f"- {time_value}: {count}")
        lines.extend(
            [
                "",
                "Ручные сообщения в общий чат - отдельная админская функция. Они не относятся к автоуведомлениям.",
            ]
        )
        return "\n".join(lines)

    @router.message(Command("admin_overview"))
    @router.message(F.text.in_(["Админ: обзор", "Админ: статус", "Админ: статистика", "Админ: аналитика", "Админ: расходы"]))
    async def admin_overview_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer("Собираю статус, статистику и аналитику...")
        await message.answer(
            await build_admin_overview_report(),
            reply_markup=admin_overview_keyboard(),
            parse_mode=None,
        )

    @router.message(Command("notification_status"))
    @router.message(F.text.in_(["Настройки автоуведомлений", "Админ: автоуведомления", "Админ: уведомления"]))
    async def admin_notification_status_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer(
            await build_notification_admin_report(),
            reply_markup=admin_notification_control_keyboard(),
            parse_mode=None,
        )

    @router.callback_query(F.data.in_(["admin_notifications:start", "admin_notifications:stop", "admin_notifications:refresh"]))
    async def admin_notification_control_callback(callback: CallbackQuery) -> None:
        if not is_admin_user_id(callback.from_user.id):
            await callback.answer("Эта кнопка доступна только администратору.", show_alert=True)
            return
        user = await upsert_telegram_user(callback.from_user)
        if callback.data == "admin_notifications:start":
            async with SessionLocal() as session:
                await AppSettingRepository.upsert(
                    session,
                    key=NOTIFICATION_ACTIVE_KEY,
                    value="true",
                    updated_by_user_id=user.id,
                )
                await AppSettingRepository.upsert(
                    session,
                    key=NOTIFICATION_EXPIRES_AT_KEY,
                    value="",
                    updated_by_user_id=user.id,
                )
            await callback.answer("Автоуведомления включены.")
        elif callback.data == "admin_notifications:stop":
            async with SessionLocal() as session:
                await AppSettingRepository.upsert(
                    session,
                    key=NOTIFICATION_ACTIVE_KEY,
                    value="false",
                    updated_by_user_id=user.id,
                )
            await callback.answer("Автоуведомления остановлены.")
        else:
            await callback.answer("Обновляю статус.")

        if callback.message:
            report = await build_notification_admin_report()
            try:
                await callback.message.edit_text(
                    report,
                    reply_markup=admin_notification_control_keyboard(),
                    parse_mode=None,
                )
            except TelegramBadRequest:
                await callback.message.answer(
                    report,
                    reply_markup=admin_notification_control_keyboard(),
                    parse_mode=None,
                )

    @router.message(Command("stop_notifications"))
    @router.message(F.text == "Админ: стоп уведомления")
    async def admin_stop_notifications_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        user = await ensure_user(message)
        async with SessionLocal() as session:
            await AppSettingRepository.upsert(
                session,
                key=NOTIFICATION_ACTIVE_KEY,
                value="false",
                updated_by_user_id=user.id,
            )
        await message.answer(
            "Автоуведомления остановлены.\n\n"
            "Бот не будет отправлять уведомления по событиям и домашкам, пока админ не включит их обратно.",
            reply_markup=admin_notifications_keyboard(),
            parse_mode=None,
        )

    @router.message(Command("start_notifications"))
    async def admin_start_notifications_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        expires_argument = command_argument(message.text)
        expires_at = parse_notification_expiry(expires_argument)
        if expires_argument and expires_at is None:
            await message.answer(
                "Не понял срок годности уведомления.\n\n"
                "Пример: /start_notifications 2026-05-22 12:00\n"
                "Или: /start_notifications 22.05 12:00",
                reply_markup=admin_menu_keyboard(),
                parse_mode=None,
            )
            return

        user = await ensure_user(message)
        async with SessionLocal() as session:
            await AppSettingRepository.upsert(
                session,
                key=NOTIFICATION_ACTIVE_KEY,
                value="true",
                updated_by_user_id=user.id,
            )
            await AppSettingRepository.upsert(
                session,
                key=NOTIFICATION_EXPIRES_AT_KEY,
                value=expires_at.isoformat(timespec="minutes") if expires_at else "",
                updated_by_user_id=user.id,
            )

        if expires_at is None:
            tail = "Бот будет отправлять только одноразовые уведомления по событиям и домашкам."
        else:
            tail = f"Бот перестанет отправлять автоуведомления после {expires_at.strftime('%d.%m.%Y %H:%M')}."
        await message.answer(
            f"Автоуведомления включены.\n\n{tail}",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(Command("upload_global_material"))
    @router.message(
        F.text.in_(
            [
                "Админ: загрузить материал для ИИ и пользователей",
                "Админ: загрузить материал для ИИ",
                "Админ: загрузить материал",
                "Добавить материал",
            ]
        )
    )
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
            "Тип: транскрипция": "transcript",
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
                "Шаг 5 из 7: пришли ссылку на Moodle/ПРОГРЕСС для сдачи домашнего задания.\n\n"
                "Если ссылки пока нет, нажми «Ссылка: без ссылки».",
                reply_markup=admin_homework_link_keyboard(),
                parse_mode=None,
            )
            return

        await state.set_state(AdminFlow.waiting_for_global_file)
        text_upload_hint = ""
        if material_type == "summary":
            text_upload_hint = (
                "Саммари можно прислать обычным текстом прямо сообщением. "
                "Первая строка станет названием, весь текст попадёт в RAG и раздел саммари.\n"
                "Если саммари уже оформлено файлом, пришли PDF/DOCX/PPTX/TXT.\n\n"
            )
        await message.answer(
            "Шаг 5 из 5: пришли материал.\n\n"
            + text_upload_hint
            + (
                "Если это не саммари, пришли файл PDF/DOCX/PPTX/TXT.\n\n"
                if material_type != "summary"
                else ""
            )
            + (
                "Транскрипция будет использоваться как скрытый контекст для ИИ: "
                "участники не увидят её отдельной кнопкой в материалах.\n\n"
                if material_type == "transcript"
                else ""
            )
            + f"Будет сохранено так:\n"
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
        lesson_key = data.get("material_lesson_key")
        lesson_date_raw = data.get("material_lesson_date")
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
        link_text = moodle_url or "без ссылки"

        async with SessionLocal() as session:
            next_lesson = await ProgramLessonRepository.get_next_after(
                session=session,
                lesson_key=lesson_key,
                lesson_date=lesson_date,
            )

        default_deadline = next_lesson.date_start if next_lesson and next_lesson.date_start else None
        await state.update_data(homework_default_deadline=default_deadline.isoformat() if default_deadline else None)

        next_lesson_text = (
            f"{format_lesson_date(default_deadline)} ({next_lesson.lesson_title})"
            if default_deadline and next_lesson
            else "следующее занятие не найдено"
        )
        await state.set_state(AdminFlow.waiting_for_homework_deadline)
        await message.answer(
            "Шаг 6 из 7: укажи дедлайн сдачи ДЗ.\n\n"
            "Технически дедлайн обычно равен дате следующего занятия.\n"
            f"Нашёл следующее занятие: {next_lesson_text}.\n\n"
            "Можно написать дату вручную в формате `30.05.2026`, нажать «Дедлайн: следующее занятие» "
            "или «Дедлайн: без даты».\n\n"
            f"Ссылка для сдачи: {link_text}",
            reply_markup=admin_homework_deadline_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_homework_deadline, F.text)
    async def admin_homework_deadline_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text == "Админ: меню":
            await state.clear()
            await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
            return

        data = await state.get_data()
        default_deadline_raw = data.get("homework_default_deadline")
        default_deadline = date.fromisoformat(default_deadline_raw) if default_deadline_raw else None

        if message.text == "Дедлайн: следующее занятие":
            if default_deadline is None:
                await message.answer(
                    "Не нашёл следующее занятие для этой привязки. Напиши дату вручную или нажми «Дедлайн: без даты».",
                    reply_markup=admin_homework_deadline_keyboard(),
                    parse_mode=None,
                )
                return
            deadline_date = default_deadline
        elif message.text == "Дедлайн: без даты":
            deadline_date = None
        else:
            try:
                deadline_date = parse_lesson_date_input(message.text)
            except ValueError:
                await message.answer(
                    "Не распознал дату дедлайна. Напиши в формате `30.05.2026`, нажми «Дедлайн: следующее занятие» "
                    "или «Дедлайн: без даты».",
                    reply_markup=admin_homework_deadline_keyboard(),
                    parse_mode=None,
                )
                return

        await state.update_data(homework_deadline_date=deadline_date.isoformat() if deadline_date else None)
        data = await state.get_data()
        season_title = data.get("material_season_title") or "без сезона"
        module_number = data.get("material_module_number")
        module_title = data.get("material_module_title")
        lesson_date_raw = data.get("material_lesson_date")
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
        module_text = module_title or (f"урок/модуль {module_number}" if module_number else "общий материал")
        link_text = data.get("homework_moodle_url") or "без ссылки"

        await state.set_state(AdminFlow.waiting_for_global_file)
        await message.answer(
            "Шаг 7 из 7: пришли домашнее задание.\n\n"
            "Можно отправить обычный текст прямо сообщением — бот будет показывать его участникам как текст ДЗ.\n"
            "Если нужен отдельный файл, пришли PDF/DOCX/PPTX/TXT. Для файла можно добавить подпись: первая строка станет названием ДЗ, остальные строки — описанием.\n\n"
            f"Будет сохранено так:\n"
            f"- сезон: {season_title}\n"
            f"- привязка: {module_text}\n"
            f"- дата занятия: {format_lesson_date(lesson_date)}\n"
            f"- дедлайн сдачи: {format_lesson_date(deadline_date)}\n"
            f"- тип: домашнее задание\n"
            f"- ссылка: {link_text}",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "Админ: техфайлы")
    async def admin_tech_files_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer(
            "Техфайлы и медиа - это файлы, которые бот хранит и отдаёт пользователям, но не отправляет в RAG/ИИ.\n\n"
            "Что сюда относится:\n"
            "- ICS для календаря\n"
            "- картинка расписания\n"
            "- видео и подкасты занятий\n\n"
            "Если нужно загрузить PDF/DOCX/PPTX/TXT, по которым ИИ должен отвечать и которые должны видеть пользователи, "
            "используй «Админ: загрузить материал для ИИ и пользователей».",
            reply_markup=admin_tech_files_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text.in_(["Картинка расписания", "Техфайл: картинка расписания"]))
    async def admin_schedule_image_upload_prompt_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.update_data(
            media_type="schedule_image",
            media_module_number=None,
            media_module_title="Расписание Лиги Лидеров",
            media_lesson_key="schedule",
            media_lesson_date=None,
        )
        await state.set_state(AdminFlow.waiting_for_media_file)
        await message.answer(
            "Пришли картинку расписания.\n\n"
            "Она будет показываться пользователю в разделе «Расписание Лиги Лидеров». "
            "ИИ на эту картинку смотреть не будет.",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text.in_(["Добавить видео/подкаст", "Техфайл: видео/подкаст", "Админ: загрузить медиа"]))
    async def admin_media_upload_start_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.set_state(AdminFlow.waiting_for_media_type)
        await message.answer(
            "Запускаю мастер загрузки видео/подкаста.\n\n"
            "Эти файлы бот будет отдавать пользователям в разделе материалов, но ИИ не будет использовать их как источник ответа.\n"
            "Если видео тяжёлое, лучше предварительно сжать его и отправить как файл/документ .mp4.\n\n"
            "Шаг 1 из 4: выбери тип файла.",
            reply_markup=admin_media_type_keyboard(),
            parse_mode=None,
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
            await message.answer(
                "Загрузка медиа отменена. Вернул в главное меню.",
                reply_markup=await user_main_menu_for_message(message),
            )
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
            await message.answer("Пришли видео, аудио или файл-документ с видео/аудио.", reply_markup=admin_menu_keyboard())
            return

        state_data = await state.get_data()
        media_type = state_data.get("media_type")
        module_number = state_data.get("media_module_number")
        module_title = state_data.get("media_module_title")
        lesson_key = state_data.get("media_lesson_key")
        lesson_date_raw = state_data.get("media_lesson_date")
        lesson_date = date.fromisoformat(lesson_date_raw) if lesson_date_raw else None
        if media_type not in {"video", "podcast", "image", "schedule_image"}:
            await message.answer("Не понял тип медиа. Начни заново через «Админ: техфайлы».", reply_markup=admin_menu_keyboard())
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
        stored_path = await save_media_file_to_storage(message, payload, media_type)
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
                stored_path=stored_path,
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
        storage_text = "сохранён на сервере" if stored_path else "сохранён через Telegram file_id"
        storage_note = ""
        if media_type == "video" and not stored_path:
            storage_note = (
                "\n\nВажно: это видео не удалось скачать на сервер, поэтому mini app для него не включится. "
                "Бот попробует отдавать его через Telegram. Для просмотра в mini app нужно загрузить файл на сервер."
            )
        await message.answer(
            "Медиафайл сохранён.\n\n"
            f"- id: {media.id}\n"
            f"- тип: {type_text}\n"
            f"- название: {media.title}\n"
            f"- привязка: {module_text}\n"
            f"- дата: {format_lesson_date(lesson_date)}\n"
            f"- файл: {storage_text}\n"
            f"- теги: {', '.join(tags)}\n\n"
            "Теперь он будет доступен в разделе «Материалы программы»."
            f"{storage_note}",
            reply_markup=admin_menu_keyboard(),
        )
        await state.clear()

    @router.message(Command("list_materials"))
    @router.message(F.text.in_(["Библиотека материалов", "Админ: материалы"]))
    async def list_materials_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            docs = await DocumentRepository.list_materials(session, limit=100)
            media_items = await ProgramMediaRepository.list_latest(session, limit=30)
            homeworks = await HomeworkRepository.list_active(session, limit=30)
        if not docs and not media_items and not homeworks:
            await message.answer(
                "Материалы и медиа пока не загружены.",
                reply_markup=admin_materials_keyboard(),
            )
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
                    f"deadline={homework_deadline_label(homework)} | document_id={homework.document_id or 'none'}"
                )
        await message.answer(
            "\n".join(lines),
            reply_markup=admin_materials_keyboard(),
            parse_mode=None,
        )

    @router.message(Command("reindex"))
    @router.message(F.text == "Переиндексировать материалы")
    async def reindex_handler(message: Message) -> None:
        if not await require_admin(message):
            return

        await message.answer(
            "Запускаю переиндексацию документов, это может занять время...",
            reply_markup=admin_materials_service_keyboard(),
        )
        async with SessionLocal() as session:
            ok, failed = await container.document_service.reindex_all(session)
        await message.answer(
            f"Переиндексация завершена: успешно={ok}, с ошибками={failed}.",
            reply_markup=admin_materials_service_keyboard(),
        )

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
        await message.answer("\n".join(lines), reply_markup=admin_status_keyboard(), parse_mode=None)

    @router.message(Command("analytics"))
    @router.message(F.text.in_(["Активность участников", "Админ: аналитика"]))
    async def admin_analytics_handler(message: Message) -> None:
        if not await require_admin(message):
            return

        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(days=1)
        since_7d = now - timedelta(days=7)
        exclude_admin_ids = container.settings.admin_ids

        async with SessionLocal() as session:
            allowed_count = await AllowedUserRepository.count_active(session)
            recent_users = await UserRepository.list_recent(session, limit=10)
            active_24h = await UserEventRepository.active_users_since(
                session,
                since_24h,
                exclude_telegram_ids=exclude_admin_ids,
            )
            active_7d = await UserEventRepository.active_users_since(
                session,
                since_7d,
                exclude_telegram_ids=exclude_admin_ids,
            )
            button_events_24h = await UserEventRepository.count_events_since(
                session,
                since_24h,
                event_types=["reply_button", "inline_button"],
                exclude_telegram_ids=exclude_admin_ids,
            )
            button_events_7d = await UserEventRepository.count_events_since(
                session,
                since_7d,
                event_types=["reply_button", "inline_button"],
                exclude_telegram_ids=exclude_admin_ids,
            )
            top_24h = await UserEventRepository.top_events(
                session,
                ["reply_button", "inline_button"],
                since=since_24h,
                limit=10,
                exclude_telegram_ids=exclude_admin_ids,
            )
            top_7d = await UserEventRepository.top_events(
                session,
                ["reply_button", "inline_button"],
                since=since_7d,
                limit=10,
                exclude_telegram_ids=exclude_admin_ids,
            )
            button_counts_7d = await UserEventRepository.event_counts_by_name(
                session,
                USER_ANALYTICS_BUTTONS,
                since=since_7d,
                exclude_telegram_ids=exclude_admin_ids,
            )

        quiet_buttons = [button for button in USER_ANALYTICS_BUTTONS if button_counts_7d.get(button, 0) == 0]
        lines = [
            "Админ-аналитика:",
            "",
            "Пользователи:",
            f"- в allowlist: {allowed_count}",
            f"- активных за 24ч: {active_24h}",
            f"- активных за 7д: {active_7d}",
            "",
            "Клики по кнопкам:",
            f"- за 24ч: {button_events_24h}",
            f"- за 7д: {button_events_7d}",
            "",
            "Топ кнопок за 24ч:",
        ]
        if top_24h:
            for stat in top_24h:
                lines.append(f"- {stat.event_name}: {stat.count}")
        else:
            lines.append("- пока нет данных")

        lines.extend(["", "Топ кнопок за 7д:"])
        if top_7d:
            for stat in top_7d:
                lines.append(f"- {stat.event_name}: {stat.count}")
        else:
            lines.append("- пока нет данных")

        lines.extend(["", "Почти/совсем не нажимали за 7д:"])
        if quiet_buttons:
            for button in quiet_buttons[:12]:
                lines.append(f"- {button}")
            if len(quiet_buttons) > 12:
                lines.append(f"- ещё {len(quiet_buttons) - 12}")
        else:
            lines.append("- все ключевые кнопки уже нажимали")

        lines.extend(["", "Последние пользователи, которые зашли в бота:"])
        if recent_users:
            for user in recent_users:
                name = user.full_name or user.username or str(user.telegram_id)
                username = f"@{user.username}" if user.username else "без username"
                lines.append(f"- {name} ({username}), id={user.telegram_id}, {_format_admin_datetime(user.created_at)}")
        else:
            lines.append("- пока нет пользователей")

        lines.extend(
            [
                "",
                "Важно: клики собираются с момента включения этой аналитики. Старые нажатия из прошлого не восстановить.",
            ]
        )
        await message.answer("\n".join(lines), reply_markup=admin_menu_keyboard(), parse_mode=None)

    async def send_admin_csv_files(message: Message) -> None:
        async with SessionLocal() as session:
            user_rows = await UserEventRepository.user_activity_rows(session, limit=1000)
            button_stats = await UserEventRepository.top_events(
                session,
                ["reply_button", "inline_button", "command"],
                since=None,
                limit=1000,
            )

        users_csv = StringIO()
        writer = csv.writer(users_csv)
        writer.writerow(
            [
                "telegram_id",
                "username",
                "full_name",
                "role",
                "created_at_utc",
                "last_activity_utc",
                "questions_count",
                "button_events_count",
            ]
        )
        for row in user_rows:
            writer.writerow(
                [
                    row.telegram_id,
                    row.username or "",
                    row.full_name or "",
                    row.role,
                    _format_admin_datetime(row.created_at),
                    _format_admin_datetime(row.last_event_at),
                    row.messages_count,
                    row.button_events_count,
                ]
            )

        buttons_csv = StringIO()
        writer = csv.writer(buttons_csv)
        writer.writerow(["event_type", "event_name", "count"])
        for stat in button_stats:
            writer.writerow([stat.event_type, stat.event_name, stat.count])

        await message.answer_document(
            BufferedInputFile(users_csv.getvalue().encode("utf-8-sig"), filename="ll_bot_users.csv"),
            caption="Пользователи и активность.",
        )
        await message.answer_document(
            BufferedInputFile(buttons_csv.getvalue().encode("utf-8-sig"), filename="ll_bot_buttons.csv"),
            caption="Клики по кнопкам и команды.",
            reply_markup=admin_status_keyboard(),
        )

    @router.callback_query(F.data == "admin:export_csv")
    async def admin_export_csv_callback(callback: CallbackQuery) -> None:
        if not is_admin_user_id(callback.from_user.id):
            await callback.answer("Эта кнопка доступна только администратору.", show_alert=True)
            return
        await callback.answer("Готовлю CSV.")
        if callback.message:
            await send_admin_csv_files(callback.message)

    @router.message(Command("export_csv"))
    @router.message(F.text.in_(["Скачать CSV", "Админ: выгрузка CSV"]))
    async def admin_export_csv_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await send_admin_csv_files(message)

    @router.message(F.text.in_(["Расходы OpenAI", "Админ: расходы"]))
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

        openai_embedding_rub = (
            embedding_tokens_total / 1_000_000 * settings.openai_embedding_usd_per_1m * settings.usd_rub_rate
        )

        lines = [
            "Расходы и оценки:",
            "",
            "Инфраструктура:",
            "- бот сейчас работает на Hostinger, не на Yandex VM",
            "- точную стоимость сервера смотри в Hostinger Billing/hPanel",
            "- внутри бота считаем только примерные расходы LLM по сохранённым токенам",
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
            "Важно:",
            "- Это оценка по успешным ответам, сохранённым в БД.",
            "- OCR по презентациям тоже тратит OpenAI, но такие расходы сейчас не всегда попадают в таблицу сообщений.",
            "- Точный счёт OpenAI смотри в кабинете OpenAI.",
        ]
        await message.answer("\n".join(lines), reply_markup=admin_status_keyboard(), parse_mode=None)

    @router.message(F.text.in_(["Состояние бота", "Админ: статус"]))
    async def admin_status_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer("Проверяю БД, LLM и RAG...")
        await message.answer(await build_admin_status_report(), reply_markup=admin_status_keyboard(), parse_mode=None)

    @router.message(Command("upload_ics"))
    @router.message(F.text.in_(["Загрузить ICS", "Техфайл: ICS календаря", "Админ: загрузить ICS"]))
    async def admin_upload_ics_prompt_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.set_state(AdminFlow.waiting_for_notification_ics)
        await message.answer(
            "Пришли файл `.ics`.\n\n"
            "Это технический файл календаря: бот сохранит его отдельно, ИИ на него смотреть не будет.",
            reply_markup=admin_calendar_keyboard(),
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
                reply_markup=admin_calendar_keyboard(),
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
        if message.text in {"Админ: меню", "Админ: уведомления и сообщения"}:
            await state.clear()
            await message.answer(
                "Загрузку ICS отменил.",
                reply_markup=(
                    admin_menu_keyboard()
                    if message.text == "Админ: меню"
                    else admin_notifications_keyboard()
                ),
            )
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
            if key == NOTIFICATION_TEXT_KEY:
                continue
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
                "Контакты поддержки",
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
            "Контакты поддержки": "support_contacts",
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

    @router.message(F.text == "Изменить текст уведомления")
    async def admin_legacy_notification_text_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        await message.answer(
            "Этот старый текст больше не используется в автоматической рассылке.\n\n"
            "Автоуведомления теперь собираются только из расписания событий и дедлайнов домашних заданий.",
            reply_markup=admin_menu_keyboard(),
            parse_mode=None,
        )

    @router.message(AdminFlow.waiting_for_bot_text, F.text)
    async def admin_text_preview_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text in {"Админ: меню", "Главное меню"}:
            await state.clear()
            reply_markup = (
                admin_menu_keyboard()
                if message.text == "Админ: меню"
                else await user_main_menu_for_message(message)
            )
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
                await callback.message.answer(
                    "Редактирование текста отменено.",
                    reply_markup=admin_texts_keyboard(),
                )
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
                reply_markup=admin_texts_keyboard(),
            )

    @router.message(AdminFlow.waiting_for_bot_text_confirm)
    async def admin_text_confirm_waiting_handler(message: Message) -> None:
        await message.answer("Нажми «Сохранить текст» или «Отменить» под предпросмотром.")

    @router.message(F.text == "Главное меню")
    async def main_menu_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer("Выбери действие:", reply_markup=await user_main_menu_for_message(message))

    @router.message(F.text == "Помощь")
    async def help_button_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(
            await get_bot_text("help"),
            reply_markup=await user_main_menu_for_message(message),
            link_preview_options=NO_LINK_PREVIEW,
        )

    @router.message(F.text.in_(["Расписание Лиги Лидеров", "Расписание программы обучения"]))
    async def schedule_handler(message: Message) -> None:
        await ensure_user(message)
        custom_text = await get_bot_text("schedule")
        try:
            await message.answer(
                custom_text,
                reply_markup=await user_main_menu_for_message(message),
                parse_mode="HTML",
                link_preview_options=NO_LINK_PREVIEW,
            )
        except TelegramBadRequest:
            logger.exception("schedule_html_message_failed")
            await message.answer(
                custom_text,
                reply_markup=await user_main_menu_for_message(message),
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
            await callback.message.answer(
                "Не нашёл занятия этого блока.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
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
            await callback.message.answer(
                "Не нашёл это занятие в расписании.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
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
            await callback.message.answer(
                "Не нашёл это занятие в расписании.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
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
                await message.answer(
                    "Уведомления отключены.",
                    reply_markup=await user_main_menu_for_message(message),
                )
                return
            if choice not in NOTIFICATION_TIME_OPTIONS:
                await message.answer("Выбери время кнопкой ниже.", reply_markup=notification_settings_keyboard())
                return

            await UserNotificationSettingRepository.upsert_time(session, user.id, choice)
            await message.answer(
                f"Готово. Уведомления будут приходить в {choice} по московскому времени.\n\n"
                "Пока текст тестовый, позже здесь будут разные уведомления по направлениям программы.",
                reply_markup=await user_main_menu_for_message(message),
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
        await message.answer(
            "Что хочешь открыть?\n\n"
            "Быстрее всего — нажать «Последнее занятие»: там будут материалы, саммари, подкаст и домашка в одном месте.",
            reply_markup=materials_program_keyboard(),
            parse_mode=None,
        )

    @router.callback_query(F.data == "materials:last_lesson")
    async def materials_last_lesson_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message:
            return
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.latest_started_with_content(session, date.today())
        if lesson is None:
            await callback.message.answer(
                "Пока не нашёл прошедших занятий с загруженными материалами.",
                reply_markup=materials_program_keyboard(),
            )
            return
        await send_materials_lesson_card(callback.message, lesson, telegram_user=callback.from_user)

    @router.callback_query(F.data == "materials:choose_lesson")
    async def materials_choose_lesson_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message:
            return
        await send_materials_block_picker(callback.message)

    @router.callback_query(F.data.startswith("materials:block:"))
    async def materials_block_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        block_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lessons = await ProgramLessonRepository.list_by_block(session, block_key)
        if not lessons:
            await callback.message.answer("Пока не нашёл занятия этого блока.", reply_markup=materials_program_keyboard())
            return
        await callback.message.answer(
            f"{lessons[0].block_title}. Выбери занятие:",
            reply_markup=materials_lessons_keyboard(lessons),
            parse_mode=None,
        )

    @router.callback_query(F.data.startswith("materials:lesson:"))
    async def materials_lesson_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        lesson_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие.", reply_markup=materials_program_keyboard())
            return
        await send_materials_lesson_card(callback.message, lesson, telegram_user=callback.from_user)

    @router.callback_query(F.data.startswith("materials:lesson_docs:"))
    async def materials_lesson_docs_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        lesson_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие.", reply_markup=materials_program_keyboard())
            return
        await send_lesson_documents_by_type(callback.message, lesson, doc_type="materials", telegram_user=callback.from_user)

    @router.callback_query(F.data.startswith("materials:lesson_summary:"))
    async def materials_lesson_summary_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        lesson_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие.", reply_markup=materials_program_keyboard())
            return
        await send_lesson_documents_by_type(callback.message, lesson, doc_type="summary", telegram_user=callback.from_user)

    @router.callback_query(F.data.startswith("materials:lesson_podcasts:"))
    async def materials_lesson_podcasts_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        lesson_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие.", reply_markup=materials_program_keyboard())
            return
        await send_lesson_media_by_type(callback.message, lesson, media_type="podcast")

    @router.callback_query(F.data.startswith("materials:lesson_video:"))
    async def materials_lesson_video_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        lesson_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие.", reply_markup=materials_program_keyboard())
            return
        await send_lesson_media_by_type(callback.message, lesson, media_type="video")

    @router.callback_query(F.data.startswith("materials:lesson_homework:"))
    async def materials_lesson_homework_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return
        lesson_key = callback.data.split(":")[-1]
        async with SessionLocal() as session:
            lesson = await ProgramLessonRepository.get_by_key(session, lesson_key)
            if lesson is None:
                homeworks = []
            else:
                homeworks = await HomeworkRepository.list_by_lesson(
                    session=session,
                    lesson_key=lesson.lesson_key,
                    lesson_date=lesson.date_start,
                    limit=20,
                )
        if lesson is None:
            await callback.message.answer("Не нашёл это занятие.", reply_markup=materials_program_keyboard())
            return
        archived_count = len(archived_homeworks(homeworks))
        homeworks = current_homeworks(homeworks)
        if not homeworks:
            archive_hint = " Старые задания можно посмотреть через «Домашние задания» -> «Архив ДЗ»." if archived_count else ""
            await callback.message.answer(
                f"Актуальное домашнее задание по этому занятию пока не добавлено.{archive_hint}",
                reply_markup=materials_program_keyboard(),
            )
            return
        if len(homeworks) == 1:
            await send_homework_item(callback.message, homeworks[0].id)
            return
        lines = [f"Домашние задания: {lesson.lesson_title}", ""]
        for homework in homeworks[:20]:
            deadline_text = f"; срок сдачи: {homework_deadline_label(homework)}" if homework.deadline_date else ""
            lines.append(f"- {homework.title}{deadline_text}")
        lines.extend(["", "Выбери задание кнопкой ниже."])
        await callback.message.answer(
            "\n".join(lines),
            reply_markup=homework_list_keyboard(homeworks, include_archive=bool(archived_count)),
            parse_mode=None,
        )

    @router.callback_query(F.data == "materials:all")
    async def materials_all_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_materials_list(
                callback.message,
                telegram_user=callback.from_user,
                title="Все материалы программы",
            )

    @router.callback_query(F.data == "materials:records")
    async def materials_records_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await callback.message.answer("Выбери занятие, по которому нужны материалы или записи.")
            await send_materials_block_picker(callback.message)

    @router.callback_query(F.data == "materials:docs")
    async def materials_docs_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if callback.message:
            await send_materials_list(
                callback.message,
                telegram_user=callback.from_user,
                title="Текстовые материалы программы",
            )

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
        user = await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message:
            return
        async with SessionLocal() as session:
            summaries = await DocumentRepository.list_visible_by_material_type(
                session=session,
                user_id=user.id,
                material_type="summary",
                limit=20,
            )
        await send_summary_documents(callback.message, summaries)
        await state.clear()

    @router.callback_query(F.data.startswith("summary:send:"))
    async def summary_send_callback_handler(callback: CallbackQuery) -> None:
        user = await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return

        try:
            document_id = int(callback.data.split(":")[-1])
        except ValueError:
            await callback.message.answer("Не понял, какое саммари нужно открыть.", reply_markup=materials_program_keyboard())
            return

        async with SessionLocal() as session:
            document = await DocumentRepository.get_visible_by_id(session, user.id, document_id)

        if document is None or document.material_type != "summary":
            await callback.message.answer(
                "Не нашёл это саммари или оно больше недоступно. Попробуй открыть раздел материалов ещё раз.",
                reply_markup=materials_program_keyboard(),
            )
            return

        await send_summary_document_text(callback.message, document)

    @router.callback_query(F.data.startswith("document:send:"))
    async def document_send_callback_handler(callback: CallbackQuery) -> None:
        user = await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return

        try:
            document_id = int(callback.data.split(":")[-1])
        except ValueError:
            await callback.message.answer(
                "Не понял, какой материал нужно отправить.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
            return

        async with SessionLocal() as session:
            document = await DocumentRepository.get_visible_by_id(session, user.id, document_id)

        if document is None:
            await callback.message.answer(
                "Не нашёл этот материал или он больше недоступен. Попробуй открыть раздел материалов ещё раз.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
            return

        await send_document_original(callback.message, document)

    @router.callback_query(F.data.startswith("media:"))
    async def media_send_callback_handler(callback: CallbackQuery) -> None:
        await upsert_telegram_user(callback.from_user)
        await callback.answer()
        if not callback.message or not callback.data:
            return

        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.message.answer(
                "Не понял, какой файл нужно отправить.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
            return
        _, media_type, media_id_raw = parts
        try:
            media_id = int(media_id_raw)
        except ValueError:
            await callback.message.answer(
                "Не понял номер файла.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
            return

        async with SessionLocal() as session:
            media = await ProgramMediaRepository.get_by_id(session, media_id)

        if media is None or media.media_type != media_type:
            await callback.message.answer(
                "Этот файл не найден. Попробуй открыть раздел материалов ещё раз.",
                reply_markup=await user_main_menu_for_callback(callback),
            )
            return

        await send_media_asset(callback.message, media)
        await callback.message.answer(
            "Если хочешь продолжить, выбери действие:",
            reply_markup=await user_main_menu_for_callback(callback),
        )

    @router.message(F.text == "Сезон 1. Бизнес-консалтинг")
    async def materials_season_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(
            "Что хочешь открыть по сезону «Бизнес-консалтинг»?",
            reply_markup=materials_program_keyboard(),
            parse_mode=None,
        )

    @router.message(F.text == "Записи и материалы занятий")
    async def materials_records_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer("Выбери занятие, по которому нужны материалы или записи.")
        await send_materials_block_picker(message)

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
        await message.answer(
            "После просмотра можно вернуться в главное меню.",
            reply_markup=await user_main_menu_for_message(message),
        )

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
        user = await ensure_user(message)
        async with SessionLocal() as session:
            summaries = await DocumentRepository.list_visible_by_material_type(
                session=session,
                user_id=user.id,
                material_type="summary",
                limit=20,
            )
        await send_summary_documents(message, summaries)
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
        await message.answer(
            PROJECT_HELP_PLACEHOLDER_TEXT,
            reply_markup=await user_main_menu_for_message(message),
        )

    @router.message(UserFlow.waiting_for_training_question, F.text)
    async def training_question_input_handler(message: Message, state: FSMContext) -> None:
        if await answer_direct_question_if_supported(message, message.text, state):
            await state.clear()
            return
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
        if await answer_direct_question_if_supported(message, message.text, state):
            await state.clear()
            return
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
        if await answer_direct_question_if_supported(message, message.text, state):
            await state.clear()
            return
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
                    f"контекст: {homework_lesson_label(homework)}",
                ]
                if homework.deadline_date:
                    block_lines.append(f"срок сдачи: {homework_deadline_label(homework)}")
                description = homework_description_for_user(homework.description)
                if description:
                    block_lines.append(f"описание: {description}")
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
            "Не упоминай дату открытия домашнего задания: пользователю важен только срок сдачи. "
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
        if await answer_direct_question_if_supported(message, message.text, state):
            await state.clear()
            return
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
        if await answer_direct_question_if_supported(message, message.text, state):
            await state.clear()
            return
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

    @router.message(AdminFlow.waiting_for_global_file, F.text)
    async def admin_text_material_input_handler(message: Message, state: FSMContext) -> None:
        user, session = await get_user_and_session(message)
        processing_message: Message | None = None
        try:
            if message.from_user.id not in container.settings.admin_ids:
                await message.answer("Эта команда доступна только администратору.")
                await state.clear()
                return
            if message.text == "Админ: меню":
                await state.clear()
                await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())
                return

            state_data = await state.get_data()
            material_type = state_data.get("material_type")
            if material_type not in {"homework", "summary"}:
                await message.answer("Нужен именно файл. Пришли PDF, DOCX, PPTX или TXT.")
                return

            material_text = (message.text or "").strip()
            if not material_text:
                await message.answer("Пришли текст или файл PDF/DOCX/PPTX/TXT.")
                return

            processing_message = await message.answer(random.choice(FILE_PROCESSING_MESSAGES))

            module_number = state_data.get("material_module_number")
            season_title = state_data.get("material_season_title")
            module_title = state_data.get("material_module_title")
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

            moodle_url = state_data.get("homework_moodle_url")
            deadline_date_raw = state_data.get("homework_deadline_date")
            deadline_date = date.fromisoformat(deadline_date_raw) if deadline_date_raw else None
            homework_title = None
            homework_description = None
            if material_type == "homework":
                document_title, homework_description = split_homework_title_and_description(
                    material_text,
                    module_number=module_number,
                    module_title=module_title,
                    lesson_date=lesson_date,
                )
                homework_title = document_title
            else:
                document_title, material_text = split_summary_title_and_text(
                    material_text,
                    module_number=module_number,
                    module_title=module_title,
                    lesson_date=lesson_date,
                )
            tags = build_content_tags(
                lesson_key=lesson_key,
                module_number=module_number,
                lesson_date=lesson_date,
                season_title=season_title,
                material_type=material_type,
            )

            saved = await save_text_material_as_upload(material_text, lesson_key, material_type)
            indexed_document = await container.document_service.create_and_index_document(
                session=session,
                title=document_title,
                saved_upload=saved,
                visibility="global",
                owner_user_id=user.id,
                telegram_file_id=None,
                module_number=module_number,
                module_title=module_title,
                lesson_key=lesson_key,
                lesson_date=lesson_date,
                material_type=material_type,
                tags=tags,
            )

            module_text = module_title or (f"урок/модуль {module_number}" if module_number else "общий материал")
            if material_type == "homework":
                homework = await HomeworkRepository.create(
                    session=session,
                    title=homework_title or document_title,
                    description=homework_description or material_text,
                    document_id=indexed_document.id,
                    moodle_url=moodle_url,
                    module_number=module_number,
                    module_title=module_title,
                    lesson_key=lesson_key,
                    lesson_date=lesson_date,
                    deadline_date=deadline_date,
                    created_by_user_id=user.id,
                )
                await message.answer(
                    "Домашнее задание сохранено и обработано.\n\n"
                    f"- id материала: {indexed_document.id}\n"
                    f"- домашнее задание id: {homework.id}\n"
                    f"- название: {homework.title}\n"
                    f"- привязка: {module_text}\n"
                    f"- дата занятия: {format_lesson_date(lesson_date)}\n"
                    f"- срок сдачи: {format_lesson_date(deadline_date)}\n"
                    f"- ссылка: {moodle_url or 'без ссылки'}\n\n"
                    "Теперь участники увидят текст задания в разделе «Домашние задания», а ИИ сможет отвечать по нему.",
                    reply_markup=admin_menu_keyboard(),
                    parse_mode=None,
                )
            else:
                await message.answer(
                    "Саммари сохранено и обработано.\n\n"
                    f"- id материала: {indexed_document.id}\n"
                    f"- название: {indexed_document.title}\n"
                    f"- привязка: {module_text}\n"
                    f"- дата занятия: {format_lesson_date(lesson_date)}\n\n"
                    "Теперь участники смогут открыть его в разделе материалов, а ИИ будет учитывать его в ответах.",
                    reply_markup=admin_menu_keyboard(),
                    parse_mode=None,
                )
            await state.clear()
        except Exception as exc:
            logger.exception("text_material_upload_failed")
            await ErrorRepository.create(session, context="text_material_upload", error_text=str(exc), user_id=user.id)
            await message.answer("Не получилось сохранить материал. Попробуй ещё раз или пришли файл.")
        finally:
            await _delete_message_safely(processing_message)
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
            deadline_date_raw = state_data.get("homework_deadline_date")
            deadline_date = date.fromisoformat(deadline_date_raw) if deadline_date_raw else None
            document_title = document.file_name.rsplit(".", 1)[0]
            homework_title = document_title
            homework_description = (message.caption or "").strip() or None
            if material_type == "homework":
                homework_title, homework_description = split_homework_title_and_description(
                    message.caption,
                    module_number=module_number,
                    module_title=module_title,
                    lesson_date=lesson_date,
                    fallback_title=default_homework_title(module_number, module_title, lesson_date),
                )
                document_title = homework_title
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
                title=document_title,
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
                    title=homework_title,
                    description=homework_description,
                    document_id=indexed_document.id,
                    moodle_url=moodle_url,
                    module_number=module_number,
                    module_title=module_title,
                    lesson_key=lesson_key,
                    lesson_date=lesson_date,
                    deadline_date=deadline_date,
                    created_by_user_id=user.id,
                )
            module_text = f"урок/модуль {module_number}" if module_number else "общий материал"
            type_text = material_type or "другое"
            homework_line = ""
            link_line = ""
            if homework is not None:
                homework_line = f"- домашнее задание id: {homework.id}\n"
                homework_line += f"- название ДЗ: {homework.title}\n"
                link_line = f"- ссылка: {moodle_url or 'без ссылки'}\n"
                link_line += f"- дедлайн сдачи: {format_lesson_date(deadline_date)}\n"
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
                reply_markup=await user_main_menu_for_message(message),
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
    async def waiting_file_but_not_document_handler(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state == AdminFlow.waiting_for_global_file.state:
            state_data = await state.get_data()
            if state_data.get("material_type") == "homework":
                await message.answer("Пришли текст домашнего задания обычным сообщением или файл PDF/DOCX/PPTX/TXT.")
                return
        await message.answer("Нужен именно файл. Пришли PDF, DOCX, PPTX или TXT.")

    @router.callback_query(F.data.startswith("bot_feedback:score:"))
    async def bot_feedback_score_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await upsert_telegram_user(callback.from_user)
        if not callback.message or not callback.data:
            await callback.answer()
            return
        try:
            _, _, response_id_raw, score_raw = callback.data.split(":")
            response_id = int(response_id_raw)
            score = int(score_raw)
        except (ValueError, TypeError):
            await callback.answer("Не понял оценку.", show_alert=True)
            return
        if score < 1 or score > 5:
            await callback.answer("Оценка должна быть от 1 до 5.", show_alert=True)
            return

        user = await upsert_telegram_user(callback.from_user)
        async with SessionLocal() as session:
            response = await BotFeedbackRepository.set_score(session, response_id, user.id, score)
        if response is None:
            await callback.answer("Опрос не найден. Открой ссылку ещё раз.", show_alert=True)
            return

        await state.set_state(UserFlow.waiting_for_bot_feedback_useful)
        await state.update_data(bot_feedback_response_id=response_id)
        await callback.answer("Спасибо!")
        await callback.message.answer(
            "Что в боте уже удобно или полезно?\n\n"
            "Можно ответить текстом или голосовым.",
            parse_mode=None,
        )

    @router.message(UserFlow.waiting_for_bot_feedback_score)
    async def bot_feedback_score_text_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        if message.text == "Главное меню":
            await state.clear()
            await message.answer(
                "Опрос по боту отменён. Вернул в главное меню.",
                reply_markup=await user_main_menu_for_message(message),
            )
            return
        score_raw = (message.text or "").strip()
        if not score_raw.isdigit():
            await message.answer("Поставь оценку кнопкой или напиши цифру от 1 до 5.")
            return
        score = int(score_raw)
        if score < 1 or score > 5:
            await message.answer("Оценка должна быть от 1 до 5.")
            return

        data = await state.get_data()
        response_id = int(data.get("bot_feedback_response_id") or 0)
        user = await ensure_user(message)
        async with SessionLocal() as session:
            response = await BotFeedbackRepository.set_score(session, response_id, user.id, score)
        if response is None:
            await start_bot_feedback_flow(message, state)
            return
        await state.set_state(UserFlow.waiting_for_bot_feedback_useful)
        await message.answer(
            "Что в боте уже удобно или полезно?\n\n"
            "Можно ответить текстом или голосовым.",
            parse_mode=None,
        )

    @router.message(UserFlow.waiting_for_bot_feedback_useful)
    @router.message(UserFlow.waiting_for_bot_feedback_improve)
    @router.message(UserFlow.waiting_for_bot_feedback_missing)
    async def bot_feedback_open_answer_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        if message.text == "Главное меню":
            await state.clear()
            await message.answer(
                "Опрос по боту отменён. Вернул в главное меню.",
                reply_markup=await user_main_menu_for_message(message),
            )
            return

        answer_text = await bot_feedback_message_text(message)
        if not answer_text:
            return

        current_state = await state.get_state()
        data = await state.get_data()
        response_id = int(data.get("bot_feedback_response_id") or 0)
        user = await ensure_user(message)

        if current_state == UserFlow.waiting_for_bot_feedback_useful.state:
            field_name = "useful_text"
            next_state = UserFlow.waiting_for_bot_feedback_improve
            next_question = "Что стоит улучшить в боте?"
            complete = False
        elif current_state == UserFlow.waiting_for_bot_feedback_improve.state:
            field_name = "improvement_text"
            next_state = UserFlow.waiting_for_bot_feedback_missing
            next_question = "Какой функции тебе не хватает?"
            complete = False
        else:
            field_name = "missing_feature_text"
            next_state = None
            next_question = ""
            complete = True

        async with SessionLocal() as session:
            response = await BotFeedbackRepository.set_answer(
                session=session,
                response_id=response_id,
                user_id=user.id,
                field_name=field_name,
                value=answer_text,
                complete=complete,
            )
        if response is None:
            await start_bot_feedback_flow(message, state)
            return

        if complete:
            await state.clear()
            await message.answer(
                "Спасибо за обратную связь о боте. Мы правда читаем такие ответы и будем докручивать помощника под ваши сценарии.",
                reply_markup=await user_main_menu_for_message(message),
                parse_mode=None,
            )
        else:
            await state.set_state(next_state)
            await message.answer(f"{next_question}\n\nМожно ответить текстом или голосовым.", parse_mode=None)

    @router.message(F.voice)
    async def voice_question_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        voice = message.voice
        if voice.duration > container.settings.max_voice_duration_seconds:
            await message.answer(
                f"Голосовое слишком длинное. Максимум "
                f"{container.settings.max_voice_duration_seconds // 60} минуты."
            )
            return
        if voice.file_size and voice.file_size > container.settings.max_voice_size_bytes:
            await message.answer(
                f"Голосовое слишком большое. Максимум {container.settings.max_voice_size_mb} МБ."
            )
            return
        if not container.transcription_service.enabled:
            await message.answer(
                "Голосовые вопросы пока не подключены. Напиши вопрос текстом, пожалуйста."
            )
            return

        processing_message = await message.answer("Расшифровываю голосовое сообщение...")
        try:
            buffer = BytesIO()
            await message.bot.download(voice.file_id, destination=buffer)
            transcription = await container.transcription_service.transcribe(
                buffer.getvalue(),
                filename="voice.ogg",
                mime_type=voice.mime_type or "audio/ogg",
            )
            question = transcription.text
            await message.answer(f"Распознал вопрос:\n{question}", parse_mode=None)

            current_state = await state.get_state()
            if current_state != UserFlow.waiting_for_homework_help_question.state:
                if await answer_direct_question_if_supported(message, question, state):
                    await state.clear()
                    return
                structured_allowed = True
                if current_state == UserFlow.waiting_for_categorized_question.state:
                    state_data = await state.get_data()
                    structured_allowed = state_data.get("question_section") != "technical"
                if structured_allowed and await answer_structured_lesson_question_if_supported(message, question, state):
                    await state.clear()
                    return

            if current_state == UserFlow.waiting_for_categorized_question.state:
                data = await state.get_data()
                section = data.get("question_section")
                if section != "technical" and looks_like_technical_question(question):
                    section = "technical"
                mode, extra_context, force_rag = question_section_context(section)
                if section != "technical" and looks_like_schedule_question(question):
                    schedule_context = await build_schedule_context_for_llm()
                    extra_context = f"{extra_context or ''}\n\n{schedule_context}".strip()
                    if should_send_schedule_image_for_question(question):
                        await send_schedule_image(message)
                await answer_question(
                    message,
                    question,
                    state,
                    mode=mode,
                    force_rag=force_rag,
                    extra_context=extra_context,
                )
            elif current_state == UserFlow.waiting_for_file_question.state:
                await answer_question(message, question, state, mode="user_file_qa")
            elif current_state == UserFlow.waiting_for_project_help_question.state:
                await answer_question(message, question, state, mode="project_help")
            elif current_state == UserFlow.waiting_for_homework_help_question.state:
                await answer_question(message, question, state, mode="homework_help")
            else:
                extra_context = None
                if looks_like_schedule_question(question):
                    extra_context = await build_schedule_context_for_llm()
                    if should_send_schedule_image_for_question(question):
                        await send_schedule_image(message)
                await answer_question(
                    message,
                    question,
                    state,
                    mode="voice_question",
                    extra_context=extra_context,
                )
            await state.clear()
        except Exception as exc:
            logger.exception("voice_question_transcription_failed")
            user = await ensure_user(message)
            async with SessionLocal() as session:
                await ErrorRepository.create(
                    session,
                    context="voice_question_transcription",
                    error_text=str(exc),
                    user_id=user.id,
                )
            await message.answer(
                "Не получилось расшифровать голосовое. Попробуй ещё раз или напиши вопрос текстом."
            )
        finally:
            await _delete_message_safely(processing_message)

    @router.message(F.text)
    async def fallback_text_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        if await answer_direct_question_if_supported(message, message.text, state):
            return
        material_question = parse_material_question(message.text)
        if material_question is not None:
            document_id, question = material_question
            await answer_material_question(message, document_id, question, state)
            return
        if await answer_structured_lesson_question_if_supported(message, message.text, state):
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
        extra_context = None
        if looks_like_schedule_question(message.text):
            extra_context = await build_schedule_context_for_llm()
            if should_send_schedule_image_for_question(message.text):
                await send_schedule_image(message)
        await answer_question(message, message.text, state, mode="free_text", extra_context=extra_context)

    return router
