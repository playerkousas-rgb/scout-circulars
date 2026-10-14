#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回歸測試：Vercel Usage Report 唔可以再日日觸發「Run failed」（2026-10-09 用戶要求）。

背景：10-06 起 VERCEL_TOKEN／API 問題令 `on: push` 嘅 usage report 每次都
exit 1 →「Run failed」郵件轟炸。呢個係唯讀監察報告，API 讀唔到只係資訊性
失敗，應該出 warning（附修復指引）＋ exit 0，唔好 fail run。

釘住四點：
1. 冇 secrets → warning「已跳過」＋ exit 0（原有行為，唔好改壞）；
2. API 401／403（token 過期／無權限）→ ::warning::（附 VERCEL_TOKEN 修復指引）
   ＋ exit 0，唔准出 ::error::；
3. API 404（project 冇咗）→ warning 附 VERCEL_PROJECT_ID 指引 ＋ exit 0；
4. 網絡／未知例外 → 一樣 warning ＋ exit 0。

action 工具（vercel_prune／vercel_retention）不在此限：佢哋真係要執行變更，
失敗值得大聲。

用法：python3 test_vercel_usage_report.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).parent
SCRIPT_PATH = BASE_DIR / ".github" / "scripts" / "vercel_usage_report.py"

spec = importlib.util.spec_from_file_location("vercel_usage_report", SCRIPT_PATH)
vur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vur)


def http_error(code: int, body: bytes = b'{"error":{"message":"denied"}}') -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.vercel.com/v6/deployments", code, "err", {}, io.BytesIO(body),
    )


def run_main(env: dict | None, side_effect) -> tuple[int, str]:
    """設定 env ＋ mock Vercel.call，跑 main()，回傳（exit code, stdout）。"""
    output = io.StringIO()
    env_patch = mock.patch.dict(os.environ, env or {}, clear=False)
    with env_patch, redirect_stdout(output):
        if env is None:
            for key in ("VERCEL_TOKEN", "VERCEL_PROJECT_ID", "VERCEL_TEAM_ID", "VERCEL_ORG_ID"):
                os.environ.pop(key, None)
        with mock.patch.object(vur.Vercel, "call", side_effect=side_effect):
            code = vur.main()
    return code, output.getvalue()


class VercelUsageReportSoftFailTests(unittest.TestCase):
    def test_missing_secrets_skip_cleanly(self):
        code, out = run_main(None, AssertionError("唔應該打 API"))
        self.assertEqual(code, 0)
        self.assertIn("::warning::", out)
        self.assertIn("已跳過", out)

    def test_token_rejected_warns_with_fix_hint(self):
        for status in (401, 403):
            with self.subTest(status=status):
                code, out = run_main(
                    {"VERCEL_TOKEN": "bad", "VERCEL_PROJECT_ID": "prj_x"},
                    http_error(status),
                )
                self.assertEqual(code, 0)
                self.assertIn("::warning::", out)
                self.assertNotIn("::error::", out)
                self.assertIn("VERCEL_TOKEN", out)
                self.assertIn("重新生成", out)

    def test_project_not_found_points_to_project_id(self):
        code, out = run_main(
            {"VERCEL_TOKEN": "ok", "VERCEL_PROJECT_ID": "prj_gone"},
            http_error(404),
        )
        self.assertEqual(code, 0)
        self.assertIn("::warning::", out)
        self.assertIn("VERCEL_PROJECT_ID", out)

    def test_network_error_soft_fails(self):
        code, out = run_main(
            {"VERCEL_TOKEN": "ok", "VERCEL_PROJECT_ID": "prj_x"},
            OSError("network down"),
        )
        self.assertEqual(code, 0)
        self.assertIn("::warning::", out)
        self.assertNotIn("::error::", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
