import unittest
from unittest.mock import patch

import check_sources
import core


class SourceHealthClassificationTests(unittest.TestCase):
    def run_check(self, *, html, requested="https://example.org/notices", final=None, assets=None):
        result = core.FetchResult(final or requested, html, "requests", 200)
        with patch.object(check_sources.core, "fetch_main_page", return_value=result), \
             patch.object(check_sources.core, "extract_assets_from_listing", return_value=assets or []):
            return check_sources.check_one("Example", {
                "url": requested,
                "fingerprint_selector": ".notice-list",
            }, False)

    def test_reports_final_url_after_redirect(self):
        report = self.run_check(
            html='<div class="notice-list"></div>',
            final="https://new.example.org/notices",
            assets=[{"title": "通告", "pdf_url": "https://new.example.org/1.pdf"}],
        )
        self.assertEqual(report["status"], "OFFSITE_REDIRECT")
        self.assertTrue(report["address_changed"])
        self.assertEqual(report["final_url"], "https://new.example.org/notices")

    def test_detects_missing_fingerprint_as_layout_change(self):
        report = self.run_check(html="<html><body>new design</body></html>")
        self.assertEqual(report["status"], "LAYOUT_CHANGED")
        self.assertEqual(report["fingerprint_matches"], 0)

    def test_detects_empty_listing_with_intact_layout(self):
        report = self.run_check(html='<div class="notice-list"></div>')
        self.assertEqual(report["status"], "EMPTY")
        self.assertEqual(report["fingerprint_matches"], 1)

    def test_www_canonical_redirect_is_not_offsite(self):
        report = self.run_check(
            html='<div class="notice-list"></div>',
            requested="https://example.org/notices",
            final="https://www.example.org/notices",
        )
        self.assertEqual(report["status"], "EMPTY")
        self.assertTrue(report["address_changed"])
        self.assertFalse(report["offsite_redirect"])


if __name__ == "__main__":
    unittest.main()
