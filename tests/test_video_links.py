from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from app.services.director_dashboard import DIRECTOR_TEST_TEAMS, is_director_dashboard_demo_user
from app.services.video_links import build_video_watch_url, verify_video_watch_token


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

    def test_demo_director_ids_are_recognized(self) -> None:
        demo_id = next(iter(DIRECTOR_TEST_TEAMS))

        self.assertTrue(is_director_dashboard_demo_user(demo_id))
        self.assertFalse(is_director_dashboard_demo_user(None))
        self.assertFalse(is_director_dashboard_demo_user(0))


if __name__ == "__main__":
    unittest.main()
