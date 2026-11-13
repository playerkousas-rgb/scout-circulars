#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-11-04 用戶規則：歲數／「XX支部或以上」→ 支部標籤。

權威定義喺 subscription_tagging.py；enrich.py（PDF 對象抽取）、notify.py
（推播支部標籤）同 index.html（前端支部篩選，JS 鏡像由 test_search_members.js
釘住）都要跟同一套結果。
"""
import unittest

from enrich import extract_audience
from subscription_tagging import (
    CHAR_VARIANTS, YOUTH_SECTION_ORDER, age_and_or_above_branches,
    branches_from_min_age, branches_from_or_above, extra_branch_tokens,
    extract_branch_ids, extract_categories, extract_subscription_metadata,
    normalize,
)


class SectionOrderTests(unittest.TestCase):
    def test_or_above_stops_at_rovers_and_never_adds_leaders(self):
        self.assertEqual(branches_from_or_above("小童軍"), YOUTH_SECTION_ORDER)
        self.assertEqual(branches_from_or_above("幼童軍"),
                         ("幼童軍", "童軍", "深資童軍", "樂行童軍"))
        self.assertEqual(branches_from_or_above("童軍"),
                         ("童軍", "深資童軍", "樂行童軍"))
        self.assertEqual(branches_from_or_above("深資童軍"),
                         ("深資童軍", "樂行童軍"))
        self.assertEqual(branches_from_or_above("樂行童軍"), ("樂行童軍",))
        self.assertEqual(branches_from_or_above("領袖"), ())
        self.assertNotIn("領袖", extra_branch_tokens("童軍支部或以上成員"))

    def test_age_table_matches_user_examples(self):
        # 用戶：15歲以上＝童軍＋深資童軍＋樂行童軍；18歲以上＝深資＋樂行
        self.assertEqual(branches_from_min_age(15),
                         ("童軍", "深資童軍", "樂行童軍"))
        self.assertEqual(branches_from_min_age(18), ("深資童軍", "樂行童軍"))
        self.assertEqual(branches_from_min_age(11),
                         ("童軍", "深資童軍", "樂行童軍"))
        self.assertEqual(branches_from_min_age(21), ("樂行童軍",))
        self.assertEqual(branches_from_min_age(6),
                         ("童軍", "深資童軍", "樂行童軍"))

    def test_under_age_consent_is_not_an_age_rule(self):
        text = "18歲以下之參加者必須簽署家長／監護人同意書（RT06）。"
        self.assertEqual(age_and_or_above_branches(text), (set(), set()))
        self.assertEqual(extra_branch_tokens(text), set())

    def test_bounded_age_range_does_not_expand_past_its_upper_limit(self):
        text = "受資助資格：年齡為8至11歲，持有有效幼童軍紀錄冊及童軍成員編號的幼童軍。"
        self.assertEqual(age_and_or_above_branches(text), (set(), set()))
        self.assertEqual(extract_audience(text), "幼童軍")

    def test_or_above_and_age_phrases(self):
        age, above = age_and_or_above_branches("童軍支部或以上成員")
        self.assertEqual(age, set())
        self.assertEqual(above, {"童軍", "深資童軍", "樂行童軍"})
        age, above = age_and_or_above_branches("15歲以上之童軍成員")
        self.assertEqual(age, {"童軍", "深資童軍", "樂行童軍"})
        self.assertEqual(above, set())


class AudienceAndPushTests(unittest.TestCase):
    def test_extract_audience_age_phrases(self):
        self.assertEqual(extract_audience("參加資格：15歲以上之童軍成員。"),
                         "童軍、深資童軍、樂行童軍")
        self.assertEqual(extract_audience("參加資格：18歲或以上之童軍成員。"),
                         "深資童軍、樂行童軍")
        self.assertEqual(extract_audience("參加資格：童軍支部或以上成員。"),
                         "童軍、深資童軍、樂行童軍")
        self.assertEqual(extract_audience("參加資格：幼童軍支部或以上之成員。"),
                         "幼童軍、童軍、深資童軍、樂行童軍")

    def test_explicit_branch_list_is_not_overridden_by_age(self):
        self.assertEqual(
            extract_audience("（二）參加資格：11至26歲(以本通告發出日為準)的童軍、深資童軍或樂行童軍支部成員;"),
            "深資童軍、樂行童軍、童軍",
        )
        # 6歲或以上＋明列幼童軍：唔可以因為歲數推論而掉走幼童軍
        self.assertEqual(
            extract_audience("參加資格：6歲或以上持有有效紀錄冊之幼童軍、童軍、深資童軍及樂行童軍支部成員；"),
            "幼童軍、深資童軍、樂行童軍、童軍",
        )

    def test_push_branch_tags_follow_the_same_rules(self):
        self.assertEqual(
            extract_branch_ids("活動通告", "18歲以上之童軍成員"),
            {"深資童軍", "樂行童軍"},
        )
        meta = extract_subscription_metadata("活動通告", "", "幼童軍支部或以上成員")
        self.assertEqual(set(meta["branch_tags"]),
                         {"幼童軍", "童軍", "深資童軍", "樂行童軍"})
        self.assertNotIn("領袖", meta["branch_tags"])

    def test_age_rule_from_title_only(self):
        # 舊通告冇 audience，標題自己寫年齡都要展開
        self.assertEqual(extract_branch_ids("15歲以上童軍成員遠足活動", ""),
                         {"童軍", "深資童軍", "樂行童軍"})


class VariantAndCategoryTests(unittest.TestCase):
    def test_char_variants_are_shared(self):
        self.assertEqual(normalize("傑出服務奬"), normalize("傑出服務獎"))
        self.assertEqual("奬奨敎歳".translate(CHAR_VARIANTS), "獎獎教歲")

    def test_2026_11_04_circular_categories(self):
        self.assertEqual(extract_categories("冬日弦音 • 聖誕燒烤派對", "")[0]["id"], "activity")
        self.assertEqual(
            extract_categories("葛量洪青少年制服團隊傑出服務奬2026-2027", "社會服務")[0]["id"],
            "announcement",
        )
        self.assertEqual(
            extract_categories(
                "11-2026 小童軍支部 - 「小草」賀新春—小童軍親子利是封設計比賽 (截止: 2026-12-26)", ""
            )[0]["id"],
            "competition",
        )
        # 服務獎唔可以再由內文「服務」抢去做服務
        self.assertEqual(
            extract_categories("葛量洪獎學基金 葛量洪青少年制服團隊傑出服務獎 2026-2027",
                               "社會服務、義工服務")[0]["id"],
            "announcement",
        )


if __name__ == "__main__":
    unittest.main()
