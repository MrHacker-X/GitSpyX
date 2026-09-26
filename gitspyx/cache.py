"""Persistent on-disk conditional-request cache.

Stores API responses under the platform cache dir (``~/.cache/gitspyx`` on
Linux) keyed by the complete effective request URL (path + query string).
Each entry records the ``ETag``/``Last-Modified`` validators plus the response
body. On a 304 the cached body is reused and the call costs nothing against
the hourly limit. Tokens are never part of the key or the stored data.

TTL: by default entries are revalidated via ETag/If-Modified-Since (no TTL),
but a ``ttl`` can be set so entries older than that are ignored entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

CACHE_VERSION = 2


class ETagCache:
    """Disk-backed cache implementing GitHub conditional-request semantics."""

    def __init__(self, directory: Optional[Path] = None, ttl: Optional[float] = None):
        if directory is None:
            base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
            directory = Path(base) / "gitspyx"
        self.directory = Path(directory)
        self.ttl = ttl
        self.enabled = True
        self.hits = 0
        self._mem: dict[str, dict[str, Any]] = {}

    # -- key handling ---------------------------------------------------------
    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"

    def _load_entry(self, url: str) -> Optional[dict[str, Any]]:
        if url in self._mem:
            return self._mem[url]
        path = self._path_for(url)
        try:
            with open(path, encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            # Missing, unreadable or corrupted cache file: treat as absent.
            return None
        if not isinstance(entry, dict) or entry.get("version") != CACHE_VERSION:
            return None
        if self.ttl is not None and entry.get("stored_at"):
            try:
                if time.time() - float(entry["stored_at"]) > self.ttl:
                    return None
            except (TypeError, ValueError):
                return None
        self._mem[url] = entry
        return entry

    # -- public API -------------------------------------------------------------
    def get_validator(self, url: str) -> dict[str, str]:
        """Headers dict for conditional request, if a cached copy exists."""
        entry = self._load_entry(url)
        if not entry:
            return {}
        headers: dict[str, str] = {}
        if entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = entry["last_modified"]
        return headers

    def get_cached_body(self, url: str) -> Optional[Any]:
        entry = self._load_entry(url)
        if not entry:
            return None
        return entry.get("body")

    def store(self, url: str, headers, body: Any) -> None:
        if not self.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            entry = {
                "version": CACHE_VERSION,
                "stored_at": time.time(),
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
                "body": body,
            }
            tmp = self._path_for(url).with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, self._path_for(url))
        except OSError:
            # Cache is best-effort; never fail a fetch because of disk issues.
            self.enabled = False

    def record_hit(self) -> None:
        self.hits += 1

    def clear(self) -> int:
        """Delete every cache file; returns how many entries were removed."""
        count = 0
        if self.directory.exists():
            for p in self.directory.glob("*.json"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    pass
        self._mem.clear()
        return count

    def stats(self) -> dict[str, Any]:
        files = list(self.directory.glob("*.json")) if self.directory.exists() else []
        return {"entries": len(files), "directory": str(self.directory)}
