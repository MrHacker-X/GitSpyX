"""Custom exception hierarchy for GitSpyX.

All errors derive from :class:`GitSpyXError` so the CLI can catch one base
class and map each subclass to a distinct exit code.
"""

from __future__ import annotations

import requests


class GitSpyXError(Exception):
    """Base class for all GitSpyX errors."""

    #: Subclasses override this; used as process exit code by the CLI.
    exit_code = 1

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\nhint: {self.hint}"
        return self.message


class ValidationError(GitSpyXError):
    """User-supplied identifier failed local validation (never sent to API)."""

    exit_code = 1


class NotFoundError(GitSpyXError):
    """GitHub returned 404 for the requested resource."""

    exit_code = 4

    def __init__(self, message: str, url: str | None = None):
        super().__init__(
            message,
            hint="Check the spelling — usernames, repo names and orgs are "
            "case-insensitive but must exist and be public.",
        )
        self.url = url


class AuthenticationError(GitSpyXError):
    """GitHub rejected the supplied token (401)."""

    exit_code = 3


class RateLimitError(GitSpyXError):
    """Base for rate limiting: primary exhaustion and secondary limits."""

    exit_code = 5

    def __init__(self, message: str, reset_epoch: float | None = None, retry_after: float | None = None):
        hint_parts = []
        if reset_epoch:
            import datetime as _dt

            local_tz = _dt.datetime.now().astimezone().tzinfo
            reset_dt = _dt.datetime.fromtimestamp(reset_epoch, tz=local_tz)
            tz_name = reset_dt.strftime("%Z") or "local"
            hint_parts.append(f"Primary limit resets {reset_dt.strftime('%d %B %Y at %H:%M:%S')} {tz_name}.")
        if retry_after:
            hint_parts.append(f"Retry after ~{int(retry_after)}s.")
        hint_parts.append("Set GITHUB_TOKEN to raise the primary limit to 5,000 requests/hour.")
        super().__init__(message, hint=" ".join(hint_parts))
        self.reset_epoch = reset_epoch
        self.retry_after = retry_after


class SecondaryRateLimitError(RateLimitError):
    """GitHub secondary rate limiting (abuse detection) or HTTP 429."""


class NetworkError(GitSpyXError):
    """DNS failure, timeout, connection reset, and friends."""

    exit_code = 2


class APIError(GitSpyXError):
    """Any other non-success HTTP status from the GitHub API."""

    exit_code = 6

    def __init__(self, message: str, status: int | None = None, hint: str | None = None):
        super().__init__(message, hint=hint)
        self.status = status


class ExportError(GitSpyXError):
    """A report file could not be written."""

    exit_code = 7


def from_requests_exception(exc: requests.RequestException) -> GitSpyXError:
    """Translate a requests exception into the GitSpyX hierarchy."""
    if isinstance(exc, requests.exceptions.Timeout):
        return NetworkError("Request timed out.", hint="Check your connection or increase --timeout.")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return NetworkError("Could not reach api.github.com.", hint="Check your internet connection / proxy.")
    return NetworkError(f"Request failed: {type(exc).__name__}")
