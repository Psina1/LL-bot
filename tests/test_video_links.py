from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.services.director_dashboard import DIRECTOR_DISPLAY_NAMES
from app.services.video_links import build_video_watch_url, verify_video_watch_token
from app.video_web import build_real_director_progress_data


class VideoLinksTests(unittest.TestCase):
    def test_plain_url_when_secret_is_empty(self) -> None:
        self.assertEqual(
            build_video_watch_url("https://video.example.com/", media_id=7, secret=""),
            "https://video.example.com/watch/7",
        )

    def test_signed_url_verifies(self) -> None:
        url = build_video_watch_url("https://video.example.com", media_id=7, secret="secret", ttl_hours=1)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/watch/7")
        self.assertTrue(
            verify_video_watch_token(
                media_id=7,
                expires_raw=query["expires"][0],
                token=query["token"][0],
                secret="secret",
            )
        )
        self.assertFalse(
            verify_video_watch_token(
                media_id=8,
                expires_raw=query["expires"][0],
                token=query["token"][0],
                secret="secret",
            )
        )

    def test_director_display_names_are_configured(self) -> None:
        self.assertIn(541848217, DIRECTOR_DISPLAY_NAMES)
        self.assertIn("@reptiloid0", DIRECTOR_DISPLAY_NAMES[541848217])

    def test_admin_with_assigned_team_sees_only_assigned_people(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            dashboard_dir = data_dir / "director_dashboard"
            dashboard_dir.mkdir()
            (dashboard_dir / "leader_dashboard_data.json").write_text(
                json.dumps(
                    {
                        "updatedAt": "26.08.2026",
                        "asOf": "26.08.2026",
                        "participants": [
                            {"id": "1", "name": "Ирина Матвеева", "cells": []},
                            {"id": "2", "name": "Анна Иванова", "cells": []},
                        ],
                        "points": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = SimpleNamespace(data_dir=data_dir)
            assigned_row = SimpleNamespace(
                telegram_id=314799815,
                allowed_full_name="Ирина Матвеева",
                user_full_name=None,
                allowed_username="Irigma1312",
                user_username=None,
            )
            result = build_real_director_progress_data(
                settings=settings,
                data={"mode": "director", "rows": [assigned_row]},
                telegram_id=541848217,
                admin_ids=[541848217],
            )

            self.assertIsNotNone(result)
            self.assertEqual([person["name"] for person in result["participants"]], ["Ирина Матвеева"])


if __name__ == "__main__":
    unittest.main()
