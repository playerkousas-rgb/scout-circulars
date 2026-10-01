#!/usr/bin/env python3
"""Offline tests for the daily no-repeat Story base allocation."""
from __future__ import annotations

import unittest

from story_template_pool import pick_daily_template_names


def item(category: str) -> dict[str, str]:
    return {"category": category}


class TestDailyTemplatePool(unittest.TestCase):
    def test_training_uses_three_native_bases_then_notice_overflow(self):
        """The exact case requested: do not repeat a training base first."""
        selected = pick_daily_template_names([item("training") for _ in range(6)])
        self.assertEqual(selected, [
            "train_blue", "train_orange", "train_green",
            "unc_scope", "unc_topsecret", "unc_glitch",
        ])
        self.assertEqual(len(set(selected)), 6)

    def test_overflow_bases_are_shared_across_categories_for_a_day(self):
        # First overflow needed: fourth training → unc_scope.
        # Second one is then needed by activity, not a second unc_scope.
        selected = pick_daily_template_names([
            *[item("training") for _ in range(4)],
            *[item("activity") for _ in range(2)],
            *[item("service") for _ in range(2)],
        ])
        self.assertEqual(selected, [
            "train_blue", "train_orange", "train_green", "unc_scope",
            "activity_army", "unc_topsecret",
            "service_wanted", "unc_glitch",
        ])
        self.assertEqual(len(set(selected)), len(selected))

    def test_repetition_starts_only_after_primary_and_all_three_overflow_bases(self):
        selected = pick_daily_template_names([item("training") for _ in range(7)])
        self.assertEqual(selected[:6], [
            "train_blue", "train_orange", "train_green",
            "unc_scope", "unc_topsecret", "unc_glitch",
        ])
        self.assertEqual(selected[6], "train_blue")

    def test_non_automatic_category_is_left_to_manual_selector(self):
        self.assertEqual(
            pick_daily_template_names([item("other"), item("announcement"), item("training")]),
            [None, None, "train_blue"],
        )

    def test_same_input_order_is_deterministic(self):
        items = [item("competition"), item("competition"), item("training"), item("training")]
        self.assertEqual(pick_daily_template_names(items), pick_daily_template_names(items))


if __name__ == "__main__":
    unittest.main(verbosity=2)
