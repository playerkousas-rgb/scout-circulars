"""Offline regression tests for the TMW candidate-list title repair."""
import copy
import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup
import core
from fix_tmw_titles_2026_10_22 import OLD, SOURCE, TITLE, URL, apply_review

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'sources.json').read_text())['sources'][SOURCE]


class TmwTitleTests(unittest.TestCase):
    def test_clean_title_variants(self):
        for separator in ('/', '／', ' / '):
            with self.subTest(separator=separator):
                self.assertEqual(core.clean_title(OLD.replace('/', separator), CONFIG), TITLE)

    def test_listing_anchor(self):
        # Reproduce the contaminated link text without requiring the live website.
        soup = BeautifulSoup(f'<div><a href="{URL}">{OLD}</a></div>', 'html.parser')
        title = core.infer_listing_title(soup.a, soup, CONFIG)
        self.assertEqual(title, TITLE)
        record = core.make_asset_record(URL, title, CONFIG)
        self.assertEqual(record['title'], TITLE)
        self.assertEqual(record['pdf_url'], URL)

    def test_no_overbroad_removal(self):
        for title in (TITLE, '歡迎深資童軍參加精神健康課程', '精神健康守護者課程 (Level 2) 學員取錄名單'):
            self.assertEqual(core.clean_title(title, CONFIG), title)
        self.assertEqual(core.clean_title(OLD, {}), OLD)

    def test_repair_scoped_and_idempotent(self):
        row = dict(source_site=SOURCE, title=OLD, pdf_url=URL, date='2026-10-22')
        other = dict(row, pdf_url='https://example.org/other.pdf')
        cache = dict(data={SOURCE: [copy.deepcopy(row)]}, notices=[row, other])
        enrich = {URL: dict(title=OLD, categories=['announcement'])}
        before = copy.deepcopy((cache, enrich))
        fixed, enriched = apply_review(cache, enrich)
        self.assertEqual((cache, enrich), before)
        self.assertEqual(fixed['data'][SOURCE][0]['title'], TITLE)
        self.assertEqual(fixed['notices'][0]['title'], TITLE)
        self.assertEqual(fixed['notices'][1], other)
        self.assertEqual(enriched[URL]['title'], TITLE)
        self.assertEqual(enriched[URL]['categories'], ['announcement'])
        self.assertEqual(apply_review(fixed, enriched), (fixed, enriched))

    def test_checked_in_data(self):
        cache = json.loads((ROOT / 'cache.json').read_text())
        enrich = json.loads((ROOT / 'enrich.json').read_text())
        for rows in (cache['data'][SOURCE], cache['notices']):
            matches = [r for r in rows if r.get('pdf_url') == URL]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]['title'], TITLE)
        self.assertEqual(enrich[URL]['title'], TITLE)


if __name__ == '__main__':
    unittest.main()
