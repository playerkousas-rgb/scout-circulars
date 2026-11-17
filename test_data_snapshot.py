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
            if name == 'store-hidden.json':
                (self.repo / name).write_text('{"hidden": []}\n')
            else:
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

    def _push_data_branch_without_store_hidden(self):
        """手動整一個舊 data branch：全部檔都有，唯獨冇 store-hidden.json。"""
        import os
        env = dict(os.environ, GIT_INDEX_FILE=str(self.root / 'oldindex'),
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')

        def git_env(*args, input=None):
            return subprocess.check_output(['git', *args], cwd=self.repo,
                                           env=env, input=input).decode().strip()

        git_env('read-tree', '--empty')
        for name in self.module.FILES:
            if name == 'store-hidden.json':
                continue
            if name == 'cache.json':
                raw = json.dumps({'data': {'x': [{'url': 'https://example.invalid'}]},
                                  'notices': [{'url': 'https://example.invalid'}],
                                  'last_updated': '2026-10-27'}).encode()
            else:
                raw = json.dumps({'test': name}).encode()
            oid = git_env('hash-object', '-w', '--stdin', input=raw)
            git_env('update-index', '--add', '--cacheinfo', f'100644,{oid},{name}')
        for name, raw in {'vercel.json': b'{"git":{"deploymentEnabled":false},"ignoreCommand":"exit 0"}\n',
                          '.vercelignore': b'*\n'}.items():
            oid = git_env('hash-object', '-w', '--stdin', input=raw)
            git_env('update-index', '--add', '--cacheinfo', f'100644,{oid},{name}')
        tree = git_env('write-tree')
        sha = git_env('commit-tree', tree, input=b'old data\n')
        self.git('push', 'origin', f'{sha}:refs/heads/data')

    def test_load_falls_back_to_checked_in_seed_when_data_branch_lacks_store_hidden(self):
        self._push_data_branch_without_store_hidden()
        self.helper('load')   # 2026-11-15 新增檔案：唔可以令第一次 load 炸
        seed = json.loads((self.repo / 'store-hidden.json').read_text())
        self.assertEqual(seed['hidden'], [])

    def test_load_falls_back_to_default_when_no_seed_either(self):
        self._push_data_branch_without_store_hidden()
        (self.repo / 'store-hidden.json').unlink()
        self.helper('load')
        fallback = json.loads((self.repo / 'store-hidden.json').read_text())
        self.assertEqual(fallback['hidden'], [])

    def test_invalid_store_hidden_never_reaches_remote(self):
        self.helper('load')
        self.helper('publish')
        old = self.git('ls-remote', 'origin', 'refs/heads/data')
        (self.repo / 'store-hidden.json').write_text('{"hidden": "https://example.invalid"}')
        self.assertNotEqual(self.helper('publish', check=False).returncode, 0)
        self.assertEqual(old, self.git('ls-remote', 'origin', 'refs/heads/data'))

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
