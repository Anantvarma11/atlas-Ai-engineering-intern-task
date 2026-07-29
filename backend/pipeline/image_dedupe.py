"""
Content-based dedup for merged supplier image URLs.

Why
---
When two suppliers both list a hotel, each hosts its own copy of that
hotel's photos under a different CDN path (different supplier id, different
index) — the *same* physical photo, re-uploaded, at two different URLs.
`_merge_list`'s exact-string dedup (see merge.py) can't catch that: the
strings just don't match. Left alone, a hotel's photo gallery shows the
same shot twice (or more).

This fetches a small byte range per URL — not the whole image — and
fingerprints it (reported total size + MD5 of the first few KB), which is
enough to catch byte-identical rehosts cheaply. Fingerprints are cached to
disk (pipeline/cache/image_fingerprints.json, committed) so a pipeline
rebuild never re-fetches a URL it's already seen.

Fails soft: a URL that can't be fetched (dead link, timeout, offline
rebuild) is fingerprinted as None and kept rather than dropped — this pass
only ever removes a photo it positively confirmed as a duplicate.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "cache" / "image_fingerprints.json"
_RANGE_BYTES = 4096
_TIMEOUT_S = 5.0
_WORKERS = 24

_cache: dict[str, str | None] = {}
_cache_loaded = False
_cache_dirty = False


def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if CACHE_PATH.exists():
        try:
            _cache = json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            _cache = {}
    _cache_loaded = True


def _save_cache() -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(_cache, sort_keys=True))


def _fingerprint(url: str) -> str | None:
    """`<reported-total-size>:<md5 of first _RANGE_BYTES>`, or None on any failure."""
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{_RANGE_BYTES - 1}"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            chunk = resp.read(_RANGE_BYTES)
            if not chunk:
                return None
            content_range = resp.headers.get("Content-Range", "")
            total = content_range.rsplit("/", 1)[-1] if "/" in content_range else resp.headers.get("Content-Length", "")
            return f"{total}:{hashlib.md5(chunk).hexdigest()}"
    except (urllib.error.URLError, OSError, ValueError):
        return None


def dedupe_image_urls(urls: list[str]) -> list[str]:
    """
    Drop URLs that are byte-identical to an earlier URL in the list,
    preserving first-seen order. Only worth calling on lists that can
    plausibly contain cross-supplier duplicates (i.e. matched hotels).
    """
    if len(urls) < 2:
        return urls

    _load_cache()
    global _cache_dirty

    to_fetch = [u for u in dict.fromkeys(urls) if u not in _cache]
    if to_fetch:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            futures = {pool.submit(_fingerprint, u): u for u in to_fetch}
            for fut in as_completed(futures):
                _cache[futures[fut]] = fut.result()
        _cache_dirty = True

    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        fp = _cache.get(u)
        if fp is None:
            result.append(u)  # couldn't fingerprint — keep it, never drop on a failure
            continue
        if fp in seen:
            continue
        seen.add(fp)
        result.append(u)
    return result


def flush_cache() -> None:
    """Persist the fingerprint cache if anything new was fetched this run."""
    if _cache_dirty:
        _save_cache()
