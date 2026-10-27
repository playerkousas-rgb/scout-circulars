#!/usr/bin/env python3
"""Local scheduled scraper: latest data in, finite backup out, no code commits.

Runs from the .bat logging wrapper. A conflicting data writer is never
force-overwritten. Failed publication keeps a local dated rescue snapshot.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys

import data_snapshot


def run(*args):
    subprocess.run(args, check=True)


def backup():
    now = datetime.now(timezone.utc)
    folder = Path('logs/data-backups') / now.strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    for name in data_snapshot.FILES:
        if Path(name).exists():
            shutil.copy2(name, folder / name)
    cutoff = now.timestamp() - timedelta(days=30).total_seconds()
    for old in folder.parent.iterdir():
        if old.is_dir() and old.stat().st_mtime < cutoff:
            shutil.rmtree(old)
    print(f'Rescue snapshot saved: {folder}', flush=True)


def main():
    # Keep source self-updating, but never stage/commit/push source or user edits.
    # Abort rather than rewriting local work; data leftovers are backed up first.
    backup()
    run('git', 'restore', '--staged', '--', *data_snapshot.FILES)
    run('git', 'restore', '--', *data_snapshot.FILES)
    run('git', 'pull', '--ff-only', 'origin', 'main')
    data_snapshot.load()  # Fail closed on network errors; never overwrite live from stale data.
    try:
        run(sys.executable, 'core.py', '--force')
        try:
            run(sys.executable, 'tools/scrape_appstore.py')
        except subprocess.CalledProcessError:
            print('App Store unavailable; continuing PDF enrichment.', flush=True)
        run(sys.executable, 'enrich.py', '--verbose', '--apply-title-fixes')
    finally:
        backup()  # Also preserve partial results for recovery; never auto-publish a failed run.
    data_snapshot.publish()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Local scrape failed; see logs/data-backups for recovery: {exc}', file=sys.stderr)
        raise SystemExit(1)
