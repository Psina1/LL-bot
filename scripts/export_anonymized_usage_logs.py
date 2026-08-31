from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db.session import SessionLocal


MOSCOW = ZoneInfo("Europe/Moscow")
SYSTEM_MESSAGE_MODES = {"materials_summary", "materials_podcast_summary"}


async def fetch(sql: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        result = await session.execute(text(sql))
        return [dict(row) for row in result.mappings().all()]


def iso_msk(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(MOSCOW).isoformat()


def participant_section(event_type: str, name: str) -> str:
    if name.startswith("Обратная связь:"):
        return "Обратная связь по занятиям"
    if name.startswith("Материалы:") or name == "Материалы программы":
        return "Материалы"
    if name.startswith("Домашние задания:") or name == "Домашние задания":
        return "Домашние задания"
    if name.startswith("Расписание:") or name == "Расписание Лиги Лидеров":
        return "Расписание"
    if (
        name.startswith("Уведомления:")
        or name.startswith("Настройки уведомлений")
        or name.startswith("Старт: выбор времени")
    ):
        return "Настройки уведомлений"
    if name in {"Задать вопрос", "Вопрос по программе", "Технический вопрос", "Другое"}:
        return "Вход в вопросы"
    if name == "Кабинет руководителя":
        return "Кабинет руководителя"
    if name == "Главное меню":
        return "Навигация"
    if event_type == "command":
        return "Команды"
    return "Прочее"


def admin_section(event_type: str, name: str) -> str:
    if name.startswith("Админ: обратная связь") or name.startswith("Обратная связь:"):
        return "Обратная связь"
    if (
        name.startswith("Материал:")
        or name.startswith("Тип:")
        or name.startswith("Медиа:")
        or name.startswith("Добавить ")
        or name.startswith("Управление материалами")
        or name.startswith("Библиотека материалов")
    ):
        return "Загрузка материалов"
    if (
        name.startswith("Уведомления:")
        or name.startswith("Админ: уведомления")
        or name.startswith("Админ: напоминание")
        or name.startswith("Ближайшие уведомления")
    ):
        return "Уведомления"
    if (
        name.startswith("Статус")
        or name.startswith("Активность участников")
        or name.startswith("Админ: аналитика")
        or name.startswith("Админ: статистика")
        or name.startswith("Админ: статус")
        or name.startswith("Скачать CSV")
    ):
        return "Аналитика"
    if name == "Кабинет руководителя":
        return "Кабинет руководителя"
    if name.startswith("Админ:") or name == "Главное меню":
        return "Админ-навигация"
    if event_type == "command":
        return "Команды"
    return participant_section(event_type, name)


def answer_outcome(answer: str) -> str:
    normalized = answer.lower()
    if "техническ" in normalized and "ошибк" in normalized:
        return "technical_error"
    if "не получилось получить ответ" in normalized:
        return "technical_error"
    if "не нашёл точного ответа" in normalized or "не нашел точного ответа" in normalized:
        return "no_answer"
    if "ответ не найден" in normalized:
        return "no_answer"
    return "answered"


def serialise_counter(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common()]


async def build_export(output_dir: Path) -> None:
    events = await fetch(
        """
        SELECT e.telegram_id, e.event_type, e.event_name, e.created_at,
               coalesce(u.role::text, 'unknown') AS actor_type
        FROM user_events e
        LEFT JOIN users u ON u.telegram_id=e.telegram_id
        ORDER BY e.created_at, e.id
        """
    )
    questions = await fetch(
        """
        SELECT u.telegram_id, u.role::text AS actor_type,
               m.mode, m.answer, m.created_at
        FROM messages m
        JOIN users u ON u.id=m.user_id
        WHERE m.mode NOT IN ('materials_summary', 'materials_podcast_summary')
        ORDER BY m.created_at, m.id
        """
    )

    actor_ids: dict[tuple[str, int], str] = {}
    actor_counters: Counter[str] = Counter()
    for row in events + questions:
        actor_type = str(row["actor_type"] or "unknown")
        telegram_id = int(row["telegram_id"])
        key = (actor_type, telegram_id)
        if key not in actor_ids:
            actor_counters[actor_type] += 1
            prefix = {"user": "P", "admin": "A"}.get(actor_type, "U")
            actor_ids[key] = f"{prefix}{actor_counters[actor_type]:03d}"

    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "events_anonymized.jsonl"
    with events_path.open("w", encoding="utf-8") as stream:
        for row in events:
            actor_type = str(row["actor_type"] or "unknown")
            record = {
                "timestamp_msk": iso_msk(row["created_at"]),
                "actor_type": actor_type,
                "anonymous_actor": actor_ids[(actor_type, int(row["telegram_id"]))],
                "event_type": row["event_type"],
                "event_name": row["event_name"],
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    questions_path = output_dir / "questions_metadata_anonymized.jsonl"
    with questions_path.open("w", encoding="utf-8") as stream:
        for row in questions:
            actor_type = str(row["actor_type"] or "unknown")
            record = {
                "timestamp_msk": iso_msk(row["created_at"]),
                "actor_type": actor_type,
                "anonymous_actor": actor_ids[(actor_type, int(row["telegram_id"]))],
                "mode": row["mode"],
                "outcome": answer_outcome(row["answer"] or ""),
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    participant_events = [row for row in events if row["actor_type"] == "user"]
    admin_events = [row for row in events if row["actor_type"] == "admin"]
    participant_questions = [row for row in questions if row["actor_type"] == "user"]

    participant_sections: Counter[str] = Counter()
    participant_actions: Counter[str] = Counter()
    participant_section_actors: dict[str, set[int]] = defaultdict(set)
    participant_action_actors: dict[str, set[int]] = defaultdict(set)
    for row in participant_events:
        section = participant_section(row["event_type"], row["event_name"])
        participant_sections[section] += 1
        participant_actions[row["event_name"]] += 1
        participant_section_actors[section].add(int(row["telegram_id"]))
        participant_action_actors[row["event_name"]].add(int(row["telegram_id"]))

    admin_sections: Counter[str] = Counter()
    admin_section_actors: dict[str, set[int]] = defaultdict(set)
    for row in admin_events:
        section = admin_section(row["event_type"], row["event_name"])
        admin_sections[section] += 1
        admin_section_actors[section].add(int(row["telegram_id"]))

    transitions: Counter[tuple[str, str]] = Counter()
    events_by_actor: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in participant_events:
        events_by_actor[int(row["telegram_id"])].append(row)
    for actor_events in events_by_actor.values():
        for current, following in zip(actor_events, actor_events[1:]):
            if following["created_at"] - current["created_at"] <= timedelta(minutes=30):
                transitions[(current["event_name"], following["event_name"])] += 1

    question_modes: Counter[str] = Counter()
    question_outcomes: Counter[str] = Counter()
    question_mode_outcomes: Counter[tuple[str, str]] = Counter()
    for row in participant_questions:
        outcome = answer_outcome(row["answer"] or "")
        question_modes[row["mode"]] += 1
        question_outcomes[outcome] += 1
        question_mode_outcomes[(row["mode"], outcome)] += 1

    monthly: dict[str, dict[str, Any]] = defaultdict(lambda: {"actions": 0, "actors": set()})
    for row in participant_events:
        month = row["created_at"].astimezone(MOSCOW).strftime("%Y-%m")
        monthly[month]["actions"] += 1
        monthly[month]["actors"].add(int(row["telegram_id"]))

    first_event = min((row["created_at"] for row in events), default=None)
    last_event = max((row["created_at"] for row in events), default=None)
    summary = {
        "generated_at_msk": datetime.now(MOSCOW).isoformat(),
        "period": {
            "first_event_msk": iso_msk(first_event) if first_event else None,
            "last_event_msk": iso_msk(last_event) if last_event else None,
        },
        "privacy": {
            "contains_names": False,
            "contains_telegram_ids": False,
            "contains_usernames": False,
            "contains_question_texts": False,
            "contains_answer_texts": False,
            "anonymous_actor_ids_are_export_local": True,
        },
        "totals": {
            "events": len(events),
            "participant_events": len(participant_events),
            "admin_events": len(admin_events),
            "active_participants": len(events_by_actor),
            "active_admins": len({int(row["telegram_id"]) for row in admin_events}),
            "participant_questions": len(participant_questions),
            "participants_who_asked": len({int(row["telegram_id"]) for row in participant_questions}),
        },
        "participant_sections": [
            {
                "name": name,
                "actions": count,
                "unique_actors": len(participant_section_actors[name]),
            }
            for name, count in participant_sections.most_common()
        ],
        "participant_top_actions": [
            {
                "name": name,
                "actions": count,
                "unique_actors": len(participant_action_actors[name]),
            }
            for name, count in participant_actions.most_common(60)
        ],
        "participant_top_transitions": [
            {"from": pair[0], "to": pair[1], "count": count}
            for pair, count in transitions.most_common(60)
        ],
        "participant_question_modes": serialise_counter(question_modes),
        "participant_question_outcomes": serialise_counter(question_outcomes),
        "participant_question_mode_outcomes": [
            {"mode": pair[0], "outcome": pair[1], "count": count}
            for pair, count in question_mode_outcomes.most_common()
        ],
        "admin_sections": [
            {
                "name": name,
                "actions": count,
                "unique_actors": len(admin_section_actors[name]),
            }
            for name, count in admin_sections.most_common()
        ],
        "participant_monthly_activity": [
            {
                "month": month,
                "actions": bucket["actions"],
                "active_actors": len(bucket["actors"]),
            }
            for month, bucket in sorted(monthly.items())
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    participant_total = len(participant_events)
    feedback_actions = participant_sections.get("Обратная связь по занятиям", 0)
    self_service_actions = max(participant_total - feedback_actions, 0)
    materials_actions = participant_sections.get("Материалы", 0)
    homework_actions = participant_sections.get("Домашние задания", 0)
    answered_questions = question_outcomes.get("answered", 0)
    unsuccessful_questions = (
        question_outcomes.get("no_answer", 0)
        + question_outcomes.get("technical_error", 0)
    )
    upload_admins = len(admin_section_actors.get("Загрузка материалов", set()))
    analytics_admins = len(admin_section_actors.get("Аналитика", set()))

    def percent(value: int, total: int) -> str:
        if total <= 0:
            return "0%"
        return f"{value / total:.0%}"

    report_lines = [
        "# Обезличенная аналитика использования бота",
        "",
        f"Период событий: {summary['period']['first_event_msk']} — {summary['period']['last_event_msk']}.",
        "",
        "В выгрузке нет ФИО, Telegram ID, ников, текстов вопросов и текстов ответов. "
        "Обозначения P001/A001 действуют только внутри этой выгрузки.",
        "",
        "## Ключевые наблюдения",
        "",
        f"- {feedback_actions} из {participant_total} действий участников "
        f"({percent(feedback_actions, participant_total)}) относятся к опросам обратной связи. "
        "Их нельзя считать самостоятельным обращением к помощнику.",
        f"- Если исключить опросы, материалы и домашние задания дают "
        f"{materials_actions + homework_actions} из {self_service_actions} действий "
        f"({percent(materials_actions + homework_actions, self_service_actions)}). "
        "Это два главных самостоятельных сценария.",
        f"- Обычным текстом задали {len(participant_questions)} вопросов; "
        f"полезный ответ зафиксирован для {answered_questions}, а без ответа или с ошибкой осталось "
        f"{unsuccessful_questions}. Свободный диалог пока не стал надёжной точкой входа.",
        f"- Загрузкой материалов пользовались {upload_admins} администратора, "
        f"аналитикой — {analytics_admins}. Административные операции сосредоточены у небольшой части команды.",
        "",
        "## Участники: направления использования",
        "",
        "| Раздел | Действия | Уникальные участники |",
        "|---|---:|---:|",
    ]
    report_lines.extend(
        f"| {row['name']} | {row['actions']} | {row['unique_actors']} |"
        for row in summary["participant_sections"]
    )
    report_lines.extend(
        [
            "",
            "## Самые частые действия участников",
            "",
            "| Действие | Количество | Уникальные участники |",
            "|---|---:|---:|",
        ]
    )
    report_lines.extend(
        f"| {row['name']} | {row['actions']} | {row['unique_actors']} |"
        for row in summary["participant_top_actions"][:20]
    )
    report_lines.extend(
        [
            "",
            "## Частые переходы внутри одной сессии",
            "",
            "| Откуда | Куда | Переходы |",
            "|---|---|---:|",
        ]
    )
    report_lines.extend(
        f"| {row['from']} | {row['to']} | {row['count']} |"
        for row in summary["participant_top_transitions"][:20]
    )
    report_lines.extend(
        [
            "",
            "## Вопросы обычным текстом",
            "",
            f"Всего вопросов участников: {summary['totals']['participant_questions']}.",
            f"Участников, задававших вопросы: {summary['totals']['participants_who_asked']}.",
            "",
            "| Результат | Количество |",
            "|---|---:|",
        ]
    )
    outcome_labels = {
        "answered": "Ответ получен",
        "no_answer": "Ответ не найден",
        "technical_error": "Техническая ошибка",
    }
    report_lines.extend(
        f"| {outcome_labels.get(row['name'], row['name'])} | {row['count']} |"
        for row in summary["participant_question_outcomes"]
    )
    report_lines.extend(
        [
            "",
            "## Администраторы: направления использования",
            "",
            "| Раздел | Действия | Уникальные администраторы |",
            "|---|---:|---:|",
        ]
    )
    report_lines.extend(
        f"| {row['name']} | {row['actions']} | {row['unique_actors']} |"
        for row in summary["admin_sections"]
    )
    report_lines.extend(
        [
            "",
            "## Ограничения",
            "",
            "- Журнал `user_events` фиксирует команды и нажатия кнопок, но не произвольный текст.",
            "- Для текстовых вопросов экспортируются только режим и результат ответа.",
            "- Нажатия в опросах обратной связи считаются отдельно от самостоятельного поиска материалов.",
            "",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(report_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(build_export(args.output))


if __name__ == "__main__":
    main()
