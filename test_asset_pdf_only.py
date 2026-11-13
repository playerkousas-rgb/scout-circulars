import unittest

import core


class AssetPdfOnlyTests(unittest.TestCase):
    def test_rejects_excel_and_other_known_non_pdf_downloads(self):
        for extension in (".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx", ".csv", ".zip"):
            with self.subTest(extension=extension):
                self.assertIsNone(
                    core.make_asset_record(f"https://example.org/forms/application{extension}?v=2", "報名表", {})
                )

    def test_keeps_pdf_downloads(self):
        record = core.make_asset_record("https://example.org/notices/circular.PDF?download=1", "活動通告", {})
        self.assertEqual(record, {
            "pdf_url": "https://example.org/notices/circular.PDF?download=1",
            "title": "活動通告",
        })

    def test_keeps_opaque_download_endpoints_that_may_serve_pdf(self):
        record = core.make_asset_record("https://example.org/circulars/download/?wpdmdl=5653", "活動通告", {})
        self.assertIsNotNone(record)


if __name__ == "__main__":
    unittest.main()
