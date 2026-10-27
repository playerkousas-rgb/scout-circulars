import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import json

spec = importlib.util.spec_from_file_location('storage', Path(__file__).parent / '.github/scripts/story_storage.py')
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


class StorageTests(unittest.TestCase):
    def test_cleanup_only_expired_managed_prefixes(self):
        with patch.object(storage, 'ensure_bucket'), patch.object(storage, 'list_objects', return_value=[
            {'name': '20200101T000000Z-123-1'}, {'name': '29990101T000000Z-123-1'}, {'name': 'other-data'}
        ]), patch.object(storage, 'remove') as remove:
            storage.cleanup()
            remove.assert_called_once_with('20200101T000000Z-123-1')

    def test_removal_is_scoped(self):
        with self.assertRaises(ValueError):
            storage.remove('../other-bucket')
        with patch.object(storage, 'list_objects', return_value=[{'id': 'x', 'name': 'a.jpg'}]), patch.object(storage, 'request') as req:
            storage.remove('20261027T000000Z-123-1')
            req.assert_called_once_with('DELETE', 'object/scout-story-temp', {'prefixes': ['20261027T000000Z-123-1/a.jpg']})

    def test_upload_only_manifest_jpegs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'a.jpg').write_bytes(b'\xff\xd8\xfftest')
            (folder / 'secret.png').write_bytes(b'not for upload')
            manifest = folder / 'manifest.json'
            manifest.write_text(json.dumps({'items': [{'instagram_file': 'a.jpg'}]}))
            with patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_OUTPUT': str(folder / 'out'), 'SUPABASE_URL': 'https://test.example'}), patch.object(storage, 'cleanup'), patch.object(storage, 'request') as req:
                storage.upload(manifest)
                self.assertEqual(req.call_count, 1)
                self.assertEqual(req.call_args.args[3], 'image/jpeg')
                self.assertIn('/storage/v1/object/public/scout-story-temp/', (folder / 'out').read_text())

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'manifest.json'
            manifest.write_text(json.dumps({'items': [{'instagram_file': '../secret.jpg'}]}))
            with patch.dict(os.environ, {'GITHUB_RUN_ID': '123'}), patch.object(storage, 'cleanup'), patch.object(storage, 'request') as req:
                with self.assertRaises(ValueError):
                    storage.upload(manifest)
                req.assert_not_called()


if __name__ == '__main__':
    unittest.main()
