import io
import unittest
import urllib.error
from unittest.mock import patch

import api.pdf_proxy as pdf_proxy
import core
import enrich
import story_queue
from tools.apply_notice_corrections import apply_corrections


class _FakeHTTPResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(body))}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class YuenLongWestDoublePdfTests(unittest.TestCase):
    YLW_BAD_15 = "https://www.ylw-scout.org.hk/circular/activity15-2026.pdf.pdf"
    YLW_GOOD_15 = "https://www.ylw-scout.org.hk/circular/activity15-2026.pdf"
    HKW_REAL_DOUBLE = (
        "https://group.scout.org.hk/hkw/wp-content/uploads/2018/09/"
        "HKW2018SCIR013_2019年童軍嘉爾頓錦標賽港島西區選拔賽露營章技能組考驗安排.pdf.pdf"
    )

    def setUp(self):
        core._DOUBLE_PDF_PROBE_CACHE.clear()

    def test_sanitize_url_collapses_ylw_circular_double_pdf_only(self):
        self.assertEqual(core.sanitize_url(self.YLW_BAD_15), self.YLW_GOOD_15)
        self.assertEqual(
            core.sanitize_url("https://ylw-scout.org.hk/circular/training06-2026.PDF.pdf?v=2"),
            "https://ylw-scout.org.hk/circular/training06-2026.pdf",
        )
        # 港島西區／筲箕灣區／大埔南區歷史真檔名係 .pdf.pdf，唔可以盲目剝走
        self.assertEqual(core.sanitize_url(self.HKW_REAL_DOUBLE), self.HKW_REAL_DOUBLE)

    def test_repair_broken_double_pdf_probes_other_domains_safely(self):
        broken = "https://example.org/notices/cir01.pdf.pdf"
        fixed = "https://example.org/notices/cir01.pdf"

        with patch.object(
            core,
            "_probe_pdf_magic",
            side_effect=lambda u, verify_ssl=True: (404, False) if u == broken else (200, True),
        ):
            self.assertEqual(core.repair_broken_double_pdf_url(broken), fixed)

        core._DOUBLE_PDF_PROBE_CACHE.clear()
        with patch.object(core, "_probe_pdf_magic", return_value=(200, True)) as mock_probe:
            self.assertEqual(core.repair_broken_double_pdf_url(self.HKW_REAL_DOUBLE), self.HKW_REAL_DOUBLE)
            self.assertEqual(mock_probe.call_count, 1)

        core._DOUBLE_PDF_PROBE_CACHE.clear()
        with patch.object(core, "_probe_pdf_magic", return_value=(None, False)):
            self.assertEqual(core.repair_broken_double_pdf_url(broken), broken)

    def test_fullwidth_dollar_fee_extracted_for_ylw_activity15(self):
        pdf_text = (
            "由 :區總監\n活動通告第15/2026號\n"
            "二 ） 參加資格： 本區已宣誓及持有效幼童軍記錄冊之幼童軍成員。\n"
            "八 ） 費 用： 每隊港幣貳佰圓正(＄200.00)。\n"
            "十 ） 截止日期： 2026年 11月 21日 ( 星期六)\n"
        )
        fields = enrich.extract_fields(
            pdf_text,
            "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
            source="元朗西區",
        )
        self.assertEqual(fields["deadline"], "2026-11-21")
        self.assertEqual(fields["audience"], "幼童軍")
        self.assertEqual(enrich.normalize_fee(fields["fee"]), "HK$200.00")

    def test_enrich_download_falls_back_on_double_pdf_404(self):
        calls = []

        def fake_urlopen(req, timeout=25):
            calls.append(req.full_url)
            if req.full_url.endswith(".pdf.pdf"):
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return _FakeHTTPResponse(b"%PDF-1.7 fake body")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            data = enrich.download(self.YLW_BAD_15)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(calls, [self.YLW_BAD_15, self.YLW_GOOD_15])

    def test_pdf_proxy_falls_back_on_double_pdf_404(self):
        sample_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"

        def fake_urlopen(req, timeout=20):
            if req.full_url.endswith(".pdf.pdf"):
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return _FakeHTTPResponse(sample_pdf, status=200)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(pdf_proxy.fetch_pdf(self.YLW_BAD_15), sample_pdf)
            chunk, eof = pdf_proxy.fetch_pdf_slice(self.YLW_BAD_15, 0, 64)
            self.assertEqual(chunk, sample_pdf)
            self.assertTrue(eof)

    def test_apply_corrections_migrates_ylw_urls_preserves_dates_and_enables_story(self):
        cache = {
            "data": {
                "元朗西區": [
                    {
                        "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
                        "url": self.YLW_BAD_15,
                        "pdf_url": self.YLW_BAD_15,
                        "date": "2026-11-16",
                        "captured_date": "2026-11-16",
                        "source_site": "元朗西區",
                        "region": "新界地域",
                    },
                    # 模擬重跑後新舊 URL 並存：必須合併並保留較早入庫日
                    {
                        "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
                        "url": self.YLW_GOOD_15,
                        "pdf_url": self.YLW_GOOD_15,
                        "date": "2026-11-17",
                        "captured_date": "2026-11-17",
                        "source_site": "元朗西區",
                        "region": "新界地域",
                    },
                ]
            },
            "notices": [
                {
                    "source_site": "元朗西區",
                    "region": "新界地域",
                    "pdf_url": self.YLW_BAD_15,
                    "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
                    "captured_date": "2026-11-16",
                }
            ],
        }
        enrich_map = {
            self.YLW_BAD_15: {
                "source": "元朗西區",
                "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
                "deadline": "",
                "audience": "",
                "fee": "",
                "error": "download: HTTPError",
            }
        }

        summary = apply_corrections(enrich_map, cache)
        self.assertGreater(summary.get("migrated_urls", 0), 0)
        self.assertEqual(summary.get("repaired_pdfs"), 1)

        self.assertEqual(len(cache["data"]["元朗西區"]), 1)
        item = cache["data"]["元朗西區"][0]
        self.assertEqual(item["pdf_url"], self.YLW_GOOD_15)
        self.assertEqual(item["url"], self.YLW_GOOD_15)
        self.assertEqual(item["captured_date"], "2026-11-16")
        self.assertEqual(item["date"], "2026-11-16")
        self.assertEqual(cache["notices"][0]["pdf_url"], self.YLW_GOOD_15)

        self.assertNotIn(self.YLW_BAD_15, enrich_map)
        repaired = enrich_map[self.YLW_GOOD_15]
        self.assertEqual(repaired["error"], "")
        self.assertEqual(repaired["deadline"], "2026-11-21")
        self.assertEqual(repaired["audience"], "幼童軍")
        self.assertEqual(repaired["fee"], "HK$200.00")

        stories = story_queue.pick_today(cache, "2026-11-16", enrich_map)
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["url"], self.YLW_GOOD_15)

        # 冪等：第二次跑唔再重複計入 migrated_urls / repaired_pdfs
        second = apply_corrections(enrich_map, cache)
        self.assertNotIn("migrated_urls", second)
        self.assertNotIn("repaired_pdfs", second)


if __name__ == "__main__":
    unittest.main()
