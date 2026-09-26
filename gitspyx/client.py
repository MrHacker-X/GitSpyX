"""Resilient GitHub API client: tokens, retries, rate limits, ETag caching.

Hardening notes:
    * Token precedence: explicit ``--token`` > ``GITHUB_TOKEN`` > ``GH_TOKEN``
      > unauthenticated. Tokens never appear in cache keys, stats, or errors.
    * Retry classification: only connection errors, timeouts, HTTP 429 and
      temporary 5xx are retried. 400/401/403/404 fail fast.
    * Rate-limit headers (``X-RateLimit-*``, ``Retry-After``) are parsed on
      every response and exposed via :attr:`stats` and :meth:`rate_limit_state`.
    * Pagination honours ``max_pages``/``max_items`` and reports truncation.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

from .cache import ETagCache
from .exceptions import (
    APIError,
    AuthenticationError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    SecondaryRateLimitError,
    from_requests_exception,
)
from . import __version__

API_ROOT = "https://api.github.com"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_CAP = 8  # seconds
USER_AGENT = f"GitSpyX/{__version__} (+https://github.com/MrHacker-X/GitSpyX)"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GitSpyXClient:
    """Thin, resilient wrapper around the GitHub REST API."""

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        use_cache: bool = True,
        cache_dir: Optional[Any] = None,
        quiet: bool = False,
        max_retries: int = MAX_RETRIES,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        token = self._resolve_token(token)
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.token_present = bool(token)
        self.timeout = timeout
        self.quiet = quiet
        self.max_retries = max_retries
        self.cache = ETagCache(cache_dir) if use_cache else None
        self.stats = {
            "requests": 0,        # HTTP requests attempted (excl. cache hits)
            "cache_hits": 0,      # responses served from local cache
            "retries": 0,         # retry attempts made
            "rate_limit_remaining": None,
            "rate_limit_used": None,
            "rate_limit_limit": None,
            "rate_limit_reset": None,  # epoch seconds
        }

    # -- token handling --------------------------------------------------------
    @staticmethod
    def _resolve_token(explicit: Optional[str]) -> Optional[str]:
        """Precedence: explicit arg > GITHUB_TOKEN > GH_TOKEN > None."""
        tok = explicit or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        tok = (tok or "").strip()
        return tok or None

    # -- rate-limit bookkeeping --------------------------------------------------
    def _update_rate_limit(self, resp: requests.Response) -> None:
        try:
            if "X-RateLimit-Remaining" in resp.headers:
                self.stats["rate_limit_remaining"] = int(resp.headers["X-RateLimit-Remaining"])
            if "X-RateLimit-Used" in resp.headers:
                self.stats["rate_limit_used"] = int(resp.headers["X-RateLimit-Used"])
            if "X-RateLimit-Limit" in resp.headers:
                self.stats["rate_limit_limit"] = int(resp.headers["X-RateLimit-Limit"])
            if "X-RateLimit-Reset" in resp.headers:
                self.stats["rate_limit_reset"] = int(resp.headers["X-RateLimit-Reset"])
        except (TypeError, ValueError):
            pass

    def rate_limit_state(self) -> dict:
        """Current rate-limit knowledge from response headers."""
        return {k: v for k, v in self.stats.items() if k.startswith("rate_limit")}

    # -- low-level ----------------------------------------------------------------
    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(min(2 ** attempt, RETRY_BACKOFF_CAP))

    def get_json(self, url: str, params: Optional[dict] = None) -> Any:
        """GET a JSON resource; raises a GitSpyXError subclass on failure.

        The cache key is the complete effective URL including query params.
        """
        if params:
            url = f"{url}?{requests.compat.urlencode(params)}"

        validator_headers = self.cache.get_validator(url) if self.cache else {}
        clean_retry_used = False  # allows exactly one validator-free refetch
        last_exc: Optional[GitSpyXError] = None

        for attempt in range(self.max_retries + 1):
            try:
                self.stats["requests"] += 1
                resp = self.session.get(url, headers=validator_headers or None, timeout=self.timeout)
            except requests.RequestException as exc:
                # Connection errors/timeouts are transient: retry.
                last_exc = from_requests_exception(exc)
                if attempt < self.max_retries:
                    self.stats["retries"] += 1
                    self._sleep_backoff(attempt)
                    continue
                raise last_exc from exc

            self._update_rate_limit(resp)

            if resp.status_code == 304 and self.cache:
                body = self.cache.get_cached_body(url)
                if body is not None:
                    self.cache.record_hit()
                    self.stats["cache_hits"] += 1
                    return body
                # A 304 never carries a usable body: serve from cache or
                # refetch cleanly — never fall through to the JSON path.
                if not clean_retry_used:
                    # One clean retry WITHOUT If-None-Match / If-Modified-Since
                    # so the server must send a full 200 body. The flag bounds
                    # the loop even if the server misbehaves and 304s again.
                    clean_retry_used = True
                    validator_headers = {}
                    continue
                raise APIError("Unexpected HTTP 304 without cached data.", status=304)

            if resp.status_code == 404:
                raise NotFoundError("Resource not found.", url=url)

            if resp.status_code == 401:
                raise AuthenticationError(
                    "GitHub rejected the credentials (401).",
                    hint="Check that your token is valid and not expired.",
                )

            if resp.status_code == 403:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                retry_after = resp.headers.get("Retry-After")
                if remaining == "0":
                    reset = resp.headers.get("X-RateLimit-Reset")
                    raise RateLimitError(
                        "GitHub API rate limit exceeded.",
                        reset_epoch=float(reset) if reset else None,
                        retry_after=float(retry_after) if retry_after else None,
                    )
                # 403 with Retry-After (or abuse wording) => secondary limit.
                if retry_after or "secondary" in resp.text.lower() or "abuse" in resp.text.lower():
                    raise SecondaryRateLimitError(
                        "GitHub secondary rate limit triggered.",
                        retry_after=float(retry_after) if retry_after else None,
                    )
                # Deterministic 403 (private/blocked resource): fail fast.
                raise APIError(
                    "GitHub refused the request (403).",
                    status=403,
                    hint="The resource may be private, blocked, or require different access.",
                )

            if resp.status_code == 429:
                # Primary or secondary throttling: retry honouring Retry-After.
                # An explicit server-provided Retry-After is waited for EXACTLY
                # (no exponential-backoff cap); our own backoff policy applies
                # only when the header is absent or invalid.
                if attempt < self.max_retries:
                    self.stats["retries"] += 1
                    ra = resp.headers.get("Retry-After")
                    if ra:
                        try:
                            time.sleep(float(ra))
                        except (TypeError, ValueError):
                            self._sleep_backoff(attempt)
                    else:
                        self._sleep_backoff(attempt)
                    continue
                raise SecondaryRateLimitError("Still throttled after retries (429).")

            if resp.status_code in RETRYABLE_STATUS:
                if attempt < self.max_retries:
                    self.stats["retries"] += 1
                    self._sleep_backoff(attempt)
                    continue
                raise APIError(
                    f"GitHub server error after {self.max_retries} retries (HTTP {resp.status_code}).",
                    status=resp.status_code,
                )

            if resp.status_code >= 400:
                raise APIError(f"GitHub API error (HTTP {resp.status_code}).", status=resp.status_code)

            # Success path
            try:
                data = resp.json()
            except ValueError:
                raise APIError("GitHub returned malformed JSON.", status=resp.status_code)
            if self.cache and (resp.headers.get("ETag") or resp.headers.get("Last-Modified")):
                self.cache.store(url, resp.headers, data)
            return data

        raise NetworkError("Unreachable: exhausted all retry attempts.")  # pragma: no cover

    # -- convenience endpoints ------------------------------------------------
    def user(self, username: str) -> Any:
        return self.get_json(f"{API_ROOT}/users/{username}")

    def user_repos(self, username: str, max_pages: int = 100, max_items: Optional[int] = None) -> list:
        return self.paginate(f"{API_ROOT}/users/{username}/repos", max_pages=max_pages, max_items=max_items)

    def repo(self, owner: str, repo: str) -> Any:
        return self.get_json(f"{API_ROOT}/repos/{owner}/{repo}")

    def repo_languages(self, owner: str, repo: str) -> Any:
        return self.get_json(f"{API_ROOT}/repos/{owner}/{repo}/languages")

    def repo_contributors(self, owner: str, repo: str, max_pages: int = 2) -> Any:
        return self.paginate(f"{API_ROOT}/repos/{owner}/{repo}/contributors", max_pages=max_pages)

    def repo_branches(self, owner: str, repo: str, max_pages: int = 2) -> Any:
        return self.paginate(f"{API_ROOT}/repos/{owner}/{repo}/branches", max_pages=max_pages)

    def repo_commits(self, owner: str, repo: str, per_page: int = 30) -> Any:
        return self.get_json(f"{API_ROOT}/repos/{owner}/{repo}/commits", params={"per_page": per_page})

    def repo_events(self, owner: str, repo: str, per_page: int = 30) -> Any:
        return self.get_json(f"{API_ROOT}/repos/{owner}/{repo}/events", params={"per_page": per_page})

    def user_events(self, username: str, per_page: int = 30) -> Any:
        return self.get_json(f"{API_ROOT}/users/{username}/events/public", params={"per_page": per_page})

    def user_gists(self, username: str, per_page: int = 100) -> Any:
        return self.get_json(f"{API_ROOT}/users/{username}/gists", params={"per_page": per_page})

    def user_orgs(self, username: str, per_page: int = 100) -> Any:
        return self.get_json(f"{API_ROOT}/users/{username}/orgs", params={"per_page": per_page})

    def org(self, org: str) -> Any:
        return self.get_json(f"{API_ROOT}/orgs/{org}")

    def search_users(self, query: str, per_page: int = 30) -> Any:
        return self.get_json(f"{API_ROOT}/search/users", params={"q": query, "per_page": per_page})

    # -- pagination ---------------------------------------------------------------
    def paginate(self, url: str, max_pages: int = 100, max_items: Optional[int] = None) -> list:
        """Fetch collection pages up to ``max_pages`` / ``max_items`` bounds.

        Returns a list; the caller can check :attr:`last_pagination_truncated`
        to know whether bounds may have cut the result short. Truncation is
        flagged when we stop due to ``max_items``, or when ``max_pages`` is
        reached while the last fetched page was still full (a full page at
        the page bound means more data may exist). A page shorter than the
        page size proves the collection ended naturally.
        """
        items: list = []
        self.last_pagination_truncated = False
        page = 1
        while page <= max_pages:
            if max_items is not None and len(items) >= max_items:
                self.last_pagination_truncated = True
                break
            data = self.get_json(url, params={"page": page, "per_page": 100})
            if not isinstance(data, list) or not data:
                break
            items.extend(data)
            if max_items is not None and len(items) >= max_items:
                items = items[:max_items]
                self.last_pagination_truncated = True
                break
            if len(data) < 100:
                # Short page: the collection is genuinely complete.
                self.last_pagination_truncated = False
                break
            page += 1
        else:
            # Loop exhausted max_pages with the last page full: more data
            # may exist beyond the bound.
            self.last_pagination_truncated = True
        return items

    # -- introspection ----------------------------------------------------------------
    def rate_limit(self) -> Any:
        return self.get_json(f"{API_ROOT}/rate_limit")

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "GitSpyXClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
