from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import text

from app.bot.keyboards.reply import (
    admin_material_module_keyboard,
    admin_material_season_keyboard,
    admin_material_type_keyboard,
    admin_menu_keyboard,
    admin_text_preview_keyboard,
    admin_texts_keyboard,
    feedback_keyboard,
    feedback_reason_keyboard,
    homework_menu_keyboard,
    main_menu_keyboard,
    materials_season_keyboard,
    materials_type_keyboard,
    project_context_keyboard,
    project_help_keyboard,
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
)
from app.db.repositories import (
    BotTextRepository,
    DocumentRepository,
    ErrorRepository,
    MessageFeedbackRepository,
    MessageRepository,
    StatsRepository,
    UserRepository,
)
from app.db.session import SessionLocal
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
    "Режу материал на фрагменты...",
    "Складываю файл в личный контекст...",
]


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


async def _delete_message_safely(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramNetworkError):
        return


def build_main_router(container: AppContainer) -> Router:
    router = Router(name="main")

    async def ensure_user(message: Message):
        async with SessionLocal() as session:
            return await UserRepository.upsert_telegram_user(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                is_admin=message.from_user.id in container.settings.admin_ids,
            )

    async def get_user_and_session(message: Message):
        session = SessionLocal()
        user = await UserRepository.upsert_telegram_user(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_admin=message.from_user.id in container.settings.admin_ids,
        )
        return user, session

    def is_admin(message: Message) -> bool:
        return message.from_user.id in container.settings.admin_ids

    def is_admin_user_id(user_id: int) -> bool:
        return user_id in container.settings.admin_ids

    async def get_bot_text(key: str) -> str:
        async with SessionLocal() as session:
            return await BotTextRepository.get_value(session, key, BOT_TEXT_DEFAULTS[key])

    async def require_admin(message: Message) -> bool:
        await ensure_user(message)
        if not is_admin(message):
            await message.answer("Эта команда доступна только администратору.")
            return False
        return True

    async def answer_question(
        message: Message,
        question: str,
        state: FSMContext,
        mode: str = "training_qa",
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
            result = await container.chat_service.answer_question(
                session=session,
                user=user,
                question=question,
                mode=mode,
                force_rag=True,
            )
            await message.answer(result.text, reply_markup=feedback_keyboard(result.message_id))
            await message.answer("Если хочешь продолжить, выбери действие:", reply_markup=main_menu_keyboard())
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

    async def send_materials_list(message: Message) -> None:
        async with SessionLocal() as session:
            modules = await DocumentRepository.list_modules(session)
            docs = await DocumentRepository.list_materials(session, limit=50)

        if modules:
            lines = ["Доступные модули:"]
            for number, title, count in modules:
                lines.append(f"- Модуль {number}: {title or 'Без названия'} ({count} материалов)")
            await message.answer("\n".join(lines), reply_markup=main_menu_keyboard())
            return

        if not docs:
            await message.answer(
                "Материалы программы пока не загружены.\n\n"
                "Как только администратор добавит файлы занятий, я смогу показывать их здесь "
                "и отвечать по ним с источниками.",
                reply_markup=main_menu_keyboard(),
            )
            return

        lines = ["Загруженные материалы:"]
        for doc in docs[:20]:
            status_hint = "готов" if doc.status.value == "ready" else "обрабатывается"
            lines.append(f"- {doc.title} ({status_hint})")
        await message.answer("\n".join(lines), reply_markup=main_menu_keyboard())

    async def send_homework_list(message: Message) -> None:
        async with SessionLocal() as session:
            docs = await DocumentRepository.list_homework_materials(session)
        if not docs:
            await message.answer(
                "Домашние задания пока не найдены в загруженных материалах.\n\n"
                "Когда администратор загрузит файл с домашками или пометит материал как `homework`, "
                "я покажу список заданий здесь.",
                reply_markup=main_menu_keyboard(),
            )
            return

        lines = ["Нашёл материалы по домашним заданиям:"]
        for doc in docs:
            lines.append(f"- {doc.title}")
        await message.answer("\n".join(lines), reply_markup=main_menu_keyboard())

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
                await callback.message.answer("Спасибо! Рад, что ответ был полезен.", reply_markup=main_menu_keyboard())
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
                reply_markup=main_menu_keyboard(),
            )

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer(await get_bot_text("welcome"), reply_markup=main_menu_keyboard(), parse_mode=None)

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(await get_bot_text("help"), reply_markup=main_menu_keyboard(), parse_mode=None)

    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.clear()
        await message.answer("Действие отменено. Вернул в главное меню.", reply_markup=main_menu_keyboard())

    @router.message(Command("admin"))
    @router.message(F.text == "Админ: меню")
    async def admin_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.clear()
        await message.answer(ADMIN_PROMPT, reply_markup=admin_menu_keyboard())

    @router.message(Command("upload_global_material"))
    @router.message(F.text == "Админ: загрузить материал")
    async def admin_upload_command(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        await state.set_state(AdminFlow.waiting_for_material_season)
        await message.answer(
            "Запускаю мастер загрузки материала.\n\n"
            "Шаг 1 из 4: выбери сезон материала.",
            reply_markup=admin_material_season_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_material_season, F.text.in_(["Материал: Сезон 1. Бизнес-консалтинг", "Материал: без сезона"]))
    async def admin_material_season_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        season_title = "Сезон 1. Бизнес-консалтинг" if message.text == "Материал: Сезон 1. Бизнес-консалтинг" else None
        await state.update_data(material_season_title=season_title)
        await state.set_state(AdminFlow.waiting_for_material_module)
        await message.answer("Шаг 2 из 4: выбери модуль.", reply_markup=admin_material_module_keyboard())

    @router.message(AdminFlow.waiting_for_material_season)
    async def admin_material_season_invalid_handler(message: Message) -> None:
        await message.answer("Выбери сезон кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_material_season_keyboard())

    @router.message(AdminFlow.waiting_for_material_module, F.text.startswith("Материал: "))
    async def admin_material_module_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        module_number = None
        module_match = re.search(r"модуль\s+(\d+)", message.text, flags=re.IGNORECASE)
        if module_match:
            module_number = int(module_match.group(1))
        await state.update_data(material_module_number=module_number)
        await state.set_state(AdminFlow.waiting_for_material_type)
        await message.answer("Шаг 3 из 4: выбери тип материала.", reply_markup=admin_material_type_keyboard())

    @router.message(AdminFlow.waiting_for_material_module)
    async def admin_material_module_invalid_handler(message: Message) -> None:
        await message.answer("Выбери модуль кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_material_module_keyboard())

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
        module_text = f"модуль {module_number}" if module_number else "без модуля"
        type_text = message.text.replace("Тип: ", "")
        await state.set_state(AdminFlow.waiting_for_global_file)
        await message.answer(
            "Шаг 4 из 4: пришли файл PDF/DOCX/PPTX/TXT.\n\n"
            f"Будет сохранено так:\n"
            f"- сезон: {season_title}\n"
            f"- модуль: {module_text}\n"
            f"- тип: {type_text}",
            reply_markup=admin_menu_keyboard(),
        )

    @router.message(AdminFlow.waiting_for_material_type)
    async def admin_material_type_invalid_handler(message: Message) -> None:
        await message.answer("Выбери тип материала кнопкой ниже или нажми «Админ: меню».", reply_markup=admin_material_type_keyboard())

    @router.message(Command("list_materials"))
    @router.message(F.text == "Админ: материалы")
    async def list_materials_handler(message: Message) -> None:
        if not await require_admin(message):
            return
        async with SessionLocal() as session:
            docs = await DocumentRepository.list_materials(session, limit=100)
        if not docs:
            await message.answer("Материалы пока не загружены.")
            return

        lines = ["Последние материалы:"]
        for doc in docs[:30]:
            lines.append(
                f"- id={doc.id} | {doc.title} | visibility={doc.visibility.value} | "
                f"module={doc.module_number} | status={doc.status.value}"
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

    @router.message(F.text.in_(["Изменить приветствие", "Изменить помощь", "Изменить расписание"]))
    async def admin_edit_text_prompt_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            return
        mapping = {
            "Изменить приветствие": "welcome",
            "Изменить помощь": "help",
            "Изменить расписание": "schedule",
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
        )

    @router.message(AdminFlow.waiting_for_bot_text, F.text)
    async def admin_text_preview_handler(message: Message, state: FSMContext) -> None:
        if not await require_admin(message):
            await state.clear()
            return
        if message.text in {"Админ: меню", "Главное меню"}:
            await state.clear()
            reply_markup = admin_menu_keyboard() if message.text == "Админ: меню" else main_menu_keyboard()
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

        await state.update_data(pending_bot_text=message.text.strip())
        await state.set_state(AdminFlow.waiting_for_bot_text_confirm)
        await message.answer(
            f"Предпросмотр текста «{BOT_TEXT_LABELS[key]}»:\n\n{message.text.strip()}",
            reply_markup=admin_text_preview_keyboard(),
            parse_mode=None,
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
        await message.answer("Выбери действие:", reply_markup=main_menu_keyboard())

    @router.message(F.text == "Помощь")
    async def help_button_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(await get_bot_text("help"), reply_markup=main_menu_keyboard(), parse_mode=None)

    @router.message(F.text.in_(["Расписание Лиги Лидеров", "Расписание программы обучения"]))
    async def schedule_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(await get_bot_text("schedule"), reply_markup=main_menu_keyboard(), parse_mode=None)

    @router.message(F.text.in_(["Задать вопрос по организации Лиги Лидеров", "Задать вопрос по обучению"]))
    async def ask_training_question_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.set_state(UserFlow.waiting_for_training_question)
        await message.answer("Напиши свой организационный вопрос по программе.")

    @router.message(F.text == "Материалы программы")
    async def materials_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(MATERIALS_SEASON_PROMPT, reply_markup=materials_season_keyboard())

    @router.message(F.text == "Сезон 1. Бизнес-консалтинг")
    async def materials_season_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(MATERIALS_TYPE_PROMPT, reply_markup=materials_type_keyboard())

    @router.message(F.text == "Записи и материалы занятий")
    async def materials_records_handler(message: Message) -> None:
        await ensure_user(message)
        await send_materials_list(message)

    @router.message(F.text == "Подкасты на основе занятий")
    async def materials_podcasts_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await message.answer(PODCASTS_PROMPT)
        await answer_question(
            message,
            "Сделай короткий текстовый подкаст-конспект по материалам занятий сезона 1. "
            "Формат: 5 ключевых мыслей, практический вывод, что попробовать на работе.",
            state,
            mode="materials_podcast_summary",
        )
        await state.clear()

    @router.message(F.text == "Саммари занятий")
    async def materials_summary_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await answer_question(
            message,
            "Сделай краткое саммари занятий сезона 1 по загруженным материалам. "
            "Выдели основные темы, инструменты и что участнику можно применить в проекте.",
            state,
            mode="materials_summary",
        )
        await state.clear()

    @router.message(F.text == "Домашние задания")
    async def homework_handler(message: Message) -> None:
        await ensure_user(message)
        await message.answer(HOMEWORK_MENU_PROMPT, reply_markup=homework_menu_keyboard())

    @router.message(F.text == "Список заданий")
    async def homework_list_handler(message: Message) -> None:
        await ensure_user(message)
        await send_homework_list(message)

    @router.message(F.text == "Помощь с домашкой")
    async def homework_help_prompt_handler(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await state.set_state(UserFlow.waiting_for_homework_help_question)
        await message.answer(HOMEWORK_HELP_PROMPT, reply_markup=homework_menu_keyboard())

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
        await message.answer(PROJECT_HELP_PLACEHOLDER_TEXT, reply_markup=main_menu_keyboard())

    @router.message(UserFlow.waiting_for_training_question, F.text)
    async def training_question_input_handler(message: Message, state: FSMContext) -> None:
        await answer_question(message, message.text, state, mode="training_qa")
        await state.clear()

    @router.message(UserFlow.waiting_for_project_help_question, F.text)
    async def project_help_question_input_handler(message: Message, state: FSMContext) -> None:
        await answer_question(message, message.text, state, mode="project_help")
        await state.clear()

    @router.message(UserFlow.waiting_for_homework_help_question, F.text)
    async def homework_help_question_input_handler(message: Message, state: FSMContext) -> None:
        await answer_question(message, message.text, state, mode="homework_help")
        await state.clear()

    @router.message(UserFlow.waiting_for_file_question, F.text)
    async def file_question_input_handler(message: Message, state: FSMContext) -> None:
        await answer_question(message, message.text, state, mode="user_file_qa")
        await state.clear()

    @router.message(UserFlow.waiting_for_followup, F.text)
    async def followup_input_handler(message: Message, state: FSMContext) -> None:
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
            module_title = caption_metadata.get("module_title")
            if module_title is None and season_title and module_number:
                module_title = f"{season_title}, модуль {module_number}"
            elif module_title is None and season_title:
                module_title = season_title

            material_type_from_state = state_data.get("material_type") if "material_type" in state_data else None
            material_type = material_type_from_state or caption_metadata.get("material_type")
            if material_type is None and "material_type" not in state_data and "домаш" in (document.file_name or "").lower():
                material_type = "homework"

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
                material_type=material_type,
            )
            module_text = f"модуль {module_number}" if module_number else "без модуля"
            type_text = material_type or "другое"
            await message.answer(
                "Материал загружен и обработан.\n\n"
                f"- файл: {document.file_name}\n"
                f"- формат: {extension}\n"
                f"- модуль: {module_text}\n"
                f"- тип: {type_text}\n"
                "- видимость: общий материал программы",
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
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
        except FileValidationError as exc:
            await message.answer(str(exc))
        except Exception as exc:
            logger.exception("user_upload_failed")
            await ErrorRepository.create(session, context="user_upload", error_text=str(exc), user_id=user.id)
            await message.answer("Не получилось обработать файл. Попробуй другой файл или обратись к администратору.")
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
        # Вертикальный срез: любой текстовый вопрос -> LLM -> ответ -> лог в БД.
        await answer_question(message, message.text, state, mode="free_text")

    return router
