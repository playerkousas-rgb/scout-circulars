"""Offline integration tests: real bare remote, no production pushes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parent / 'tools/data_snapshot.py'


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.repo = self.root / 'code'
        self.repo.mkdir()
        self.git('init', '--bare', str(self.remote), cwd=self.root)
        self.git('init', cwd=self.repo)
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('remote', 'add', 'origin', str(self.remote))
        spec = importlib.util.spec_from_file_location('snapshot', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        for name in self.module.FILES:
            (self.repo / name).write_text(json.dumps({'test': name}))
        (self.repo / 'cache.json').write_text(json.dumps({'data': {'test': [{'url': 'https://example.invalid'}]}, 'notices': [{'url': 'https://example.invalid'}], 'last_updated': '2026-10-27'}))
        (self.repo / 'source.py').write_text('print("code")')
        (self.repo / '.env').write_text('SECRET=must-not-publish')
        self.git('add', *self.module.FILES, 'source.py')
        self.git('commit', '-m', 'Code commit')
        self.head = self.git('rev-parse', 'HEAD')

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd or self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def helper(self, command, check=True):
        return subprocess.run(['python', str(SCRIPT), command], cwd=self.repo,
                              capture_output=True, text=True, check=check)

    def test_parentless_snapshot_preserves_code_and_excludes_secrets(self):
        self.helper('load')
        (self.repo / 'source.py').write_text('print("staged user code")')
        self.git('add', 'source.py')
        staged = self.git('diff', '--cached')
        self.helper('publish')
        self.assertEqual(self.git('diff', '--cached'), staged)
        first = self.git('ls-remote', 'origin', 'refs/heads/data').split()[0]
        self.helper('load')
        (self.repo / 'enrich.json').write_text('{"updated":true}')
        self.helper('publish')
        second = self.git('ls-remote', 'origin', 'refs/heads/data').split()[0]
        self.assertNotEqual(first, second)
        self.assertEqual(self.git('rev-list', '--count', second), '1')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.head)
        files = self.git('ls-tree', '--name-only', second).splitlines()
        self.assertEqual(set(files), set(self.module.FILES) | {'vercel.json', '.vercelignore'})
        self.assertNotIn('.env', files)
        self.assertEqual(self.git('show', f'{second}:enrich.json'), '{"updated":true}')

    def test_concurrent_writer_rejected(self):
        self.helper('load')
        state = self.repo / '.git/scout-data-state.json'
        original = state.read_text()
        self.helper('publish')
        state.write_text(original)  # Simulate another writer with stale load state.
        result = self.helper('publish', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing stale publication', result.stderr)

    def test_invalid_json_cannot_replace_live_snapshot(self):
        self.helper('load')
        self.helper('publish')
        old = self.git('ls-remote', 'origin', 'refs/heads/data')
        (self.repo / 'cache.json').write_text('{broken')
        self.assertNotEqual(self.helper('publish', check=False).returncode, 0)
        self.assertEqual(old, self.git('ls-remote', 'origin', 'refs/heads/data'))

    def test_empty_core_rejected(self):
        self.helper('load')
        (self.repo / 'fingerprints.json').write_text('{}')
        self.assertNotEqual(self.helper('publish', check=False).returncode, 0)


if __name__ == '__main__':
    unittest.main()
