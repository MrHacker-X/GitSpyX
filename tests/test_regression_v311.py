"""Regression tests for the v3.1.1 hardening pass.

Covers: tomllib compatibility guard, HTML anchor integrity + XSS escaping,
pagination truncation edge cases, 304 cache recovery, 429 single-sleep
retry, dot-leading repo names, collector degradation semantics, and CSV
formula-injection protection.
"""

import csv
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from gitspyx.client import GitSpyXClient
from gitspyx.exporters import ExportManager, _csv_safe, _esc
from gitspyx.utils import parse_repo_slug

from conftest import FakeHeaders, FakeResponse


# ---------------------------------------------------------------------------
# Fix 1: tomllib compatibility (regression guard)
# ---------------------------------------------------------------------------

def test_version_check_module_has_tomllib_fallback():
    import ast

    source = open("checks/version_check.py", encoding="utf-8").read()
    tree = ast.parse(source)
    handler_types = [
        ast.unparse(h.type)
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for h in node.handlers
        if h.type is not None
    ]
    assert "ModuleNotFoundError" in handler_types, (
        "version_check.py must keep its tomllib/tomli fallback"
    )


def test_version_check_script_runs():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "checks/version_check.py"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Version consistent" in result.stdout


# ---------------------------------------------------------------------------
# Fix 3: HTML anchors + XSS escaping
# ---------------------------------------------------------------------------

@pytest.fixture
def em(tmp_path):
    return ExportManager(tmp_path)


def test_html_anchor_renders_clickable_link(em, user_report, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = em.export(user_report, "user-t", ["html"])
    html = open(files[0], encoding="utf-8").read()
    assert '<a href="https://github.com/torvalds/linux">linux</a>' in html
    assert "&lt;a" not in html  # anchors never escaped into literal text


def test_html_xss_in_label_is_escaped(em, tmp_path):
    em2 = ExportManager(tmp_path)
    report = {
        "subject": "xss",
        "stats": {
            "total_repos": 1, "total_stars": 1, "total_forks": 1, "total_watchers": 1,
            "top_starred": [
                {"name": '<script>alert(1)</script>', "stars": 5,
                 "url": 'javascript:alert(document.cookie)'},
            ],
        },
    }
    files = em2.export(report, "user-xss", ["html"])
    html = open(files[0], encoding="utf-8").read()
    assert "<script>" not in html
    assert "javascript:" not in html  # unsafe scheme neutralised to '#'
    assert "&lt;script&gt;" in html


def test_html_data_urls_rejected_in_anchor():
    from gitspyx.exporters import _anchor

    a = _anchor("data:text/html,<script>alert(1)</script>", "<script>alert(1)</script>")
    assert 'href="#"' in a.html
    assert "<script>" not in a.html  # label is escaped
    assert "&lt;script&gt;" in a.html


# ---------------------------------------------------------------------------
# Fix 4: pagination truncation detection
# ---------------------------------------------------------------------------

def _paginate_with(client_pages, max_pages, max_items=None):
    c = GitSpyXClient(use_cache=False)

    def fake_get(url, params=None):
        return client_pages.get(params["page"], [])

    c.get_json = fake_get
    items = c.paginate("http://x", max_pages=max_pages, max_items=max_items)
    c.close()
    return items, c.last_pagination_truncated


FULL = [{"id": i} for i in range(100)]


def test_pagination_partial_final_page_not_truncated():
    items, trunc = _paginate_with({1: FULL, 2: FULL[:50]}, 100)
    assert len(items) == 150 and trunc is False


def test_pagination_exact_full_page_at_max_pages_is_truncated():
    items, trunc = _paginate_with({1: FULL, 2: FULL}, 2)
    assert len(items) == 200 and trunc is True


def test_pagination_empty_page_not_truncated():
    items, trunc = _paginate_with({1: []}, 100)
    assert items == [] and trunc is False


def test_pagination_normal_completion_not_truncated():
    pages = {1: FULL, 2: FULL, 3: FULL[:10]}
    items, trunc = _paginate_with(pages, 100)
    assert len(items) == 210 and trunc is False


def test_pagination_max_items_mid_stream_truncated():
    items, trunc = _paginate_with({p: FULL for p in range(1, 10)}, 100, max_items=150)
    assert len(items) == 150 and trunc is True


def test_pagination_max_items_above_dataset_not_truncated():
    items, trunc = _paginate_with({1: FULL, 2: FULL[:50]}, 100, max_items=500)
    assert len(items) == 150 and trunc is False


# ---------------------------------------------------------------------------
# Fix 5: 304 cache recovery
# ---------------------------------------------------------------------------

def _client_with_cache(tmp_path):
    return GitSpyXClient(cache_dir=tmp_path)


def test_304_with_valid_cache_hits_cache(tmp_path, monkeypatch):
    c = _client_with_cache(tmp_path)
    url = "https://api.github.com/x"
    monkeypatch.setattr(
        c.session, "get",
        lambda *a, **k: FakeResponse(200, headers=FakeHeaders({"ETag": '"v1"'}), body={"n": 1}),
    )
    assert c.get_json(url) == {"n": 1}
    monkeypatch.setattr(c.session, "get", lambda *a, **k: FakeResponse(304))
    assert c.get_json(url) == {"n": 1}
    assert c.stats["cache_hits"] == 1
    c.close()


def test_304_missing_body_refetches_clean(tmp_path, monkeypatch):
    c = _client_with_cache(tmp_path)
    url = "https://api.github.com/x"
    # Populate cache then destroy the body (simulates corrupted/missing file).
    monkeypatch.setattr(
        c.session, "get",
        lambda *a, **k: FakeResponse(200, headers=FakeHeaders({"ETag": '"v1"'}), body={"n": 1}),
    )
    c.get_json(url)
    c.cache._mem.clear()
    for p in c.cache.directory.glob("*.json"):
        p.unlink()

    responses = [
        FakeResponse(304),  # first: validator matches, cache body gone
        FakeResponse(200, headers=FakeHeaders({"ETag": '"v2"'}), body={"n": 2}),  # clean refetch
    ]
    sent_headers = []

    def fake_get(url, headers=None, timeout=None):
        sent_headers.append(headers)
        return responses.pop(0)

    monkeypatch.setattr(c.session, "get", fake_get)
    assert c.get_json(url) == {"n": 2}
    assert len(responses) == 0
    # The clean refetch (2nd request) must NOT carry stale validators.
    assert sent_headers[1] is None or not sent_headers[1]
    c.close()


def test_304_missing_body_then_refetch_fails_propagates(tmp_path, monkeypatch):
    c = _client_with_cache(tmp_path)
    url = "https://api.github.com/x"
    monkeypatch.setattr(
        c.session, "get",
        lambda *a, **k: FakeResponse(200, headers=FakeHeaders({"ETag": '"v1"'}), body={"n": 1}),
    )
    c.get_json(url)
    c.cache._mem.clear()
    for p in c.cache.directory.glob("*.json"):
        p.unlink()

    responses = [FakeResponse(304), FakeResponse(404)]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: responses.pop(0))
    from gitspyx.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        c.get_json(url)
    c.close()


def test_304_no_second_304_loop(tmp_path, monkeypatch):
    """If server keeps returning 304 without a body, we must not loop forever."""
    c = _client_with_cache(tmp_path)
    url = "https://api.github.com/x"
    monkeypatch.setattr(
        c.session, "get",
        lambda *a, **k: FakeResponse(200, headers=FakeHeaders({"ETag": '"v1"'}), body={"n": 1}),
    )
    c.get_json(url)
    c.cache._mem.clear()
    for p in c.cache.directory.glob("*.json"):
        p.unlink()

    calls = {"n": 0}

    def always_304(*a, **k):
        calls["n"] += 1
        return FakeResponse(304)

    monkeypatch.setattr(c.session, "get", always_304)
    from gitspyx.exceptions import APIError

    with pytest.raises(APIError):
        c.get_json(url)
    assert calls["n"] == 2  # 304 (validators) + one clean 304 -> bounded error
    c.close()


# ---------------------------------------------------------------------------
# Fix 6: 429 retry sleeps exactly once per retry
# ---------------------------------------------------------------------------

def test_429_retry_uses_retry_after_single_sleep(monkeypatch):
    c = GitSpyXClient(use_cache=False, max_retries=2)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    responses = [
        FakeResponse(429, headers=FakeHeaders({"Retry-After": "2"})),
        FakeResponse(200, body={"ok": 1}),
    ]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: responses.pop(0))
    assert c.get_json("https://api.github.com/x") == {"ok": 1}
    assert sleeps == [2.0]  # exactly one sleep, honouring Retry-After
    c.close()


def test_429_retry_without_retry_after_single_backoff(monkeypatch):
    c = GitSpyXClient(use_cache=False, max_retries=2)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    responses = [
        FakeResponse(429),
        FakeResponse(200, body={"ok": 1}),
    ]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: responses.pop(0))
    assert c.get_json("https://api.github.com/x") == {"ok": 1}
    assert len(sleeps) == 1
    assert sleeps[0] == 1.0  # 2**attempt(0) backoff
    c.close()


def test_429_garbage_retry_after_falls_back_to_backoff(monkeypatch):
    c = GitSpyXClient(use_cache=False, max_retries=2)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    responses = [
        FakeResponse(429, headers=FakeHeaders({"Retry-After": "soon"})),
        FakeResponse(200, body={"ok": 1}),
    ]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: responses.pop(0))
    assert c.get_json("https://api.github.com/x") == {"ok": 1}
    assert len(sleeps) == 1 and sleeps[0] == 1.0
    c.close()


def test_429_exhausted_raises_secondary(monkeypatch):
    c = GitSpyXClient(use_cache=False, max_retries=1)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(c.session, "get", lambda *a, **k: FakeResponse(429))
    from gitspyx.exceptions import SecondaryRateLimitError

    with pytest.raises(SecondaryRateLimitError):
        c.get_json("https://api.github.com/x")
    assert len(sleeps) == 1  # one retry, one sleep
    c.close()


# --- v3.1.2 follow-up fixes -------------------------------------------------

def test_429_retry_after_not_capped(monkeypatch):
    """Retry-After: 30 must sleep 30s, not the 8s backoff cap."""
    c = GitSpyXClient(use_cache=False, max_retries=2)
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    responses = [
        FakeResponse(429, headers=FakeHeaders({"Retry-After": "30"})),
        FakeResponse(200, body={"ok": 1}),
    ]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: responses.pop(0))
    assert c.get_json("https://api.github.com/x") == {"ok": 1}
    assert sleeps == [30.0]
    c.close()


def test_304_refetch_counts_both_requests(tmp_path, monkeypatch):
    """304 + clean refetch = 2 real HTTP requests in the stats."""
    c = GitSpyXClient(cache_dir=tmp_path)
    url = "https://api.github.com/x"
    monkeypatch.setattr(
        c.session, "get",
        lambda *a, **k: FakeResponse(200, headers=FakeHeaders({"ETag": '"v1"'}), body={"n": 1}),
    )
    c.get_json(url)
    assert c.stats["requests"] == 1
    # Corrupt the stored body (etag intact) so a 304 forces a clean refetch.
    c.cache._mem.clear()
    for p in c.cache.directory.glob("*.json"):
        p.write_text(json.dumps(
            {"version": 2, "etag": '"v1"', "last_modified": None, "body": None, "stored_at": 1.0}
        ))
    responses = [
        FakeResponse(304),
        FakeResponse(200, headers=FakeHeaders({"ETag": '"v2"'}), body={"n": 2}),
    ]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: responses.pop(0))
    assert c.get_json(url) == {"n": 2}
    assert c.stats["requests"] == 3  # 1 populate + 304 + clean refetch
    c.close()


def test_pagination_max_pages_1_full_page_with_high_max_items():
    """max_pages=1 + max_items=1000 + full first page: more pages may exist."""
    c = GitSpyXClient(use_cache=False)
    FULL = [{"id": i} for i in range(100)]
    c.get_json = lambda url, params=None: FULL
    items = c.paginate("http://x", max_pages=1, max_items=1000)
    c.close()
    assert len(items) == 100
    assert c.last_pagination_truncated is True


def test_pagination_max_items_bound_short_page_not_truncated():
    """Short final page inside max_items: collection genuinely complete."""
    c = GitSpyXClient(use_cache=False)
    FULL = [{"id": i} for i in range(100)]
    pages = {1: FULL, 2: FULL[:50]}
    c.get_json = lambda url, params=None: pages.get(params["page"], [])
    items = c.paginate("http://x", max_pages=10, max_items=1000)
    c.close()
    assert len(items) == 150
    assert c.last_pagination_truncated is False


def test_html_language_bars_render_as_real_html(em, user_report, monkeypatch, tmp_path):
    """Progress bars must be real HTML, not escaped text; labels stay escaped."""
    monkeypatch.chdir(tmp_path)
    report = dict(user_report)
    report["stats"] = dict(report["stats"], languages={"C": 80, "<script>x</script>": 20})
    files = em.export(report, "user-t", ["html"])
    html = open(files[0], encoding="utf-8").read()
    # Bars are real elements...
    assert '<div class="bar"><span style="width:' in html
    assert "&lt;div class=&quot;bar&quot;&gt;" not in html
    # ...while unsafe language names remain escaped.
    assert "&lt;script&gt;x&lt;/script&gt;" in html


# ---------------------------------------------------------------------------
# Fix 7: dot-leading repo names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slug", ["github/.github", "torvalds/.hidden", "a/b.repo"])
def test_dot_repo_names_valid(slug):
    assert parse_repo_slug(slug) == tuple(slug.split("/"))


@pytest.mark.parametrize("slug", ["owner/.", "owner/..", "owner/repo.", "owner/. . ."])
def test_dot_edge_cases_still_rejected(slug):
    with pytest.raises(ValueError):
        parse_repo_slug(slug)


# ---------------------------------------------------------------------------
# Fix 8: collector error handling
# ---------------------------------------------------------------------------

class ErrClient:
    """Client whose optional endpoints raise; profile/repos succeed."""

    exit_codes = {}

    def __init__(self, exc_factory):
        self.exc_factory = exc_factory
        self.last_pagination_truncated = False

    def user(self, u):
        return {"login": u}

    def user_repos(self, u, **k):
        return []

    def user_orgs(self, u):
        raise self.exc_factory("orgs")

    def user_gists(self, u):
        raise self.exc_factory("gists")

    def user_events(self, u, per_page=30):
        raise self.exc_factory("events")


def test_collector_records_warning_on_optional_failure():
    from gitspyx import collectors
    from gitspyx.exceptions import APIError

    report = collectors.collect_user(ErrClient(lambda m: APIError("boom", status=500)), "x", fetch_extra=True)
    assert report["organizations"] == []
    assert report["gists"] == []
    assert report["activity"]["events_analyzed"] == 0
    sections = {w.split(":")[0] for w in report["warnings"]}
    assert {"organizations", "gists", "activity"} <= sections


def test_collector_propagates_auth_errors():
    from gitspyx import collectors
    from gitspyx.exceptions import AuthenticationError

    with pytest.raises(AuthenticationError):
        collectors.collect_user(ErrClient(lambda m: AuthenticationError("bad token")), "x", fetch_extra=True)


def test_collector_propagates_rate_limit():
    from gitspyx import collectors
    from gitspyx.exceptions import RateLimitError

    with pytest.raises(RateLimitError):
        collectors.collect_user(ErrClient(lambda m: RateLimitError("rate limited")), "x", fetch_extra=True)


def test_collector_propagates_network_errors():
    from gitspyx import collectors
    from gitspyx.exceptions import NetworkError

    with pytest.raises(NetworkError):
        collectors.collect_user(ErrClient(lambda m: NetworkError("offline")), "x", fetch_extra=True)


# ---------------------------------------------------------------------------
# Fix 9: CSV formula injection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("evil", ["=SUM(A1:A2)", "+cmd", "-2+3", "@SUM(1)", "\t=tab", "\r=cr"])
def test_csv_safe_neutralises_formulas(evil):
    assert _csv_safe(evil) == f"'{evil}"


@pytest.mark.parametrize("normal", ["plain", "linux kernel", "", None, 42, True, "hyphen-ok"])
def test_csv_safe_leaves_normal_values(normal):
    assert _csv_safe(normal) == normal


def test_csv_export_neutralises_malicious_description(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    em = ExportManager(tmp_path / "out")
    report = {
        "subject": "evil",
        "repositories": [
            {"name": "=HYPERLINK(\"http://evil\",\"click\")", "description": "@cmd/uc",
             "language": None, "stargazers_count": 1, "forks_count": 0,
             "subscribers_count": 0, "open_issues_count": 0, "fork": False,
             "updated_at": None, "pushed_at": None, "html_url": "https://x"},
        ],
    }
    files = em.export(report, "user-evil", ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["name"].startswith("'=")
    assert rows[0]["description"].startswith("'@")


def test_csv_export_normal_values_untouched(em, user_report):
    files = em.export(user_report, "user-t", ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["name"] == "linux"  # no stray quoting
