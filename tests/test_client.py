"""Client tests: token precedence, retries, rate limits, pagination, cache."""

import pytest

from gitspyx.client import GitSpyXClient
from gitspyx.exceptions import (
    APIError,
    AuthenticationError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    SecondaryRateLimitError,
)

from conftest import FakeHeaders, FakeResponse


@pytest.fixture
def client():
    c = GitSpyXClient(use_cache=False)
    yield c
    c.close()


# --- token precedence (#18) ----------------------------------------------------

def test_token_precedence_explicit_beats_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    c = GitSpyXClient(token="explicit-token", use_cache=False)
    assert c.session.headers["Authorization"] == "Bearer explicit-token"
    c.close()


def test_token_precedence_github_over_gh(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    c = GitSpyXClient(use_cache=False)
    assert c.session.headers["Authorization"] == "Bearer env-token"
    c.close()


def test_token_precedence_gh_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    c = GitSpyXClient(use_cache=False)
    assert c.session.headers["Authorization"] == "Bearer gh-token"
    c.close()


def test_no_token_unauthenticated(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    c = GitSpyXClient(use_cache=False)
    assert "Authorization" not in c.session.headers
    assert c.token_present is False
    c.close()


def test_whitespace_token_ignored(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    c = GitSpyXClient(use_cache=False)
    assert "Authorization" not in c.session.headers
    c.close()


# --- token never leaks (#17) ------------------------------------------------------

def test_no_token_in_any_exception_string(client, monkeypatch):
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(404))
    with pytest.raises(NotFoundError) as ei:
        client.get_json("https://api.github.com/users/x")
    assert "Bearer" not in str(ei.value)
    assert "Authorization" not in str(ei.value)


# --- exception mapping -------------------------------------------------------------

def test_404(client, monkeypatch):
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(404))
    with pytest.raises(NotFoundError):
        client.get_json("https://api.github.com/users/x")


def test_401(client, monkeypatch):
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(401))
    with pytest.raises(AuthenticationError):
        client.get_json("https://api.github.com/users/x")


def test_403_primary_rate_limit(client, monkeypatch):
    resp = FakeResponse(403, headers=FakeHeaders({
        "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4102444800",
    }))
    monkeypatch.setattr(client.session, "get", lambda *a, **k: resp)
    with pytest.raises(RateLimitError) as ei:
        client.get_json("https://api.github.com/users/x")
    assert ei.value.reset_epoch == 4102444800.0


def test_403_secondary_with_retry_after(client, monkeypatch):
    resp = FakeResponse(403, headers=FakeHeaders({"Retry-After": "30"}))
    monkeypatch.setattr(client.session, "get", lambda *a, **k: resp)
    with pytest.raises(SecondaryRateLimitError):
        client.get_json("https://api.github.com/users/x")


def test_403_deterministic_fail_fast(client, monkeypatch):
    """Plain 403 without rate-limit context must NOT retry."""
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return FakeResponse(403, body={"message": "blocked"})

    monkeypatch.setattr(client.session, "get", fake_get)
    with pytest.raises(APIError) as ei:
        client.get_json("https://api.github.com/users/x")
    assert calls["n"] == 1
    assert ei.value.status == 403


def test_400_not_retried(client, monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return FakeResponse(400)

    monkeypatch.setattr(client.session, "get", fake_get)
    with pytest.raises(APIError):
        client.get_json("https://api.github.com/users/x")
    assert calls["n"] == 1


def test_500_retried_then_success(client, monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(502)
        return FakeResponse(200, body={"ok": True})

    monkeypatch.setattr(client.session, "get", fake_get)
    data = client.get_json("https://api.github.com/users/x")
    assert data == {"ok": True}
    assert calls["n"] == 3
    assert client.stats["retries"] == 2


def test_500_exhausted_retries(client, monkeypatch):
    monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResponse(500))
    with pytest.raises(APIError):
        client.get_json("https://api.github.com/users/x")
    assert client.stats["requests"] == 4  # 1 + 3 retries


def test_malformed_json(client, monkeypatch):
    monkeypatch.setattr(
        client.session, "get",
        lambda *a, **k: FakeResponse(200, body=ValueError("nope")),
    )
    with pytest.raises(APIError):
        client.get_json("https://api.github.com/users/x")


# --- rate-limit header parsing (#10, #11) -----------------------------------------

def test_rate_limit_state_from_headers(client, monkeypatch):
    resp = FakeResponse(200, headers=FakeHeaders({
        "X-RateLimit-Limit": "5000", "X-RateLimit-Remaining": "4999",
        "X-RateLimit-Used": "1", "X-RateLimit-Reset": "4102444800",
    }), body={"ok": 1})
    monkeypatch.setattr(client.session, "get", lambda *a, **k: resp)
    client.get_json("https://api.github.com/users/x")
    state = client.rate_limit_state()
    assert state["rate_limit_limit"] == 5000
    assert state["rate_limit_remaining"] == 4999
    assert state["rate_limit_used"] == 1
    assert state["rate_limit_reset"] == 4102444800


def test_garbage_rate_limit_headers_ignored(client, monkeypatch):
    resp = FakeResponse(200, headers=FakeHeaders({"X-RateLimit-Remaining": "banana"}), body={})
    monkeypatch.setattr(client.session, "get", lambda *a, **k: resp)
    client.get_json("https://api.github.com/users/x")
    assert client.rate_limit_state()["rate_limit_remaining"] is None


# --- pagination (#13) -----------------------------------------------------------------

def test_paginate_respects_max_items(client, monkeypatch):
    page = [{"id": i} for i in range(100)]

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, body=page)

    monkeypatch.setattr(client.session, "get", fake_get)
    items = client.paginate("https://api.github.com/x", max_items=150)
    assert len(items) == 150
    assert client.last_pagination_truncated is True


def test_paginate_stops_on_short_page(client, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": 100}]}

    def fake_get(url, headers=None, timeout=None):
        q = parse_qs(urlparse(url).query)
        p = int(q.get("page", ["1"])[0])
        return FakeResponse(200, body=pages.get(p, []))

    monkeypatch.setattr(client.session, "get", fake_get)
    items = client.paginate("https://api.github.com/x")
    assert len(items) == 101
    assert client.last_pagination_truncated is False


def test_paginate_respects_max_pages(client, monkeypatch):
    page = [{"id": i} for i in range(100)]
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(200, body=page)

    monkeypatch.setattr(client.session, "get", fake_get)
    items = client.paginate("https://api.github.com/x", max_pages=3)
    assert len(items) == 300
    assert calls["n"] == 3


# --- cache behaviour (#15, #16) ----------------------------------------------------

def test_cache_roundtrip_and_304(tmp_path, monkeypatch):
    c = GitSpyXClient(cache_dir=tmp_path)
    url = "https://api.github.com/users/x?per_page=100&page=1"

    resp = FakeResponse(200, headers=FakeHeaders({"ETag": '"v1"'}), body={"n": 1})
    monkeypatch.setattr(c.session, "get", lambda *a, **k: resp)
    assert c.get_json(url) == {"n": 1}

    # Same URL with different query = different cache key.
    other = FakeResponse(200, headers=FakeHeaders({"ETag": '"v2"'}), body={"n": 2})
    monkeypatch.setattr(c.session, "get", lambda *a, **k: other)
    assert c.get_json(url + "&page=2") == {"n": 2}

    # Now the server answers 304: cached body is served, no JSON parse needed.
    not_modified = FakeResponse(304, headers=FakeHeaders({}))
    monkeypatch.setattr(c.session, "get", lambda *a, **k: not_modified)
    assert c.get_json(url) == {"n": 1}
    assert c.stats["cache_hits"] == 1
    assert c.cache.stats()["entries"] == 2
    c.close()


def test_cache_key_includes_full_query(tmp_path):
    c = GitSpyXClient(cache_dir=tmp_path)
    c.cache.store("https://api.github.com/x?page=1", FakeHeaders({"ETag": "a"}), {"p": 1})
    c.cache.store("https://api.github.com/x?page=2", FakeHeaders({"ETag": "b"}), {"p": 2})
    assert c.cache.get_cached_body("https://api.github.com/x?page=1") == {"p": 1}
    assert c.cache.get_cached_body("https://api.github.com/x?page=2") == {"p": 2}
    c.close()


def test_cache_corrupted_file_ignored(tmp_path):
    c = GitSpyXClient(cache_dir=tmp_path)
    (tmp_path / "garbage.json").write_text("{not valid json!!")
    assert c.cache.get_cached_body("https://api.github.com/anything") is None
    assert c.cache.get_validator("https://api.github.com/anything") == {}
    c.close()


def test_cache_clear_missing_directory(tmp_path):
    c = GitSpyXClient(cache_dir=tmp_path / "does-not-exist")
    assert c.cache.clear() == 0
    c.close()


def test_cache_never_stores_token(tmp_path, monkeypatch):
    c = GitSpyXClient(token="super-secret-token", cache_dir=tmp_path)
    resp = FakeResponse(200, headers=FakeHeaders({"ETag": '"t"'}), body={"a": 1})
    monkeypatch.setattr(c.session, "get", lambda *a, **k: resp)
    c.get_json("https://api.github.com/users/x")
    import json as _json

    for p in tmp_path.glob("*.json"):
        content = p.read_text()
        assert "super-secret-token" not in content
        assert "Authorization" not in content
    c.close()
