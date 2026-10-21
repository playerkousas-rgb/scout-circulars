#!/usr/bin/env python3
"""Remove TMW recruitment copy from the reviewed candidate-list title only."""
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = '屯門西區'
URL = 'https://tmw.scout-ntr.org.hk/files/2026/SOULKeeper_candidate_List.pdf'
OLD = 'SOUL Keeper 精神健康守護者課程 (Level 1) 歡迎深資/樂行童軍和領袖報名。 學員取錄名單'
TITLE = 'SOUL Keeper 精神健康守護者課程 (Level 1) 學員取錄名單'


def apply_review(cache, enrich):
    cache, enrich = copy.deepcopy(cache), copy.deepcopy(enrich)
    for row in cache.get('data', {}).get(SOURCE, []) + cache.get('notices', []):
        if (row.get('source_site') == SOURCE and
                (row.get('pdf_url') or row.get('url')) == URL and
                row.get('title') == OLD):
            row['title'] = TITLE
    entry = enrich.get(URL)
    if isinstance(entry, dict) and entry.get('title') == OLD:
        entry['title'] = TITLE
    return cache, enrich


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    paths = [ROOT / 'cache.json', ROOT / 'enrich.json']
    originals = [json.loads(p.read_text(encoding='utf-8')) for p in paths]
    for path, old, new in zip(paths, originals, apply_review(*originals)):
        if old != new:
            print(f'{path.name}: {OLD} → {TITLE}')
            if not args.dry_run:
                path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
