"""Proxy bootstrap fallback must never weaken the notice allowlist."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from api import pdf_proxy

DEFAULT = 'https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/data/cache.json'


class ProxySnapshotTests(unittest.TestCase):
    def tearDown(self):
        pdf_proxy._cache_urls = set()
        pdf_proxy._cache_loaded_at = 0

    def test_default_404_uses_main_seed_allowlist(self):
        body = io.BytesIO(json.dumps({'data': {'source': [{'url': 'https://example.invalid/notice'}]}}).encode())
        with patch.object(pdf_proxy, 'RAW_CACHE_URL', DEFAULT), patch.object(pdf_proxy.urllib.request, 'urlopen', side_effect=[HTTPError(DEFAULT, 404, 'missing', {}, None), body]) as fetch:
            result = pdf_proxy.refresh_allowed_urls(force=True)
            self.assertEqual(result, {'https://example.invalid/notice'})
            self.assertEqual(fetch.call_args_list[1].args[0].full_url, DEFAULT.replace('/data/', '/main/'))

    def test_other_http_errors_fail_closed(self):
        with patch.object(pdf_proxy, 'RAW_CACHE_URL', DEFAULT), patch.object(pdf_proxy.urllib.request, 'urlopen', side_effect=HTTPError(DEFAULT, 500, 'error', {}, None)) as fetch:
            with self.assertRaises(HTTPError):
                pdf_proxy.refresh_allowed_urls(force=True)
            self.assertEqual(fetch.call_count, 1)

    def test_custom_url_never_rewritten(self):
        with patch.object(pdf_proxy, 'RAW_CACHE_URL', 'https://custom.invalid/cache.json'), patch.object(pdf_proxy.urllib.request, 'urlopen', side_effect=HTTPError('custom', 404, 'missing', {}, None)) as fetch:
            with self.assertRaises(HTTPError):
                pdf_proxy.refresh_allowed_urls(force=True)
            self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
