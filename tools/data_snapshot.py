#!/usr/bin/env python3
"""Latest-only public data snapshot. Never checks out or rewrites the code branch.

Uses a parentless commit and an explicit lease: concurrent writers fail rather
than overwrite newer data. Run load before scraping/publishing. No secrets or
arbitrary working-tree files can enter the snapshot.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

FILES = ('cache.json', 'enrich.json', 'fingerprints.json',
         'subscription_stats.json', 'appstore.json', 'story-queue.json',
         'store-hidden.json')
CORE = FILES[:3]


def git(*args, **kwargs):
    return subprocess.check_output(['git', *args], **kwargs).decode().strip()


def root():
    return Path(git('rev-parse', '--show-toplevel'))


def state_path():
    return Path(git('rev-parse', '--absolute-git-dir')) / 'scout-data-state.json'


def remote_tip():
    result = git('ls-remote', '--heads', 'origin', 'refs/heads/data')
    return result.split()[0] if result else ''


def validate(name, raw):
    value = json.loads(raw)
    if not isinstance(value, (dict, list)):
        raise ValueError(f'{name}: expected JSON object/array')
    if name in CORE and not isinstance(value, dict):
        raise ValueError(f'{name}: expected JSON object')
    if name in CORE and not value:
        raise ValueError(f'{name}: refusing empty core snapshot')
    if name == 'cache.json':
        if not isinstance(value.get('data'), dict) or not isinstance(value.get('notices'), list):
            raise ValueError('cache.json: missing grouped data or flat notices')
        if not value['notices'] or not value.get('last_updated'):
            raise ValueError('cache.json: refusing empty notices or missing update time')
    if name == 'store-hidden.json':
        # APP STORE 收埋咗嘅曾經上架 app 清單；前端顯示層靠佢收埋。
        if not isinstance(value, dict):
            raise ValueError('store-hidden.json: expected JSON object')
        hidden = value.get('hidden')
        if not isinstance(hidden, list) or not all(isinstance(u, str) for u in hidden):
            raise ValueError('store-hidden.json: expected {"hidden": [url, ...]} with string URLs')
    return raw


def load():
    base = root()
    sha = remote_tip()  # Network/auth errors must NOT silently fall back.
    if sha:
        git('fetch', '--depth=1', 'origin', 'refs/heads/data')
        sha = git('rev-parse', 'FETCH_HEAD')
        blobs = {}
        for name in FILES:
            try:
                raw = subprocess.check_output(['git', 'show', f'{sha}:{name}'])
            except subprocess.CalledProcessError:
                # 首次引入 store-hidden.json（2026-11-15）：origin/data 仲未有呢個檔，
                # 沿用 main 分支入面嘅種子（空 hidden 清單），唔好令第一次 load 炸。
                # 其他檔缺咗照樣照錯（唔可以静靜哋用舊檔頂替）。
                if name != 'store-hidden.json':
                    raise
                seed = base / name
                raw = seed.read_bytes() if seed.exists() else b'{"hidden": []}\n'
                print('Bootstrap: data branch 未有 store-hidden.json，沿用 repo 種子空清單')
            blobs[name] = validate(name, raw)
        # Validate the entire snapshot before replacing any working files.
        for name, raw in blobs.items():
            (base / name).write_bytes(raw)
    else:
        for name in FILES:
            validate(name, (base / name).read_bytes())
        print('Bootstrap: data branch absent; using checked-in seed files.')
    state_path().write_text(json.dumps({'sha': sha}))
    print(f'Loaded data snapshot: {sha or "bootstrap"}')


def publish():
    base = root()
    expected = json.loads(state_path().read_text())['sha']
    # The complete allowlist is published atomically in one tree.
    blobs = {name: validate(name, (base / name).read_bytes()) for name in FILES}
    if remote_tip() != expected:
        raise RuntimeError('Data changed since load; refusing stale publication. Reload and re-run.')
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / 'index'),
                   GIT_AUTHOR_NAME='scout-data', GIT_AUTHOR_EMAIL='data@scout-circulars',
                   GIT_COMMITTER_NAME='scout-data', GIT_COMMITTER_EMAIL='data@scout-circulars')
        git('read-tree', '--empty', env=env)
        blobs['vercel.json'] = b'{"git":{"deploymentEnabled":false},"ignoreCommand":"exit 0"}\n'
        blobs['.vercelignore'] = b'*\n'
        for name, raw in blobs.items():
            oid = git('hash-object', '-w', '--stdin', input=raw)
            git('update-index', '--add', '--cacheinfo', f'100644,{oid},{name}', env=env)
        tree = git('write-tree', env=env)
        sha = git('commit-tree', tree, input=b'Daily data snapshot [skip ci]\n', env=env)
        # No parent supplied to commit-tree => exactly one reachable commit.
        git('push', f'--force-with-lease=refs/heads/data:{expected}', 'origin', f'{sha}:refs/heads/data')
    state_path().write_text(json.dumps({'sha': sha}))
    print(f'Published data snapshot: {sha}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['load', 'publish', 'baseline'])
    args = parser.parse_args()
    try:
        {'load': load, 'publish': publish,
         'baseline': lambda: print(json.loads(state_path().read_text())['sha'] or 'HEAD')}[args.command]()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Data snapshot failed: {exc}')
