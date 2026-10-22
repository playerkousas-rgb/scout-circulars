#!/usr/bin/env python3
"""Tests for the anonymous registration-funnel counter (2026-10-22).

These cover the security promises of /api/push-events:
  - only the fixed event vocabulary is accepted (no free text, no PII);
  - a statistics failure never raises into the subscribe flow;
  - the browser and the server agree on the event names.
"""

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api"))

import push_common  # noqa: E402
from push_common import (  # noqa: E402
    FUNNEL_EVENTS,
    ApiError,
    SupabaseError,
    bump_funnel,
    validate_funnel_event,
)


class FunnelEventTests(unittest.TestCase):
    def test_accepts_every_declared_event(self):
        for event in FUNNEL_EVENTS:
            self.assertEqual(validate_funnel_event(event), event)

    def test_rejects_free_text_and_surrounding_injection(self):
        # 前後空白會 strip（瀏覽器有時會補），但任何自由文字一律拒收。
        for value in ("", None, "open", "panel_open; DROP TABLE", "a" * 200, ["panel_open"], {"event": "panel_open"}):
            with self.subTest(value=value), self.assertRaises(ApiError) as caught:
                validate_funnel_event(value)
            self.assertEqual(caught.exception.code, "invalid_event")

    def test_bump_uses_rpc_without_pii(self):
        with mock.patch.object(push_common, "supabase_request") as request:
            self.assertTrue(bump_funnel("panel_open", {"supabase_url": "https://x", "supabase_key": "k"}))
        args, kwargs = request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "rpc/push_funnel_bump")
        self.assertEqual(kwargs["payload"], {"p_event": "panel_open"})
        self.assertEqual(set(kwargs["payload"]), {"p_event"})

    def test_bump_never_raises(self):
        for error in (SupabaseError(503, "down"), OSError("offline")):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(push_common, "supabase_request", side_effect=error):
                self.assertFalse(bump_funnel("panel_open", {}))

    def test_browser_events_are_all_allowed(self):
        """push-client.js / index.html 唔可以偷偷送一個 server 唔識嘅事件。"""
        patterns = (
            (ROOT / "push-client.js", r"track\('([a-z_]+)'\)"),
            (ROOT / "index.html", r"track\?\.\('([a-z_]+)'\)"),
        )
        found = set()
        for path, pattern in patterns:
            found.update(re.findall(pattern, path.read_text(encoding="utf-8")))
        self.assertTrue(found, "expected the client to report funnel events")
        self.assertLessEqual(found, set(FUNNEL_EVENTS), f"unknown client events: {sorted(found - set(FUNNEL_EVENTS))}")
        # 最關鍵的兩步一定要有，否則漏斗答唔到「邊一步走失」。
        self.assertIn("panel_open", found)
        self.assertIn("enable_click", found)

    def test_events_endpoint_is_wired_in_vercel(self):
        import json

        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        self.assertIn("api/push_events.py", config["functions"])
        sources = {rule["source"] for rule in config["rewrites"]}
        self.assertIn("/api/push-events", sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
