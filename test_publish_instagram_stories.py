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


JPEG_BODY = b"\xff\xd8\xff\xe0" + b"jpeg-test-bytes"


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.body


class _ImageResponse:
    """A raw.githubusercontent-style response for the public-image gate."""

    def __init__(self, status: int = 206, body: bytes = JPEG_BODY,
                 content_type: str = "image/jpeg", total: int | None = None):
        self.status = status
        self.body = body
        total = len(JPEG_BODY) if total is None else total
        self.headers = {
            "Content-Type": content_type,
            "Content-Range": f"bytes 0-{max(len(body) - 1, 0)}/{total}",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self, *_args):
        return self.body


def _write_manifest(root: Path, count: int = 1) -> Path:
    items = []
    for n in range(count):
        filename = f"{n:02d}_training_{n:06d}.jpg"
        (root / filename).write_bytes(JPEG_BODY)
        items.append({"title": f"通告 {n + 1}", "instagram_file": filename})
    path = root / "manifest.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return path


def _ok_item(container: str = "container-1", media: str = "published-1") -> list:
    """The happy path for one Story: image live, container finished, published."""
    return [
        _ImageResponse(),
        _Response({"id": container}),
        _Response({"status_code": "FINISHED"}),
        _Response({"id": media}),
    ]


class TestPublisher(unittest.TestCase):
    ENV = {
        "INSTAGRAM_USER_ID": "1234567890",
        "INSTAGRAM_ACCESS_TOKEN": "test-token-not-a-real-secret",
    }

    def test_one_complete_item_verifies_image_then_creates_and_publishes_once(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter(_ok_item())
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                self.assertEqual(
                    publisher.publish_manifest(
                        manifest,
                        "https://raw.githubusercontent.com/acme/notices/abc123/stories/2026-09-23/",
                        self.ENV,
                        sleep=lambda _s: None,
                    ),
                    (1, 0),
                )

            # image probe + create + readiness poll + publish
            self.assertEqual(mock.call_count, 4)

            probe_request = mock.call_args_list[0].args[0]
            self.assertEqual(probe_request.get_method(), "GET")
            self.assertTrue(probe_request.full_url.endswith("00_training_000000.jpg"))
            self.assertIsNone(probe_request.get_header("Authorization"))

            create_request = mock.call_args_list[1].args[0]
            create_body = create_request.data.decode("utf-8")
            self.assertIn("media_type=STORIES", create_body)
            self.assertIn(
                "image_url=https%3A%2F%2Fraw.githubusercontent.com%2Facme%2Fnotices%2Fabc123%2Fstories%2F2026-09-23%2F00_training_000000.jpg",
                create_body,
            )
            self.assertNotIn("test-token-not-a-real-secret", create_request.full_url)
            self.assertNotIn("test-token-not-a-real-secret", create_body)
            self.assertEqual(create_request.get_header("Authorization"), "Bearer test-token-not-a-real-secret")

            status_request = mock.call_args_list[2].args[0]
            self.assertEqual(status_request.get_method(), "GET")
            self.assertIn("/container-1?", status_request.full_url)
            self.assertIn("status_code", status_request.full_url)

            publish_request = mock.call_args_list[3].args[0]
            self.assertIn("creation_id=container-1", publish_request.data.decode("utf-8"))

    def test_waits_for_image_to_become_public_before_creating_container(self):
        """No container is handed a URL that is still 404ing after a force-push."""
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                HTTPError("https://raw.githubusercontent.com/x.jpg", 404, "nf", {}, io.BytesIO(b"")),
                _ImageResponse(),
            ] + _ok_item()[1:])
            slept = []
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                self.assertEqual(
                    publisher.publish_manifest(
                        manifest,
                        "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                        self.ENV,
                        sleep=slept.append,
                    ),
                    (1, 0),
                )
            self.assertEqual(mock.call_count, 5)
            self.assertEqual(len(slept), 1)
            # The container was only created after the image answered 200.
            create_request = mock.call_args_list[2].args[0]
            self.assertIn("media_type=STORIES", create_request.data.decode("utf-8"))

    def test_image_never_public_fails_item_without_creating_a_container(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            stderr = io.StringIO()
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: _ImageResponse(status=404, body=b"nope")) as mock:
                with patch.object(publisher, "PUBLIC_IMAGE_TIMEOUT_SECONDS", 0.0):
                    with redirect_stderr(stderr):
                        self.assertEqual(
                            publisher.publish_manifest(
                                manifest,
                                "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                                self.ENV,
                                sleep=lambda _s: None,
                            ),
                            (0, 1),
                        )
            self.assertIn("not publicly fetchable", stderr.getvalue())
            for call in mock.call_args_list:
                self.assertEqual(call.args[0].get_method(), "GET")

    def test_truncated_or_mismatched_public_image_is_not_sent_to_meta(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            stderr = io.StringIO()
            partial = _ImageResponse(total=len(JPEG_BODY) + 5000)
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: partial):
                with patch.object(publisher, "PUBLIC_IMAGE_TIMEOUT_SECONDS", 0.0):
                    with redirect_stderr(stderr):
                        self.assertEqual(
                            publisher.publish_manifest(
                                manifest,
                                "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                                self.ENV,
                                sleep=lambda _s: None,
                            ),
                            (0, 1),
                        )
            self.assertIn("size mismatch", stderr.getvalue())

    def test_publish_waits_until_container_status_is_finished(self):
        """Regression for 2026-10-01: all five Stories died on 9007/2207027
        because media_publish was called while the container was IN_PROGRESS."""
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                _ImageResponse(),
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
                        "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                        self.ENV,
                        sleep=slept.append,
                    ),
                    (1, 0),
                )
            self.assertEqual(mock.call_count, 6)
            self.assertEqual(len(slept), 2)
            publish_calls = [
                call for call in mock.call_args_list
                if call.args[0].get_method() == "POST" and "media_publish" in call.args[0].full_url
            ]
            self.assertEqual(len(publish_calls), 1)

    def test_errored_container_is_rebuilt_once_and_the_story_still_posts(self):
        """A dead container was never posted, so rebuilding cannot duplicate."""
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                _ImageResponse(),
                _Response({"id": "container-1"}),
                _Response({"status_code": "ERROR", "status": "Error: 2207003 Media download failed"}),
                _Response({"id": "container-2"}),
                _Response({"status_code": "FINISHED"}),
                _Response({"id": "published-1"}),
            ])
            stderr = io.StringIO()
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                with redirect_stderr(stderr):
                    self.assertEqual(
                        publisher.publish_manifest(
                            manifest,
                            "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                            self.ENV,
                            sleep=lambda _s: None,
                        ),
                        (1, 0),
                    )
            self.assertIn("Media download failed", stderr.getvalue())
            publish_calls = [
                call for call in mock.call_args_list
                if call.args[0].get_method() == "POST" and "media_publish" in call.args[0].full_url
            ]
            self.assertEqual(len(publish_calls), 1)
            self.assertIn("creation_id=container-2", publish_calls[0].args[0].data.decode("utf-8"))

    def test_two_dead_containers_fail_the_item_without_publishing(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            responses = iter([
                _ImageResponse(),
                _Response({"id": "container-1"}),
                _Response({"status_code": "ERROR", "status": "Error: boom"}),
                _Response({"id": "container-2"}),
                _Response({"status_code": "ERROR", "status": "Error: boom again"}),
            ])
            stderr = io.StringIO()
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(responses)) as mock:
                with redirect_stderr(stderr):
                    self.assertEqual(
                        publisher.publish_manifest(
                            manifest,
                            "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                            self.ENV,
                            sleep=lambda _s: None,
                        ),
                        (0, 1),
                    )
            self.assertEqual(mock.call_count, 5)
            self.assertNotIn("media_publish", "".join(
                call.args[0].full_url for call in mock.call_args_list))

    def test_container_stuck_in_progress_times_out_without_publishing(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td))
            stream = iter([
                _ImageResponse(),
                _Response({"id": "container-1"}),
                _Response({"status_code": "IN_PROGRESS"}),
                _Response({"id": "container-2"}),
                _Response({"status_code": "IN_PROGRESS"}),
            ])
            stderr = io.StringIO()
            with patch.object(publisher, "urlopen", side_effect=lambda *_a, **_k: next(stream)) as mock:
                with patch.object(publisher, "STATUS_POLL_TIMEOUT_SECONDS", 0.0):
                    with redirect_stderr(stderr):
                        self.assertEqual(
                            publisher.publish_manifest(
                                manifest,
                                "https://raw.githubusercontent.com/a/b/abc123/stories/2026-10-01/",
                                self.ENV,
                                sleep=lambda _s: None,
                            ),
                            (0, 1),
                        )
            self.assertIn("still IN_PROGRESS", stderr.getvalue())
            self.assertNotIn("media_publish", "".join(
                call.args[0].full_url for call in mock.call_args_list))

    def test_failed_publish_is_not_retried_and_next_story_is_attempted_once(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_manifest(Path(td), count=2)
            responses = iter([
                _ImageResponse(),
                _Response({"id": "container-1"}),
                _Response({"status_code": "FINISHED"}),
                HTTPError("https://graph.facebook.com/", 400, "bad request", {}, io.BytesIO(b'{"error":{"message":"rejected"}}')),
                _ImageResponse(),
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
                            "https://raw.githubusercontent.com/a/b/abc123/stories/2026-09-23/",
                            self.ENV,
                            sleep=lambda _s: None,
                        ),
                        (1, 1),
                    )
            # A rejected media_publish is the one ambiguous call: never repeated.
            self.assertEqual(mock.call_count, 8)
            publish_calls = [
                call for call in mock.call_args_list
                if call.args[0].get_method() == "POST" and "media_publish" in call.args[0].full_url
            ]
            self.assertEqual(len(publish_calls), 2)

    def test_oversized_image_is_rejected_before_any_api_call(self):
        """Guard for heavier story-bases artwork: fail with a readable reason,
        not another opaque Graph API error."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _write_manifest(root)
            heavy = root / "00_training_000000.jpg"
            heavy.write_bytes(JPEG_BODY + b"\0" * (publisher.MAX_IMAGE_BYTES + 1 - len(JPEG_BODY)))
            with patch.object(publisher, "urlopen") as mock:
                with self.assertRaisesRegex(publisher.PublishError, "over Meta's 8MB limit"):
                    publisher.publish_manifest(
                        manifest, "https://raw.githubusercontent.com/a/b/sha/stories/2026-10-01/", self.ENV)
            mock.assert_not_called()

    def test_todays_real_image_sizes_are_accepted(self):
        """2026-10-01 AI backgrounds are 3-5x heavier than the old vector art
        (129KB -> 407KB for the same train_blue template) but still valid."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = _write_manifest(root)
            (root / "00_training_000000.jpg").write_bytes(
                JPEG_BODY + b"\0" * (626 * 1024 - len(JPEG_BODY)))
            self.assertEqual(len(publisher._manifest_items(manifest)), 1)

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
