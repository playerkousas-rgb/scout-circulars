#!/usr/bin/env python3
"""Dedicated temporary JPEG storage; never stores images in Git.

Uses existing Actions SUPABASE_URL/SUPABASE_SERVICE_KEY. Only touches the
scout-story-temp bucket. A daily cleanup job removes runs older than 24 hours.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote

BUCKET = 'scout-story-temp'


def request(method, path, payload=None, mime='application/json'):
    base = os.environ['SUPABASE_URL'].rstrip('/')
    if not base.startswith('https://'):
        raise ValueError('SUPABASE_URL must use HTTPS')
    key = os.environ['SUPABASE_SERVICE_KEY']
    data = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if payload is not None else None)
    req = Request(base + '/storage/v1/' + path, data=data, method=method,
                  headers={'Authorization': 'Bearer ' + key, 'apikey': key,
                           'Content-Type': mime, 'Cache-Control': 'max-age=60'})
    try:
        with urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        # Never log response bodies/headers: they may contain credentials.
        raise RuntimeError(f'Story storage {method} failed: HTTP {exc.code}') from None


def ensure_bucket():
    buckets = request('GET', 'bucket')
    existing = next((b for b in buckets if b['id'] == BUCKET), None)
    if existing:
        if not existing.get('public'):
            raise RuntimeError('Story bucket must be public for Meta image fetches')
        return
    request('POST', 'bucket', {'id': BUCKET, 'name': BUCKET, 'public': True,
                              'file_size_limit': 8388608,
                              'allowed_mime_types': ['image/jpeg']})


def list_objects(prefix):
    result = []
    while True:
        page = request('POST', f'object/list/{BUCKET}',
                       {'prefix': prefix, 'limit': 100, 'offset': len(result),
                        'sortBy': {'column': 'name', 'order': 'asc'}})
        result.extend(page)
        if len(page) < 100:
            return result


def remove(prefix):
    if not re.fullmatch(r'\d{8}T\d{6}Z-[A-Za-z0-9-]+', prefix):
        raise ValueError('Invalid temporary run prefix')
    paths = [prefix + '/' + o['name'] for o in list_objects(prefix) if o.get('id')]
    for start in range(0, len(paths), 100):
        request('DELETE', f'object/{BUCKET}', {'prefixes': paths[start:start+100]})


def cleanup():
    ensure_bucket()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for folder in list_objects(''):
        name = folder['name']
        if re.fullmatch(r'\d{8}T\d{6}Z-[A-Za-z0-9-]+', name):
            created = datetime.strptime(name[:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            if created < cutoff:
                remove(name)


def upload(manifest):
    cleanup()
    prefix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    doc = json.loads(manifest.read_text(encoding='utf-8'))
    for item in doc['items']:
        name = item['instagram_file']
        if Path(name).name != name or not name.endswith('.jpg'):
            raise ValueError('Only manifest JPEG basenames may be uploaded')
        raw = (manifest.parent / name).read_bytes()
        if not raw.startswith(b'\xff\xd8\xff') or len(raw) > 8388608:
            raise ValueError('Invalid or oversized JPEG')
        request('POST', f'object/{BUCKET}/{prefix}/{quote(name)}', raw, 'image/jpeg')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        out.write(f'prefix={prefix}\n')
        out.write(f'base_url={os.environ["SUPABASE_URL"].rstrip("/")}/storage/v1/object/public/{BUCKET}/{prefix}/\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['upload', 'cleanup', 'remove'])
    p.add_argument('--manifest', type=Path)
    p.add_argument('--prefix')
    a = p.parse_args()
    try:
        if a.command == 'upload':
            upload(a.manifest)
        elif a.command == 'remove':
            remove(a.prefix)
        else:
            cleanup()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(f'Temporary Story storage failed: {exc}')
