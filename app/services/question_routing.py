from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DirectQuestionRoute:
    mode: str
    answer: str


VOICE_CAPABILITIES_ANSWER = (
    "Ты можешь отправлять мне голосовые сообщения: я распознаю вопрос и отвечу на него текстом. "
    "Голосом я пока не отвечаю."
)

BOT_CAPABILITIES_ANSWER = (
    "Я помогаю участникам «Лиги лидеров»: отвечаю по материалам и расписанию программы, "
    "помогаю разобраться с домашними заданиями, выдаю загруженные материалы и принимаю "
    "текстовые и голосовые вопросы. Отвечаю я пока текстом."
)

OFF_TOPIC_ANSWER = (
    "Я специализируюсь на программе «Лига лидеров». "
    "Могу помочь с занятиями, расписанием, материалами и домашними заданиями."
)


def route_direct_question(text_value: str | None) -> DirectQuestionRoute | None:
    text = _normalize(text_value)
    if not text:
        return None

    if _is_voice_capability_question(text):
        return DirectQuestionRoute(mode="bot_voice_capabilities", answer=VOICE_CAPABILITIES_ANSWER)

    if _is_general_capability_question(text):
        return DirectQuestionRoute(mode="bot_capabilities", answer=BOT_CAPABILITIES_ANSWER)

    if _is_clearly_off_topic(text):
        return DirectQuestionRoute(mode="off_topic", answer=OFF_TOPIC_ANSWER)

    return None


def _normalize(text_value: str | None) -> str:
    return " ".join((text_value or "").lower().replace("ё", "е").split())


def _is_voice_capability_question(text: str) -> bool:
    voice_markers = (
        "голос",
        "голосов",
        "аудиосообщ",
        "аудио сообщ",
    )
    interaction_markers = (
        "с тобой",
        "тебе",
        "ты мож",
        "можно",
        "умеешь",
        "принимаешь",
        "ответишь",
        "отвечаешь",
        "общаться",
        "говорить",
        "слушаешь",
        "отправить",
        "записать",
    )
    return any(marker in text for marker in voice_markers) and any(
        marker in text for marker in interaction_markers
    )


def _is_general_capability_question(text: str) -> bool:
    capability_phrases = (
        "что ты умеешь",
        "что умеет бот",
        "что может бот",
        "чем ты можешь помочь",
        "чем можешь помочь",
        "какие у тебя возможности",
        "как тобой пользоваться",
        "как с тобой работать",
        "как пользоваться ботом",
        "кто ты такой",
        "кто ты такая",
        "что ты можешь",
    )
    return any(phrase in text for phrase in capability_phrases)


def _is_clearly_off_topic(text: str) -> bool:
    off_topic_markers = (
        "как приготовить борщ",
        "рецепт борща",
        "рецепт пиццы",
        "какая погода",
        "прогноз погоды",
        "курс доллара",
        "курс евро",
        "расскажи анекдот",
        "гороскоп",
        "кто выиграл матч",
        "результат матча",
    )
    return any(marker in text for marker in off_topic_markers)
