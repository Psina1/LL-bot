from __future__ import annotations

import asyncio
from datetime import date
import json
from types import SimpleNamespace

from app.llm.client import ChatResult
from app.services.semantic_dispatcher import (
    build_semantic_plan,
    lesson_catalog_text,
    parse_semantic_plan,
)


def lesson(key: str, day: int, title: str, speaker: str):
    return SimpleNamespace(
        lesson_key=key,
        date_start=date(2026, 7, day),
        season_title="Бизнес",
        block_title="Стратегия",
        lesson_number=1 if day == 1 else 4,
        lesson_title=title,
        speaker=speaker,
    )


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""

    async def chat_completion(self, system_prompt: str, user_prompt: str, temperature: float = 0):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return ChatResult(answer=json.dumps(self.payload, ensure_ascii=False), token_usage=None)


def test_parse_quote_plan_with_card() -> None:
    plan = parse_semantic_plan(
        """```json
        {"action":"rag_answer","lesson_key":"s1_b3_l4","speaker_hint":"Семенов",
         "content_type":null,"include_card":true,"clarification":null,"confidence":0.96}
        ```""",
        {"s1_b3_l1", "s1_b3_l4"},
    )
    assert plan.action == "rag_answer"
    assert plan.lesson_key == "s1_b3_l4"
    assert plan.speaker_hint == "Семенов"
    assert plan.include_card is True
    assert plan.content_types == ()


def test_rejects_hallucinated_lesson_key() -> None:
    plan = parse_semantic_plan(
        '{"action":"rag_answer","lesson_key":"invented","confidence":0.99}',
        {"real"},
    )
    assert plan.action == "fallback"
    assert plan.lesson_key is None


def test_rejects_low_confidence_action() -> None:
    plan = parse_semantic_plan(
        '{"action":"lesson_card","lesson_key":"real","confidence":0.3}',
        {"real"},
    )
    assert plan.action == "fallback"


def test_accepts_named_or_missing_confidence() -> None:
    named = parse_semantic_plan(
        '{"action":"rag_answer","lesson_key":"real","confidence":"high"}',
        {"real"},
    )
    missing = parse_semantic_plan(
        '{"action":"rag_answer","lesson_key":"real"}',
        {"real"},
    )
    assert named.action == "rag_answer"
    assert named.confidence == 0.9
    assert missing.action == "rag_answer"
    assert missing.confidence == 0.75


def test_string_null_values_are_treated_as_empty() -> None:
    plan = parse_semantic_plan(
        '{"action":"rag_answer","lesson_key":"null","speaker_hint":"None","confidence":0.9}',
        {"real"},
    )
    assert plan.action == "rag_answer"
    assert plan.lesson_key is None
    assert plan.speaker_hint is None


def test_parses_multiple_requested_content_types() -> None:
    plan = parse_semantic_plan(
        '{"action":"content_delivery","lesson_key":"real",'
        '"content_types":["video","summary","video"],"confidence":0.9}',
        {"real"},
    )
    assert plan.action == "content_delivery"
    assert plan.content_type == "video"
    assert plan.content_types == ("video", "summary")


def test_catalog_contains_dates_speakers_and_stable_keys() -> None:
    catalog = lesson_catalog_text([lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов")])
    assert "key=s1_b3_l4" in catalog
    assert "date=2026-07-14" in catalog
    assert "speakers=Александр Семенов" in catalog


def test_dispatch_prompt_contains_full_catalog_and_dialog_context() -> None:
    lessons = [
        lesson("s1_b3_l1", 1, "Стратегия как инструмент", "Александр Семенов"),
        lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов"),
    ]
    fake = FakeLLM(
        {
            "action": "rag_answer",
            "lesson_key": "s1_b3_l4",
            "speaker_hint": "Семенов",
            "relative_position": "latest",
            "include_card": True,
            "confidence": 0.95,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="Приведи цитаты Семенова с его последнего занятия",
            lessons=lessons,
            conversation={"conversation_lesson_key": "s1_b3_l1", "last_question": "Что он говорил?"},
            today=date(2026, 9, 14),
        )
    )
    assert plan.lesson_key == "s1_b3_l4"
    assert "последнее занятие Иванова" in fake.system_prompt
    assert "key=s1_b3_l1" in fake.user_prompt
    assert "key=s1_b3_l4" in fake.user_prompt
    assert "last_question=Что он говорил?" in fake.user_prompt


def test_dispatch_repairs_wrong_lesson_for_latest_speaker_request() -> None:
    lessons = [
        lesson("s1_b3_l1", 1, "Стратегия как инструмент", "Александр Семенов"),
        lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов"),
        lesson("s1_b4_l4", 20, "Финансовый практикум", "Ю. Макарова"),
    ]
    fake = FakeLLM(
        {
            "action": "rag_answer",
            "lesson_key": "s1_b4_l4",
            "speaker_hint": "Александр Семенов",
            "relative_position": "latest",
            "include_card": True,
            "confidence": 0.95,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="Приведи цитаты Семенова с последнего занятия",
            lessons=lessons,
        )
    )
    assert plan.action == "rag_answer"
    assert plan.lesson_key == "s1_b3_l4"


def test_dispatch_rejects_lesson_that_does_not_match_ambiguous_speaker() -> None:
    lessons = [
        lesson("s1_b3_l1", 1, "Стратегия как инструмент", "Александр Семенов"),
        lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов"),
        lesson("s1_b4_l4", 20, "Финансовый практикум", "Ю. Макарова"),
    ]
    fake = FakeLLM(
        {
            "action": "rag_answer",
            "lesson_key": "s1_b4_l4",
            "speaker_hint": "Александр Семенов",
            "include_card": True,
            "confidence": 0.95,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="Что было на занятии Семенова?",
            lessons=lessons,
        )
    )
    assert plan.action == "clarify"
    assert plan.lesson_key is None


def test_dispatch_clarifies_when_model_picks_one_of_ambiguous_speaker_lessons() -> None:
    lessons = [
        lesson("s1_b3_l1", 1, "Стратегия как инструмент", "Александр Семенов"),
        lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов"),
    ]
    fake = FakeLLM(
        {
            "action": "rag_answer",
            "lesson_key": "s1_b3_l4",
            "speaker_hint": "Семенов",
            "include_card": True,
            "confidence": 0.95,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="Что было на занятии Семенова?",
            lessons=lessons,
        )
    )
    assert plan.action == "clarify"
    assert plan.lesson_key is None


def test_followup_inherits_speaker_from_pending_context() -> None:
    lessons = [
        lesson("s1_b3_l1", 1, "Стратегия как инструмент", "Александр Семенов"),
        lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов"),
    ]
    fake = FakeLLM(
        {
            "action": "rag_answer",
            "lesson_key": "s1_b3_l4",
            "speaker_hint": None,
            "relative_position": "latest",
            "include_card": True,
            "confidence": 0.95,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="самое последнее",
            lessons=lessons,
            conversation={
                "conversation_speaker_hint": "Семенов",
                "conversation_pending_question": "Приведи цитаты Семенова",
            },
        )
    )
    assert plan.action == "rag_answer"
    assert plan.lesson_key == "s1_b3_l4"
    assert plan.speaker_hint == "Семенов"
    assert "pending_question=Приведи цитаты Семенова" in fake.user_prompt


def test_explicit_date_repairs_unnecessary_clarification() -> None:
    lessons = [lesson("s1_b3_l4", 14, "Защита проектов", "Александр Семенов")]
    fake = FakeLLM(
        {
            "action": "clarify",
            "lesson_key": None,
            "clarification": "Какое занятие?",
            "confidence": 0.8,
        }
    )
    plan = asyncio.run(build_semantic_plan(llm_client=fake, question="хочу все по 14 июля", lessons=lessons))
    assert plan.action == "lesson_card"
    assert plan.lesson_key == "s1_b3_l4"


def test_speaker_and_lesson_number_repair_unnecessary_clarification() -> None:
    lessons = [
        lesson("s1_b4_l3", 4, "Отчёты и показатели", "Ю. Макарова"),
        lesson("s1_b4_l4", 11, "Групповая работа", "Ю. Макарова, С. Сафронов"),
    ]
    lessons[0].lesson_number = 3
    fake = FakeLLM(
        {
            "action": "clarify",
            "lesson_key": None,
            "speaker_hint": "Макарова",
            "clarification": "Какое занятие?",
            "confidence": 0.8,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="чо там Макарова рассказывала на третьем занятии",
            lessons=lessons,
        )
    )
    assert plan.action == "rag_answer"
    assert plan.lesson_key == "s1_b4_l3"


def test_colloquial_content_names_override_model_misclassification() -> None:
    lessons = [lesson("s1_b4_l4", 11, "Групповая работа", "Ю. Макарова, С. Сафронов")]
    fake = FakeLLM(
        {
            "action": "content_delivery",
            "lesson_key": "s1_b4_l4",
            "content_types": ["materials", "summary"],
            "confidence": 0.9,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="тока запись и выжимку с 11.08",
            lessons=lessons,
        )
    )
    assert plan.action == "content_delivery"
    assert plan.content_types == ("video", "summary")


def test_block_reference_does_not_mistake_kickoff_for_numbered_lesson() -> None:
    kickoff = lesson("s1_b1_kickoff", 1, "Кикоф программы", "")
    kickoff.lesson_number = None
    kickoff.block_title = "Кикоф программы и блока"
    fake = FakeLLM(
        {
            "action": "content_delivery",
            "lesson_key": "s1_b1_kickoff",
            "content_types": ["video"],
            "confidence": 0.9,
        }
    )
    plan = asyncio.run(
        build_semantic_plan(
            llm_client=fake,
            question="запись последнего занятия первого блока",
            lessons=[kickoff],
        )
    )
    assert plan.action == "clarify"
    assert plan.lesson_key is None
