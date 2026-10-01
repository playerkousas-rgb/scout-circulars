#!/usr/bin/env python3
"""Offline tests for the one-pass Instagram Story publisher."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent / ".github" / "scripts"))
import publish_instagram_stories as publisher  # noqa: E402


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.body


def _write_manifest(root: Path, count: int = 1) -> Path:
    items = []
    for n in range(count):
        filename = f"{n:02d}_training_{n:06d}.jpg"
        (root / filename).write_bytes(b"jpeg-test")
        items.append({"title": f"通告 {n + 1}", "instagram_file": filename})
    path = root / "manifest.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return path


class TestPublisher(unittest.TestCase):
    ENV = {
        "INSTAGRAM_USER_ID": "1234567890",
        "INSTAGRAM_ACCESS_TOKEN": "test-token-not-a-real-secret",
    }

    def test_one_complete_item_makes_one_create_and_one_publish_request(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                _Response({"id": "container-1"}),
                _Response({"status_code": "FINISHED"}),
                _Response({"id": "published-1"}),
            ])
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                self.assertEqual(
                    publisher.publish_manifest(
                        manifest,
                        "https://raw.githubusercontent.com/acme/notices/stories/stories/2026-09-23/",
                        self.ENV,
                        sleep=lambda _s: None,
                    ),
                    (1, 0),
                )

            # create + one readiness poll + publish
            self.assertEqual(mock.call_count, 3)
            create_request = mock.call_args_list[0].args[0]
            create_body = create_request.data.decode("utf-8")
            self.assertIn("media_type=STORIES", create_body)
            self.assertIn(
                "image_url=https%3A%2F%2Fraw.githubusercontent.com%2Facme%2Fnotices%2Fstories%2Fstories%2F2026-09-23%2F00_training_000000.jpg",
                create_body,
            )
            self.assertNotIn("test-token-not-a-real-secret", create_request.full_url)
            self.assertNotIn("test-token-not-a-real-secret", create_body)
            self.assertEqual(create_request.get_header("Authorization"), "Bearer test-token-not-a-real-secret")

            status_request = mock.call_args_list[1].args[0]
            self.assertEqual(status_request.get_method(), "GET")
            self.assertIn("/container-1?", status_request.full_url)
            self.assertIn("status_code", status_request.full_url)
            self.assertNotIn("test-token-not-a-real-secret", status_request.full_url)

            publish_request = mock.call_args_list[2].args[0]
            self.assertIn("creation_id=container-1", publish_request.data.decode("utf-8"))

    def test_publish_waits_until_container_status_is_finished(self):
        """Regression for 2026-10-01: all five Stories died on 9007/2207027
        because media_publish was called while the container was IN_PROGRESS."""
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                _Response({"id": "container-1"}),
                _Response({"status_code": "IN_PROGRESS"}),
                _Response({"status_code": "IN_PROGRESS"}),
                _Response({"status_code": "FINISHED"}),
                _Response({"id": "published-1"}),
            ])
            slept = []
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                self.assertEqual(
                    publisher.publish_manifest(
                        manifest,
                        "https://raw.githubusercontent.com/a/b/stories/stories/2026-10-01/",
                        self.ENV,
                        sleep=slept.append,
                    ),
                    (1, 0),
                )
            self.assertEqual(mock.call_count, 5)
            self.assertEqual(len(slept), 2)
            # Still exactly one publish attempt: polling is a readiness wait.
            publish_calls = [
                call for call in mock.call_args_list
                if call.args[0].get_method() == "POST" and "media_publish" in call.args[0].full_url
            ]
            self.assertEqual(len(publish_calls), 1)

    def test_errored_container_is_reported_with_meta_reason_and_not_published(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                _Response({"id": "container-1"}),
                _Response({"status_code": "ERROR", "status": "Error: 2207003 Media download failed"}),
            ])
            stderr = io.StringIO()
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                with redirect_stderr(stderr):
                    self.assertEqual(
                        publisher.publish_manifest(
                            manifest,
                            "https://raw.githubusercontent.com/a/b/stories/stories/2026-10-01/",
                            self.ENV,
                            sleep=lambda _s: None,
                        ),
                        (0, 1),
                    )
            # create + status poll only; no publish call for a dead container.
            self.assertEqual(mock.call_count, 2)
            self.assertIn("Media download failed", stderr.getvalue())

    def test_container_stuck_in_progress_times_out_without_publishing(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            # deadline read, then one reading per unfinished poll.
            clock = iter([0.0, 0.0, 61.0, 121.0])
            responses = [_Response({"id": "container-1"})] + [
                _Response({"status_code": "IN_PROGRESS"}) for _ in range(5)
            ]
            stream = iter(responses)
            stderr = io.StringIO()
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(stream)) as mock:
                with patch.object(publisher.time, "monotonic", side_effect=lambda: next(clock)):
                    with redirect_stderr(stderr):
                        self.assertEqual(
                            publisher.publish_manifest(
                                manifest,
                                "https://raw.githubusercontent.com/a/b/stories/stories/2026-10-01/",
                                self.ENV,
                                sleep=lambda _s: None,
                            ),
                            (0, 1),
                        )
            self.assertIn("still IN_PROGRESS", stderr.getvalue())
            self.assertNotIn("media_publish", "".join(
                call.args[0].full_url for call in mock.call_args_list))

    def test_failed_story_is_not_retried_and_next_story_is_attempted_once(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td), count=2)
            responses = iter([
                _Response({"id": "container-1"}),
                _Response({"status_code": "FINISHED"}),
                HTTPError("https://graph.facebook.com/", 400, "bad request", {}, io.BytesIO(b'{"error":{"message":"rejected"}}')),
                _Response({"id": "container-2"}),
                _Response({"status_code": "FINISHED"}),
                _Response({"id": "published-2"}),
            ])

            def fake_urlopen(*_args, **_kwargs):
                response = next(responses)
                if isinstance(response, Exception):
                    raise response
                return response

            with patch.object(publisher, "urlopen", side_effect=fake_urlopen) as mock:
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        publisher.publish_manifest(
                            manifest,
                            "https://raw.githubusercontent.com/a/b/stories/stories/2026-09-23/",
                            self.ENV,
                            sleep=lambda _s: None,
                        ),
                        (1, 1),
                    )
            # Item 1: create + status poll + one failed publish.
            # Item 2: create + status poll + publish.
            # No second attempt is made for item 1.
            self.assertEqual(mock.call_count, 6)

    def test_empty_queue_does_not_require_secrets_or_call_api(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "manifest.json"
            manifest.write_text('{"items": []}', encoding="utf-8")
            with patch.object(publisher, "urlopen") as mock:
                self.assertEqual(publisher.publish_manifest(manifest, "https://raw.githubusercontent.com/a/b/", {}), (0, 0))
            mock.assert_not_called()

    def test_missing_jpeg_stops_before_any_api_call(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "manifest.json"
            manifest.write_text(json.dumps({"items": [{"title": "缺圖", "instagram_file": "missing.jpg"}]}), encoding="utf-8")
            with patch.object(publisher, "urlopen") as mock:
                with self.assertRaises(publisher.PublishError):
                    publisher.publish_manifest(manifest, "https://raw.githubusercontent.com/a/b/", self.ENV)
            mock.assert_not_called()

    def test_token_missing_fails_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            with patch.object(publisher, "urlopen") as mock:
                with self.assertRaisesRegex(publisher.PublishError, "INSTAGRAM_ACCESS_TOKEN"):
                    publisher.publish_manifest(manifest, "https://raw.githubusercontent.com/a/b/", {"INSTAGRAM_USER_ID": "123"})
            mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
