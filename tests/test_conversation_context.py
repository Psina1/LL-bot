from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from app.services.conversation_context import (
    has_fresh_active_lesson_context,
    is_contextual_lesson_followup,
)


class ConversationContextTests(unittest.TestCase):
    def test_recent_lesson_context_is_available(self) -> None:
        now = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
        data = {
            "last_lesson_key": "s1_b4_l3",
            "last_lesson_context_at": (now - timedelta(minutes=10)).isoformat(),
        }
        self.assertTrue(has_fresh_active_lesson_context(data, now=now))

    def test_stale_lesson_context_is_ignored(self) -> None:
        now = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
        data = {
            "last_lesson_key": "s1_b4_l3",
            "last_lesson_context_at": (now - timedelta(minutes=46)).isoformat(),
        }
        self.assertFalse(has_fresh_active_lesson_context(data, now=now))

    def test_contextual_followup_is_detected(self) -> None:
        self.assertTrue(is_contextual_lesson_followup("А что там про KPI?"))
        self.assertTrue(is_contextual_lesson_followup("А что по этому занятию?"))

    def test_global_request_does_not_reuse_active_lesson(self) -> None:
        self.assertFalse(is_contextual_lesson_followup("Покажи все материалы"))


if __name__ == "__main__":
    unittest.main()
