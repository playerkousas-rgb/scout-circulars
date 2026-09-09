#!/usr/bin/env python3
"""Pure-unit checks for the anonymous Web Push dispatcher (no network needed)."""

import io
import json
import os
import tempfile
import unittest
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from subscription_tagging import matching_topics_for_branches

from notify import (
    MAX_PAYLOAD_NOTICE_IDS,
    PUSH_TTL_SECONDS,
    StorageError,
    annotate_failure,
    build_push_payload,
    find_catchup_notices,
    find_new_notices,
    main,
    matching_groups,
    missing_required_push_env,
    notice_id,
    notice_key,
    notice_metadata,
    notification_results_url,
    push_failures_are_systemic,
    secrets_preflight,
    send_web_push,
    subscription_matches,
)


class NotifyMatchingTests(unittest.TestCase):
    def setUp(self):
        self.training_one = {
            "source_site": "總會",
            "pdf_url": "https://example.test/one.pdf",
            "title": "童軍繩結訓練班",
            "captured_date": "2026-09-07",
        }
        self.training_two = {
            "source_site": "總會",
            "pdf_url": "https://example.test/two.pdf",
            "title": "童軍初級空勤員章工作坊",
            "captured_date": "2026-09-07",
        }
        self.service = {
            "source_site": "總會",
            "pdf_url": "https://example.test/service.pdf",
            "title": "童軍社區服務日",
            "captured_date": "2026-09-07",
        }
        self.enrich = {
            self.training_one["pdf_url"]: {"branch_tags": ["童軍"], "subscription_tags": ["category:training"], "deadline": "2026-09-10", "fee": "HK$50"},
            self.training_two["pdf_url"]: {"branch_tags": ["童軍"], "subscription_tags": ["category:training", "course:scout-basic-aircrew-badge"]},
            self.service["pdf_url"]: {"branch_tags": ["童軍"], "subscription_tags": ["category:service"]},
        }
        self.subscription = {
            "id": "00000000-0000-0000-0000-000000000001",
            "branch_ids": ["童軍", "深資童軍"],
            "topic_ids": ["category:training", "activity:campfire"],
        }

    def test_general_topics_still_require_exact_branch(self):
        for topic, title in (("activity:other", "參觀活動"), ("activity:big-camp", "大露營"),
                             ("activity:campfire", "營火會"), ("category:competition", "比賽"),
                             ("category:service", "社區服務日")):
            sub = {"branch_ids": ["小童軍"], "topic_ids": [topic]}
            for branch in ("小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍"):
                with self.subTest(topic=topic, branch=branch):
                    meta = notice_metadata({"title": branch + title}, {})
                    self.assertEqual(subscription_matches(sub, meta), branch == "小童軍")
            self.assertFalse(subscription_matches(sub, {"branch_tags": [], "topic_tags": [topic]}))
            self.assertFalse(subscription_matches(sub, {"branch_tags": ["小童軍"], "topic_tags": []}))

    def test_legacy_parent_and_child_choices_use_each_topics_branch_scope(self):
        sub = {"branch_ids": ["家長", "小童軍"], "topic_ids": ["activity:other", "category:competition", "category:training", "category:service"]}
        for branches, tags, expected in (
            (["小童軍"], ["activity:other"], True),
            (["小童軍"], ["category:competition"], True),
            (["家長", "小童軍"], ["activity:other"], True),
            (["童軍"], ["activity:other"], False),
            (["家長"], [], False),
            (["家長"], ["category:training"], False),
            (["家長"], ["category:service"], False),
            (["童軍", "家長"], ["activity:other"], True),
            (["家長"], ["activity:other"], True),
            (["小童軍"], ["category:training"], True),
            (["小童軍"], ["category:service"], True),
            (["小童軍"], ["category:service", "activity:other"], True),
            (["小童軍"], ["course:scout-first-aid-badge", "activity:other"], True),
        ):
            with self.subTest(branches=branches, tags=tags):
                self.assertEqual(subscription_matches(sub, {"branch_tags": branches, "topic_tags": tags}), expected)
        parent_only = {"branch_ids": ["家長"], "topic_ids": ["activity:other"]}
        self.assertTrue(subscription_matches(parent_only, {"branch_tags": ["家長"], "topic_tags": ["activity:other"]}))
        self.assertFalse(subscription_matches(parent_only, {"branch_tags": ["童軍"], "topic_tags": ["activity:other"]}))
        sub["branch_ids"].append("幼童軍")
        self.assertTrue(subscription_matches(sub, {"branch_tags": ["幼童軍"], "topic_tags": ["activity:other"]}))

    def test_parent_and_child_match_aggregates_each_notice_once(self):
        sub = {"id": "parent-child", "branch_ids": ["家長", "小童軍"], "topic_ids": ["branch:家長:activity:other", "branch:小童軍:activity:other"]}
        notices, enrich = [], {}
        for index, branches in enumerate((["家長"], ["小童軍"], ["家長", "小童軍"], ["童軍"])):
            item = {"title": "參觀活動", "source_site": "總會", "pdf_url": f"https://example.test/activity-{index}.pdf"}
            notices.append(item)
            enrich[item["pdf_url"]] = {"branch_tags": branches, "subscription_tags": ["activity:other"]}
        groups = matching_groups([sub], notices, notices, enrich, set())
        self.assertEqual(list(groups), [sub["id"]])
        _, newly, summary = groups[sub["id"]]
        self.assertEqual(newly, notices[:3])
        self.assertEqual(summary, notices[:3])
        payload = build_push_payload(summary, enrich, "https://example.test", "2026-09-08")
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len(set(payload["noticeIds"])), 3)

    def test_parent_activity_requires_parent_audience_and_activity_type(self):
        sub = {"branch_ids": ["家長"], "topic_ids": ["activity:other"]}
        item = {"title": "港島童軍繽紛日2026", "pdf_url": "https://example.test/fun-day.pdf"}
        # Example from the stored circular's audience; title alone is not proof
        # that parents may participate. Use fresh tagging / old-record fallback.
        for audience, expected in (("童軍、領袖、家長、成年成員", True),
                                   ("童軍、領袖", False), ("", False)):
            meta = notice_metadata(item, {item["pdf_url"]: {"audience": audience}})
            self.assertIn("activity:other", meta["topic_tags"])
            self.assertEqual(subscription_matches(sub, meta), expected)
        self.assertFalse(subscription_matches(sub, {"branch_tags": ["家長"], "topic_tags": []}))
        self.assertFalse(subscription_matches(sub, {"branch_tags": ["家長"], "topic_tags": ["category:competition"]}))

    def test_catalog_parent_options_and_branch_first_choices(self):
        self.assertEqual(matching_topics_for_branches([]), [])
        choices = [t for t in matching_topics_for_branches(["家長"]) if t["kind"] != "all"]
        self.assertTrue(choices)
        self.assertTrue(all(t["group"] in {"活動", "比賽"} for t in choices))
        choices = {t["id"] for t in matching_topics_for_branches(["家長", "童軍"])}
        self.assertIn("training:童軍", choices)
        self.assertIn("branch:童軍:category:service", choices)
        self.assertNotIn("branch:家長:category:service", choices)
        self.assertNotIn("category:service", choices)

    def test_branch_scoped_pairs_cannot_cross_match(self):
        sub = {"branch_ids": ["家長", "小童軍"], "topic_ids": ["branch:家長:activity:other", "branch:小童軍:category:competition"]}
        for branch, topic, expected in (
            ("家長", "activity:other", True), ("小童軍", "category:competition", True),
            ("家長", "category:competition", False), ("小童軍", "activity:other", False),
            ("童軍", "activity:other", False), ("童軍", "category:competition", False),
        ):
            with self.subTest(branch=branch, topic=topic):
                self.assertEqual(subscription_matches(sub, {"branch_tags": [branch], "topic_tags": [topic]}), expected)
        sub["topic_ids"].append("branch:小童軍:category:service")
        self.assertTrue(subscription_matches(sub, {"branch_tags": ["小童軍"], "topic_tags": ["category:service"]}))
        self.assertFalse(subscription_matches(sub, {"branch_tags": ["家長"], "topic_tags": ["category:service"]}))
        sub["branch_ids"] = ["家長"]
        self.assertFalse(subscription_matches(sub, {"branch_tags": ["小童軍"], "topic_tags": ["category:competition"]}))

    def test_all_new_includes_untagged_but_only_new_undelivered_items(self):
        sub = {"id": "all", "branch_ids": [], "topic_ids": ["all:new"]}
        self.assertTrue(subscription_matches(sub, {}))
        old = {"title": "舊通告", "source_site": "總會", "pdf_url": "https://example.test/old.pdf"}
        new = {"title": "未分類新通告", "source_site": "總會", "pdf_url": "https://example.test/new.pdf"}
        found = find_new_notices({"notices": [old, new]}, {"notices": [old]})
        groups = matching_groups([sub], found, found, {}, set())
        self.assertEqual(groups["all"][1], [new])
        self.assertEqual(groups["all"][2], [new])
        self.assertEqual(matching_groups([sub], found, found, {}, {("all", notice_key(new))}), {})
        self.assertEqual(matching_groups([sub], [], [], {}, set()), {})
        scoped = {"branch_ids": ["家長"], "topic_ids": ["branch:家長:activity:other"]}
        self.assertFalse(subscription_matches(scoped, {}))

    def test_webpush_retains_each_message_for_three_days(self):
        webpush = Mock()
        with patch.dict(sys.modules, {"pywebpush": SimpleNamespace(webpush=webpush)}):
            send_web_push({"endpoint": "https://example.test", "p256dh": "key", "auth": "auth"},
                          {"title": "測試"}, {"private_key": "private", "subject": "https://example.test"})
        self.assertEqual(PUSH_TTL_SECONDS, 259200)
        self.assertEqual(webpush.call_args.kwargs["ttl"], 259200)

    def test_source_qualified_cache_comparison(self):
        same_url = "https://example.test/shared.pdf"
        baseline = {"data": {"甲區": [{"source_site": "甲區", "pdf_url": same_url}]}}
        current = {"data": {"甲區": [{"source_site": "甲區", "pdf_url": same_url}], "乙區": [{"source_site": "乙區", "pdf_url": same_url}]}}
        found = find_new_notices(current, baseline)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source_site"], "乙區")
        self.assertNotEqual(notice_key(found[0]), notice_key(baseline["data"]["甲區"][0]))

    def test_catchup_covers_local_first_same_day_items(self):
        # 本機後備先寫入：通告已喺 baseline 入面，HEAD diff 係空，
        # 但 captured_date 係今日 → 補發要納入。
        local_first = dict(self.training_one, captured_date="2026-09-08")
        current = {"notices": [local_first]}
        baseline = {"notices": [local_first]}
        self.assertEqual(find_new_notices(current, baseline), [])
        found = find_catchup_notices(current, [], "2026-09-08")
        self.assertEqual(found, [local_first])

    def test_catchup_ignores_other_days_and_missing_dates(self):
        yesterday = dict(self.training_one, captured_date="2026-09-07")
        no_date = {"source_site": "總會", "pdf_url": "https://example.test/nodate.pdf", "title": "無日期"}
        current = {"notices": [yesterday, no_date]}
        self.assertEqual(find_catchup_notices(current, [], "2026-09-08"), [])

    def test_catchup_never_duplicates_baseline_diff(self):
        # Action 跑先嘅正常情況：diff 已發現今日項目，補發唔可以重複加。
        discovered = dict(self.training_two, captured_date="2026-09-08")
        current = {"notices": [discovered]}
        self.assertEqual(find_catchup_notices(current, [discovered], "2026-09-08"), [])

    def test_catchup_item_still_filtered_by_delivery_record(self):
        # 補發納入後，每訂閱者嘅 delivered 紀錄仍然擋重複：同日重跑保持靜默。
        sub = {"id": "all", "branch_ids": [], "topic_ids": ["all:new"]}
        item = dict(self.training_one, captured_date="2026-09-08")
        found = find_catchup_notices({"notices": [item]}, [], "2026-09-08")
        self.assertEqual(len(found), 1)
        self.assertEqual(matching_groups([sub], found, found, self.enrich, set())["all"][1], [item])
        self.assertEqual(matching_groups([sub], found, found, self.enrich, {("all", notice_key(item))}), {})

    def test_branch_and_topic_intersection_then_aggregate(self):
        groups = matching_groups(
            [self.subscription],
            [self.training_one, self.training_two, self.service],
            [self.training_one, self.training_two, self.service],
            self.enrich,
            set(),
        )
        self.assertEqual(list(groups), [self.subscription["id"]])
        _sub, newly, summary = groups[self.subscription["id"]]
        self.assertEqual([item["pdf_url"] for item in newly], [self.training_one["pdf_url"], self.training_two["pdf_url"]])
        self.assertEqual(len(summary), 2)

    def test_already_delivered_notice_does_not_resend_but_stays_in_updated_summary(self):
        groups = matching_groups(
            [self.subscription],
            [self.training_one, self.training_two],
            [self.training_one, self.training_two],
            self.enrich,
            {(self.subscription["id"], notice_key(self.training_one))},
        )
        _sub, newly, summary = groups[self.subscription["id"]]
        self.assertEqual(newly, [self.training_two])
        self.assertEqual(summary, [self.training_one, self.training_two])

    def test_one_item_payload_is_minimal_and_opens_exact_library_result(self):
        payload = build_push_payload([self.training_one], self.enrich, "https://site.example/", "2026-09-07")
        expected_id = notice_id(self.training_one)
        self.assertEqual(payload["title"], "🔔 童軍繩結訓練班")
        self.assertEqual(payload["body"], "點擊查看通告")
        self.assertEqual(payload["url"], f"https://site.example/?n={expected_id}")
        self.assertNotIn(self.training_one["pdf_url"], payload["url"])
        self.assertEqual(payload["noticeIds"], [expected_id])
        self.assertEqual(payload["tag"], "scout-circulars-personal-2026-09-07")
        self.assertFalse(payload["silent"])

    def test_multi_item_payload_is_minimal_and_opens_exact_library_results(self):
        payload = build_push_payload([self.training_one, self.training_two], self.enrich, "https://site.example/", "2026-09-07")
        expected_ids = [notice_id(self.training_one), notice_id(self.training_two)]
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["title"], "🔔 你關注的項目有 2 項新通告")
        self.assertEqual(payload["body"], "按此查看全部")
        self.assertEqual(payload["url"], f"https://site.example/?n={','.join(expected_ids)}")
        self.assertNotIn("personal=1", payload["url"])
        self.assertEqual(payload["noticeIds"], expected_ids)
        self.assertEqual(payload["tag"], "scout-circulars-personal-2026-09-07")
        update = build_push_payload([self.training_one, self.training_two], self.enrich, "https://site.example/", "2026-09-07", silent=True)
        self.assertTrue(update["silent"])


class NotifyResilienceTests(unittest.TestCase):
    """Guards against the 2026-09-09 dispatcher incidents (payload size / one bad endpoint)."""

    def big_day(self, count=300):
        # 2026-09-02 already saw 170 real notices in one day; test beyond that.
        return [
            {
                "source_site": "總會",
                "pdf_url": f"https://example.test/big-day/{index}.pdf",
                "title": f"大日子通告 {index}",
                "captured_date": "2026-09-08",
            }
            for index in range(count)
        ]

    def test_big_day_payload_stays_under_rfc_8291_limit(self):
        payload = build_push_payload(self.big_day(), {}, "https://scout-circulars.vercel.app", "2026-09-08")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # RFC 8291 record size is 4096 bytes; keep headroom for encryption overhead.
        self.assertLessEqual(len(raw), 3400)
        # Title/count still report the true total even though IDs are capped.
        self.assertEqual(payload["count"], 300)
        self.assertIn("300 項新通告", payload["title"])
        self.assertEqual(len(payload["noticeIds"]), MAX_PAYLOAD_NOTICE_IDS)
        self.assertEqual(len(set(payload["noticeIds"])), MAX_PAYLOAD_NOTICE_IDS)
        self.assertEqual(payload["noticeIds"][0], notice_id({"source_site": "總會", "pdf_url": "https://example.test/big-day/0.pdf"}))

    def test_results_url_caps_notice_ids_but_keeps_order(self):
        notices = self.big_day()
        url = notification_results_url("https://scout-circulars.vercel.app", notices)
        ids = parse_qs(urlsplit(url).query)["n"][0].split(",")
        self.assertEqual(len(ids), MAX_PAYLOAD_NOTICE_IDS)
        self.assertEqual(ids, [notice_id(item) for item in notices[:MAX_PAYLOAD_NOTICE_IDS]])
        # A small batch is not truncated; dedupe still applies.
        two = notification_results_url("https://site.example/", [notices[0], notices[1], notices[0]])
        self.assertEqual(parse_qs(urlsplit(two).query)["n"][0].split(","), [notice_id(notices[0]), notice_id(notices[1])])

    def test_isolated_endpoint_failures_do_not_block_pipeline(self):
        self.assertFalse(push_failures_are_systemic(0, 0))
        self.assertFalse(push_failures_are_systemic(0, 3))
        self.assertFalse(push_failures_are_systemic(1, 3))
        self.assertFalse(push_failures_are_systemic(1, 2))  # exactly half is not "過半"
        self.assertTrue(push_failures_are_systemic(1, 1))
        self.assertTrue(push_failures_are_systemic(2, 3))
        self.assertTrue(push_failures_are_systemic(2, 2))
        self.assertTrue(push_failures_are_systemic(3, 5))


class NotifyDispatchFailureTests(unittest.TestCase):
    """2026-09-09 第二次事故：步驟 2–3 秒就 exit 1，而 log 讀唔到。

    失敗必須自己講明原因（annotation），而且只要未發出任何通知，就唔可以
    連累 cache 提交（根因 B）。
    """

    NOTICE = {
        "source_site": "總會",
        "pdf_url": "https://example.test/catchup.pdf",
        "title": "今日新通告",
        "captured_date": "2026-09-09",
    }
    FULL_ENV = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_KEY": "service-key-value-must-never-be-logged",
        "VAPID_PRIVATE_KEY": "vapid-private-value-must-never-be-logged",
    }

    def run_main(self, env, client):
        """Run main() against a temp cache. Returns (exit_code, combined_output)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache.json"
            cache.write_text(
                json.dumps({"last_updated": "2026-09-09 10:15:07", "notices": [self.NOTICE]}, ensure_ascii=False),
                encoding="utf-8",
            )
            enrich = root / "enrich.json"
            enrich.write_text("{}", encoding="utf-8")
            buffer = io.StringIO()
            with patch.multiple(
                "notify",
                CACHE_PATH=cache,
                ENRICH_PATH=enrich,
                SupabaseClient=client,
                load_baseline_cache=lambda ref: {"notices": []},
                send_web_push=lambda subscription, payload, config: None,
            ), patch.dict(os.environ, env, clear=True), patch.object(
                sys, "argv", ["notify.py", "--batch-date", "2026-09-09"]
            ), redirect_stdout(buffer), redirect_stderr(buffer):
                code = main()
        return code, buffer.getvalue()

    def test_preflight_reports_presence_without_values(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co", "VAPID_PRIVATE_KEY": "pem"}, clear=True):
            state = secrets_preflight()
            missing = missing_required_push_env()
        self.assertTrue(state["SUPABASE_URL"])
        self.assertTrue(state["VAPID_PRIVATE_KEY"])
        self.assertFalse(state["SUPABASE_SERVICE_KEY"])
        self.assertEqual(missing, ["SUPABASE_SERVICE_KEY"])

    def test_missing_secret_is_named_and_step_stays_red(self):
        code, out = self.run_main({"SUPABASE_URL": "https://example.supabase.co"}, client=object)
        # 仍然要紅（靜默綠燈正正係今次睇漏嘅原因）；cache 由 scrape.yml 嘅
        # steps.notify 條件保住，見 test_workflow_commits_cache_when_notify_fails。
        self.assertEqual(code, 1)
        # 缺少邊個 secret 要講得出嚟
        self.assertIn("SUPABASE_SERVICE_KEY", out)
        self.assertIn("VAPID_PRIVATE_KEY", out)
        self.assertIn("::error title=notify::", out)
        self.assertNotIn("service-key-value-must-never-be-logged", out)

    def test_supabase_read_failure_is_named_and_step_stays_red(self):
        class Broken:
            def __init__(self, url, service_key):
                pass

            def active_subscriptions(self):
                raise StorageError("Supabase HTTP 404")

        code, out = self.run_main(dict(self.FULL_ENV), client=Broken)
        self.assertEqual(code, 1)
        self.assertIn("推播資料庫錯誤", out)
        self.assertIn("Supabase HTTP 404", out)
        self.assertIn("::error title=notify::", out)
        self.assertNotIn("vapid-private-value-must-never-be-logged", out)

    def test_post_send_record_failure_is_still_fatal(self):
        class Recorder:
            def __init__(self, url, service_key):
                pass

            def active_subscriptions(self):
                return [
                    {
                        "id": "sub-1",
                        "endpoint": "https://push.example/e",
                        "p256dh": "a",
                        "auth": "b",
                        "branch_ids": [],
                        "topic_ids": ["all:new"],
                    }
                ]

            def delivered_pairs(self, keys):
                return set()

            def notified_subscription_ids_for_batch(self, date):
                return set()

            def record_deliveries(self, subscription_id, notices, date):
                raise StorageError("Supabase HTTP 500")

            def delete_subscription(self, subscription_id):
                pass

        code, out = self.run_main(dict(self.FULL_ENV), client=Recorder)
        # 已經發出但記錄唔到 → 仍然要擋住 commit，否則日後會重複推送
        self.assertEqual(code, 1)
        self.assertIn("無法寫入發送紀錄", out)
        self.assertIn("::error title=notify::", out)

    def test_annotate_failure_escapes_workflow_command_syntax(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            annotate_failure("第一行\n第二行: 100% bad")
        line = buffer.getvalue()
        # One annotation = exactly one line; newlines are collapsed, not emitted.
        self.assertEqual(line.count("\n"), 1)
        self.assertTrue(line.endswith("\n"))
        body = line.strip()
        self.assertTrue(body.startswith("::error title=notify::"))
        self.assertIn("第一行 第二行", body)  # whitespace collapsed to a single space
        self.assertIn("%3A", body)  # ':' would otherwise end the title early
        self.assertIn("%25", body)  # '%' is the workflow-command escape character

    def test_annotate_failure_never_emits_a_raw_newline(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            annotate_failure("line one\r\nline two\n\nline three")
        self.assertEqual(buffer.getvalue().count("\n"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
