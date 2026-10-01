#!/usr/bin/env python3
"""Publish every rendered, complete Story item through Meta's Instagram API.

Images are JPEGs on the public `stories` branch because Meta fetches `image_url`
from a public server and its Content Publishing API accepts JPEG (not PNG).
Each item gets one container-create call and one publish call. There are no
retries, delayed retries, or re-queue operations; a failed item is reported and
processing continues with the next distinct item.

Container creation is asynchronous: Meta downloads and processes `image_url`
in the background, so the container only becomes publishable once its
`status_code` reaches FINISHED. Publishing earlier returns HTTP 400 with
`code 9007 / error_subcode 2207027` ("媒體素材尚未準備好發佈"), which is exactly
how the 2026-10-01 scheduled run lost all five Stories. Between the single
create call and the single publish call this script therefore polls
`GET /{container-id}?fields=status_code,status`. That poll is a readiness wait
required by Meta's API, not a publish retry: each item still gets exactly one
create attempt and one publish attempt, and ERROR/EXPIRED containers are
reported with Meta's own reason instead of being re-created.

Required environment variables (set as GitHub Actions secrets):
  INSTAGRAM_USER_ID       Instagram professional-account user ID
  INSTAGRAM_ACCESS_TOKEN  token with content-publishing permission
Optional repository variables:
  INSTAGRAM_GRAPH_API_BASE     https://graph.facebook.com (default) or
                               https://graph.instagram.com
  INSTAGRAM_GRAPH_API_VERSION  v25.0 (default)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

DEFAULT_API_BASE = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v25.0"
ALLOWED_API_BASES = {
    "https://graph.facebook.com",
    "https://graph.instagram.com",
}
TIMEOUT_SECONDS = 60
# Readiness wait between the one create call and the one publish call.
# Meta finishes a 1080x1920 JPEG in seconds; 120s of headroom covers a slow
# fetch of raw.githubusercontent.com without letting a stuck container hang
# the whole run (5 stuck items worst case = 10 minutes, inside the 60-minute
# job timeout).
STATUS_POLL_INTERVAL_SECONDS = 3.0
STATUS_POLL_TIMEOUT_SECONDS = 120.0
READY_STATUS = "FINISHED"
DEAD_STATUSES = {"ERROR", "EXPIRED"}


class PublishError(RuntimeError):
    """A single configuration, transport, or Graph API error."""


def _config(env: dict[str, str] | None = None) -> tuple[str, str, str, str]:
    env = env or os.environ
    user_id = (env.get("INSTAGRAM_USER_ID") or "").strip()
    token = (env.get("INSTAGRAM_ACCESS_TOKEN") or "").strip()
    api_base = (env.get("INSTAGRAM_GRAPH_API_BASE") or DEFAULT_API_BASE).strip().rstrip("/")
    api_version = (env.get("INSTAGRAM_GRAPH_API_VERSION") or DEFAULT_API_VERSION).strip()

    if not user_id or not re.fullmatch(r"\d+", user_id):
        raise PublishError("INSTAGRAM_USER_ID is missing or is not a numeric Instagram user ID")
    if not token:
        raise PublishError("INSTAGRAM_ACCESS_TOKEN is not configured")
    if api_base not in ALLOWED_API_BASES:
        raise PublishError(
            "INSTAGRAM_GRAPH_API_BASE must be https://graph.facebook.com or "
            "https://graph.instagram.com"
        )
    if not re.fullmatch(r"v\d+\.\d+", api_version):
        raise PublishError("INSTAGRAM_GRAPH_API_VERSION must look like v25.0")
    return user_id, token, api_base, api_version


def _parse_json_response(raw: bytes, token: str) -> dict:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError("Meta API returned a non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise PublishError("Meta API returned an unexpected response")
    if isinstance(parsed.get("error"), dict):
        error = parsed["error"]
        message = str(error.get("message") or "Graph API error").replace(token, "[redacted]")
        code = error.get("code")
        suffix = f" (code {code})" if code is not None else ""
        raise PublishError(f"{message}{suffix}")
    return parsed


def _post_graph(edge: str, fields: dict[str, str], *, user_id: str, token: str,
                api_base: str, api_version: str) -> dict:
    url = f"{api_base}/{api_version}/{user_id}/{edge}"
    data = urlencode(fields).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "scout-circulars-instagram-story/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return _parse_json_response(response.read(), token)
    except HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace").replace(token, "[redacted]")
        detail = body[:1000] if body else str(exc.reason)
        raise PublishError(f"Meta API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        # Do not retry transport errors: this workflow gets one scheduled run.
        reason = str(exc.reason).replace(token, "[redacted]")
        raise PublishError(f"Meta API connection failed: {reason}") from exc


def _get_graph(node: str, params: dict[str, str], *, token: str,
               api_base: str, api_version: str) -> dict:
    url = f"{api_base}/{api_version}/{node}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "scout-circulars-instagram-story/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return _parse_json_response(response.read(), token)
    except HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace").replace(token, "[redacted]")
        detail = body[:1000] if body else str(exc.reason)
        raise PublishError(f"Meta API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        reason = str(exc.reason).replace(token, "[redacted]")
        raise PublishError(f"Meta API connection failed: {reason}") from exc


def _wait_until_finished(creation_id: str, *, token: str, api_base: str,
                         api_version: str, sleep=None, monotonic=None) -> str:
    """Block until the media container is publishable.

    Returns the final status_code (always FINISHED) or raises PublishError with
    Meta's own status text, so an unreachable or rejected image is diagnosed in
    the run log instead of surfacing as an opaque 9007/2207027 publish failure.
    """
    # Resolved at call time so tests can patch the clock and the sleeper.
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + STATUS_POLL_TIMEOUT_SECONDS
    status_code = ""
    while True:
        payload = _get_graph(
            creation_id,
            {"fields": "status_code,status"},
            token=token,
            api_base=api_base,
            api_version=api_version,
        )
        status_code = str(payload.get("status_code") or "").strip().upper()
        detail = str(payload.get("status") or "").strip()
        if status_code == READY_STATUS:
            return status_code
        if status_code in DEAD_STATUSES:
            raise PublishError(
                f"Media container {status_code}: {detail or 'Meta gave no status detail'}"
            )
        if monotonic() >= deadline:
            raise PublishError(
                f"Media container still {status_code or 'UNKNOWN'} after "
                f"{int(STATUS_POLL_TIMEOUT_SECONDS)}s"
                + (f": {detail}" if detail else "")
            )
        sleep(STATUS_POLL_INTERVAL_SECONDS)


def _image_url(base_url: str, filename: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise PublishError("Story image base URL must be a public HTTPS URL without query or fragment")
    if parsed.username or parsed.password:
        raise PublishError("Story image base URL must not contain credentials")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", filename, flags=re.IGNORECASE):
        raise PublishError(f"Manifest has an invalid JPEG filename: {filename!r}")
    return base_url.rstrip("/") + "/" + quote(filename, safe="")


def _manifest_items(manifest_path: Path) -> list[dict]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"Cannot read Story manifest: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
        raise PublishError("Story manifest has no items list")

    items = manifest["items"]
    # Validate all local files before the first API call, avoiding a partial
    # batch caused by a bad or missing renderer output.
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PublishError(f"Manifest item {index + 1} is not an object")
        filename = str(item.get("instagram_file") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", filename, flags=re.IGNORECASE):
            raise PublishError(f"Manifest item {index + 1} has no valid instagram_file JPEG")
        if not (manifest_path.parent / filename).is_file():
            raise PublishError(f"Manifest JPEG is missing: {filename}")
        if not str(item.get("title") or "").strip():
            raise PublishError(f"Manifest item {index + 1} has no title")
    return items


def publish_manifest(manifest_path: Path, base_url: str,
                     env: dict[str, str] | None = None,
                     sleep=None) -> tuple[int, int]:
    items = _manifest_items(manifest_path)
    if not items:
        print("No eligible Story images; nothing to publish.")
        return 0, 0

    user_id, token, api_base, api_version = _config(env)
    # Pre-validate every public URL before creating any containers.
    urls = [_image_url(base_url, str(item["instagram_file"])) for item in items]
    published = 0
    failures = 0

    for item, image_url in zip(items, urls):
        title = str(item.get("title") or "(untitled)").replace("\n", " ")[:100]
        try:
            container = _post_graph(
                "media",
                {"image_url": image_url, "media_type": "STORIES"},
                user_id=user_id,
                token=token,
                api_base=api_base,
                api_version=api_version,
            )
            creation_id = str(container.get("id") or "")
            if not creation_id:
                raise PublishError("Meta API did not return a media container ID")

            # Readiness wait, not a retry: Meta rejects media_publish until the
            # container finishes downloading and processing image_url.
            wait_started = time.monotonic()
            _wait_until_finished(
                creation_id,
                token=token,
                api_base=api_base,
                api_version=api_version,
                sleep=sleep,
            )
            ready_after = time.monotonic() - wait_started

            result = _post_graph(
                "media_publish",
                {"creation_id": creation_id},
                user_id=user_id,
                token=token,
                api_base=api_base,
                api_version=api_version,
            )
            media_id = str(result.get("id") or "")
            if not media_id:
                raise PublishError("Meta API did not return a published media ID")
            published += 1
            print(
                f"✅ Published Story {published}/{len(items)}: {title} "
                f"(media {media_id}, container ready in {ready_after:.1f}s)"
            )
        except PublishError as exc:
            # This item is not retried or re-queued. Continue once with the next
            # distinct complete notice, then return a failing run summary.
            failures += 1
            print(f"❌ Story failed (no retry): {title}: {exc}", file=sys.stderr)

    print(f"Story publish summary: {published} published, {failures} failed; no retries.")
    return published, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish all JPEG Stories in a manifest via Meta Graph API")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--base-url", required=True,
                        help="public HTTPS directory containing the manifest's JPEGs")
    args = parser.parse_args(argv)

    try:
        _, failures = publish_manifest(args.manifest, args.base_url)
    except PublishError as exc:
        print(f"❌ Instagram Story publishing stopped: {exc}", file=sys.stderr)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
