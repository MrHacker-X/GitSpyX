"""Shared helpers: validation, slug sanitising, human formatting."""

from __future__ import annotations

import re
import urllib.parse

# GitHub identifier rules (usernames, orgs, repo names): alphanumeric and
# single hyphens, must start/end alphanumeric, max 39 chars for login names.
_GH_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
# Repo names are slightly laxer: also allow dots and underscores, up to 100.
_GH_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _repo_name_valid(repo: str) -> bool:
    """GitHub repo-name rules: alnum/dot/underscore/hyphen, 1-100 chars.

    Leading dots are valid (e.g. ``.github``). Names made only of dots, or
    ending with a dot, are rejected (GitHub sanitises these away).
    """
    if not _GH_REPO_RE.match(repo):
        return False
    if set(repo) == {"."}:
        return False
    if repo.endswith("."):
        return False
    return True

# Windows reserved device names that must never become a filename base.
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def is_valid_github_login(name) -> bool:
    """True if ``name`` looks like a GitHub username/org (after strip)."""
    if not isinstance(name, str):
        return False
    return bool(_GH_ID_RE.match(name.strip()))


def parse_repo_slug(owner_repo: str) -> tuple[str, str]:
    """Validate and split ``owner/repo``.

    Raises ``ValueError`` with a helpful message for malformed input such as
    ``repo``, ``owner/``, ``/repo``, ``owner//repo`` or ``o/r/extra``.
    """
    raw = (owner_repo or "").strip()
    if not raw:
        raise ValueError("Repository identifier is empty. Expected owner/repo (e.g. torvalds/linux).")
    parts = raw.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid repository identifier '{raw}'. Expected exactly 'owner/repo' "
            "(e.g. torvalds/linux) with no extra slashes."
        )
    owner, repo = (p.strip() for p in parts)
    if not owner or not repo:
        raise ValueError(
            f"Invalid repository identifier '{raw}'. Both owner and repo name are required."
        )
    if not _GH_ID_RE.match(owner):
        raise ValueError(f"Invalid repository owner '{owner}': not a valid GitHub account name.")
    if not _repo_name_valid(repo):
        raise ValueError(f"Invalid repository name '{repo}': not a valid GitHub repository name.")
    return owner, repo


def slugify(value: str, fallback: str = "gitspyx_output", max_len: int = 60) -> str:
    """Turn arbitrary user input into a safe filename component.

    Handles ``../`` traversal, Windows reserved names, unicode, punctuation,
    leading dots and very long strings. Output never contains path separators.
    """
    value = (value or "").strip()
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE)
    value = value.strip(" ._")
    if not value:
        return fallback
    if value.upper() in _WINDOWS_RESERVED:
        value = f"_{value}"
    if value.startswith("."):
        value = f"_{value}"
    return value[:max_len]


def format_count(n) -> str:
    """1234 -> '1,234' with thousands separators, robust to None/garbage."""
    try:
        return f"{int(n or 0):,}"
    except (TypeError, ValueError):
        return "0"


def format_delta(seconds: float | None) -> str:
    """Seconds -> '4ms' / '1.2s' / '3m05s'."""
    if seconds is None:
        return "?"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def safe_str(value, default: str = "N/A") -> str:
    """Render any optional API field for display without crashing on None."""
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def build_output_slug(prefix: str, subject: str) -> str:
    """Filename stem for exports, e.g. 'user-torvalds' or 'repo-owner_name'."""
    return f"{prefix}-{slugify(subject, fallback='unknown').replace(' ', '_')}"
