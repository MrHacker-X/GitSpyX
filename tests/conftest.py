"""Shared fixtures for the GitSpyX test suite (fully offline)."""

import pytest


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch):
    """Deterministic Rich output: wide console, no dynamic truncation."""
    monkeypatch.setenv("COLUMNS", "300")
    monkeypatch.setenv("LINES", "100")


class FakeHeaders(dict):
    """Case-insensitive-ish header mapping good enough for tests."""

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class FakeResponse:
    def __init__(self, status=200, headers=None, body=None, text=""):
        self.status_code = status
        self.headers = headers or FakeHeaders()
        self._body = body if body is not None else {}
        self.text = text or ("{}" if isinstance(self._body, dict) else "[]")

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


PROFILE = {
    "login": "torvalds",
    "id": 1024025,
    "name": "Linus Torvalds",
    "bio": None,
    "company": None,
    "location": "Portland, OR",
    "blog": "",
    "email": None,
    "twitter_username": None,
    "public_repos": 9,
    "followers": 200000,
    "following": 0,
    "public_gists": 1,
    "type": "User",
    "hireable": None,
    "created_at": "2011-09-03T15:32:34Z",
    "updated_at": "2025-08-06T10:00:00Z",
}

REPO = {
    "name": "linux",
    "full_name": "torvalds/linux",
    "description": "Linux kernel source tree",
    "language": "C",
    "stargazers_count": 250000,
    "forks_count": 65000,
    "subscribers_count": 8000,
    "open_issues_count": 300,
    "html_url": "https://github.com/torvalds/linux",
    "fork": False,
    "archived": False,
    "visibility": "public",
    "default_branch": "master",
    "size": 5000000,
    "homepage": "",
    "topics": ["kernel", "linux"],
    "license": {"name": "Other"},
    "created_at": "2011-09-04T00:00:00Z",
    "updated_at": "2026-09-01T00:00:00Z",
    "pushed_at": "2026-09-20T00:00:00Z",
    "owner": {"login": "torvalds"},
}

SMALL_REPO = {
    **REPO,
    "name": "subsurface-for-zander",
    "full_name": "torvalds/subsurface-for-zander",
    "description": None,
    "language": None,
    "stargazers_count": 90,
    "forks_count": 20,
    "subscribers_count": 5,
    "fork": True,
    "parent": {"full_name": "subsurface/subsurface"},
    "source": {"full_name": "subsurface/subsurface"},
}

CONTRIB = {"login": "torvalds", "contributions": 30000, "type": "User",
           "html_url": "https://github.com/torvalds"}
ANON_CONTRIB = {"login": None, "contributions": 12, "type": "Anonymous"}

COMMIT = {
    "sha": "abc123def4567890",
    "author": {"login": "torvalds"},
    "commit": {
        "author": {"name": "Linus Torvalds", "date": "2026-09-20T12:00:00Z"},
        "message": "Fix the thing\n\nLonger body here.",
    },
}

EVENT = {"type": "PushEvent", "repo": {"name": "torvalds/linux"},
         "created_at": "2026-09-20T12:00:00Z"}


@pytest.fixture
def user_report():
    """A realistic user report assembled without network access."""
    from gitspyx.collectors import _activity_summary, _repo_aggregates

    repos = [REPO, SMALL_REPO]
    return {
        "subject": "torvalds",
        "profile": PROFILE,
        "repositories": repos,
        "stats": _repo_aggregates(repos),
        "organizations": [{"login": "linux-foundation"}],
        "gists": [],
        "activity": _activity_summary([EVENT, EVENT]),
        "activity_note": "Based on the 2 most recent public events only.",
        "repositories_truncated": False,
        "collected_at": "2026-09-26T00:00:00Z",
    }


@pytest.fixture
def repo_report():
    return {
        "subject": "torvalds/linux",
        "repository": REPO,
        "languages": {"C": 98, "Shell": 1, "Python": 1},
        "contributors": [CONTRIB, ANON_CONTRIB],
        "branches": ["master", "next"],
        "collected_at": "2026-09-26T00:00:00Z",
    }


@pytest.fixture
def deep_report(user_report):
    report = dict(user_report)
    report["deep_dive"] = [
        {
            "repo": "linux",
            "stars": 250000,
            "url": "https://github.com/torvalds/linux",
            "top_contributors": [CONTRIB, ANON_CONTRIB],
        }
    ]
    report["deep_dive_limit"] = 3
    return report
