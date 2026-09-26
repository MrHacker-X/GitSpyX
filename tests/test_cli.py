"""CLI integration tests — every mode exercised offline via a fake client."""

import json

import pytest

from gitspyx import __main__ as cli

from conftest import (
    ANON_CONTRIB,
    COMMIT,
    CONTRIB,
    EVENT,
    PROFILE,
    REPO,
    SMALL_REPO,
    FakeHeaders,
    FakeResponse,
)


class FakeClient:
    """Scripted stand-in for GitSpyXClient: records calls, returns fixtures."""

    last: "FakeClient | None" = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[str] = []
        self.token_present = bool(kwargs.get("token"))
        self.cache = None
        self.stats = {
            "requests": 3, "cache_hits": 1, "retries": 0,
            "rate_limit_remaining": 55, "rate_limit_used": 5,
            "rate_limit_limit": 60, "rate_limit_reset": None,
        }
        FakeClient.last = self

    def _log(self, name):
        self.calls.append(name)

    def user(self, username):
        self._log("user")
        return dict(PROFILE)

    def user_repos(self, username, max_pages=100, max_items=None):
        self._log("user_repos")
        items = [dict(REPO), dict(SMALL_REPO)]
        if max_items:
            items = items[:max_items]
        return items

    def user_orgs(self, username):
        self._log("user_orgs")
        return [{"login": "linux-foundation"}]

    def user_gists(self, username):
        self._log("user_gists")
        return []

    def user_events(self, username, per_page=30):
        self._log("user_events")
        return [dict(EVENT) for _ in range(2)]

    def repo(self, owner, repo):
        self._log(f"repo:{owner}/{repo}")
        return dict(REPO, full_name=f"{owner}/{repo}", name=repo)

    def repo_languages(self, owner, repo):
        self._log("languages")
        return {"C": 98, "Python": 2}

    def repo_contributors(self, owner, repo, max_pages=2):
        self._log("contributors")
        return [dict(CONTRIB), dict(ANON_CONTRIB)]

    def repo_branches(self, owner, repo, max_pages=2):
        self._log("branches")
        return [{"name": "master"}, {"name": "next"}]

    def repo_commits(self, owner, repo, per_page=30):
        self._log("commits")
        return [dict(COMMIT)]

    def repo_events(self, owner, repo, per_page=30):
        self._log("repo_events")
        return [dict(EVENT) for _ in range(3)]

    def rate_limit(self):
        self._log("rate_limit")
        return {"resources": {"core": {"remaining": 55, "limit": 60}}}

    def rate_limit_state(self):
        return {k: v for k, v in self.stats.items() if k.startswith("rate_limit")}

    def org(self, org):
        self._log("org")
        return {"login": org, "name": "GitHub", "public_repos": 564,
                "followers": 87480, "blog": "https://github.com/about"}

    def search_users(self, query, per_page=30):
        self._log("search")
        return {"total_count": 2, "items": [
            {"login": "johndoe", "type": "User", "id": 1, "html_url": "https://github.com/johndoe"},
            {"login": "janedoe", "type": "User", "id": 2, "html_url": "https://github.com/janedoe"},
        ]}

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "GitSpyXClient", lambda **k: FakeClient(**k))
    monkeypatch.chdir(tmp_path)
    yield FakeClient


# --- mode coverage (#24) ---------------------------------------------------------

def test_user_basic(fake_client, capsys):
    assert cli.main(["-u", "torvalds"]) == 0
    out = capsys.readouterr().out
    assert "torvalds" in out
    # -r NOT passed: full repo table must not print
    assert "Repositories for" not in out
    # extra data NOT fetched by default (#39)
    assert "user_orgs" not in FakeClient.last.calls


def test_user_with_repos_flag(fake_client, capsys):
    assert cli.main(["-u", "torvalds", "-r"]) == 0
    out = capsys.readouterr().out
    assert "Repositories: torvalds" in out
    assert "linux" in out
    assert "Subs" in out            # subscribers column
    assert "Pushed" in out


def test_user_deep(fake_client, capsys):
    assert cli.main(["-u", "torvalds", "--deep"]) == 0
    out = capsys.readouterr().out
    assert "Deep Dive" in out
    assert "torvalds" in out        # contributor shown in terminal
    # extra sections surfaced in deep mode (#8/#9)
    assert "user_orgs" in FakeClient.last.calls
    assert "Organizations" in out


def test_repo_investigation(fake_client, capsys):
    assert cli.main(["-i", "torvalds/linux"]) == 0
    out = capsys.readouterr().out
    assert "Repository Dossier" in out
    assert "Default Branch" in out
    assert "Last Push" in out
    assert "Visibility" in out
    assert "Branches" in out
    assert "Contributors" in out


def test_repo_activity(fake_client, capsys):
    assert cli.main(["-i", "torvalds/linux", "--activity"]) == 0
    out = capsys.readouterr().out
    assert "Recent Commits" in out
    assert "abc123de" in out
    assert "Recent Public Events" in out   # labelled 'recent' (#35)


def test_org_lookup(fake_client, capsys):
    assert cli.main(["-o", "github"]) == 0
    out = capsys.readouterr().out
    assert "Organization" in out


def test_search(fake_client, capsys):
    assert cli.main(["-s", "john"]) == 0
    out = capsys.readouterr().out
    assert "Search" in out


# --- silent mode (#3) ---------------------------------------------------------------

def test_no_display_fully_silent(fake_client, capsys):
    assert cli.main(["-u", "torvalds", "--no-display"]) == 0
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    combined = out + err
    assert "█" not in combined                    # no banner
    assert "Profile Intelligence" not in combined  # no tables
    assert "Saved:" not in combined                # no save messages
    assert "HTTP requests" not in combined         # no session summary
    assert "GitSpyX v" not in combined             # no version banner text


def test_no_display_exports_files(fake_client, capsys, tmp_path):
    import os

    assert cli.main(["-u", "torvalds", "--no-display", "-f", "json"]) == 0
    out_dir = tmp_path / "output-gitspyx"
    assert out_dir.exists()
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["profile"]["login"] == "torvalds"


# --- legacy compatibility (#4) --------------------------------------------------------

def test_legacy_u_owner_i_repo(fake_client, capsys):
    """python gitspyx.py -u OWNER -i REPO == gitspyx -i OWNER/REPO."""
    assert cli.main(["-u", "torvalds", "-i", "linux"]) == 0
    out = capsys.readouterr().out
    assert "Repository Dossier" in out
    assert "repo:torvalds/linux" in FakeClient.last.calls
    # must NOT have called user()
    assert "user" not in FakeClient.last.calls


def test_legacy_still_allows_new_syntax(fake_client, capsys):
    assert cli.main(["-i", "torvalds/linux"]) == 0
    assert "repo:torvalds/linux" in FakeClient.last.calls


# --- validation (#19, #20) --------------------------------------------------------------

@pytest.mark.parametrize("bad", ["repo", "owner/", "/repo", "owner/repo/extra", "owner//repo"])
def test_malformed_repo_identifiers(fake_client, capsys, bad):
    assert cli.main(["-i", bad]) == 1
    err = capsys.readouterr().err
    assert "Error" in err


def test_invalid_username(fake_client, capsys):
    assert cli.main(["-u", "not a user!"]) == 1
    assert "not a valid GitHub username" in capsys.readouterr().err


def test_invalid_org(fake_client, capsys):
    assert cli.main(["-o", "bad org!"]) == 1


# --- exit codes ----------------------------------------------------------------------------

def test_exit_codes_error_paths(fake_client, monkeypatch, capsys):
    from gitspyx.exceptions import (
        AuthenticationError, NotFoundError, RateLimitError, SecondaryRateLimitError,
    )

    cases = [
        (NotFoundError("nf"), 4),
        (AuthenticationError("auth"), 3),
        (RateLimitError("rl", reset_epoch=4102444800), 5),
        (SecondaryRateLimitError("srl"), 5),
    ]
    for exc, code in cases:
        def raise_exc(*a, **k):
            raise exc

        monkeypatch.setattr(cli, "collect_user", raise_exc)
        assert cli.main(["-u", "torvalds"]) == code
        capsys.readouterr()


def test_rate_limit_command(fake_client, capsys):
    assert cli.main(["--rate-limit"]) == 0
    assert "55/60" in capsys.readouterr().out


def test_clear_cache_command(fake_client, capsys):
    assert cli.main(["--clear-cache"]) == 0
    assert "Cache cleared" in capsys.readouterr().out


# --- deep-limit (#14) --------------------------------------------------------------------

def test_deep_limit_capped(fake_client, capsys):
    assert cli.main(["-u", "torvalds", "--deep", "--deep-limit", "999"]) == 0
    err = capsys.readouterr().err
    assert "capped" in err


def test_deep_limit_valid(fake_client):
    assert cli.main(["-u", "torvalds", "--deep", "--deep-limit", "2"]) == 0


def test_negative_deep_limit_rejected(fake_client):
    assert cli.main(["-u", "torvalds", "--deep", "--deep-limit", "-1"]) == 1


# --- collectors deep safety (#37) ------------------------------------------------------------

def test_collect_full_report_handles_null_contributors(monkeypatch):
    from gitspyx import collectors

    class C:
        def user(self, u):
            return dict(PROFILE)

        def user_repos(self, u, **k):
            return [dict(REPO)]

        def user_orgs(self, u):
            return []

        def user_gists(self, u):
            return []

        def user_events(self, u, per_page=30):
            return []

        def repo_contributors(self, o, r, max_pages=1):
            return [dict(ANON_CONTRIB), {"weird": "shape"}, None]

        last_pagination_truncated = False

    report = collectors.collect_full_report(C(), "torvalds", deep_limit=1)
    assert report["deep_dive"][0]["top_contributors"][0]["login"] == "anonymous"


# --- user collector efficiency (#39) ------------------------------------------------------------

def test_collect_user_default_skips_extra_calls():
    from gitspyx import collectors

    class C:
        def __init__(self):
            self.calls = []

        def user(self, u):
            self.calls.append("user")
            return dict(PROFILE)

        def user_repos(self, u, **k):
            self.calls.append("repos")
            return [dict(REPO)]

        def __getattr__(self, name):
            def boom(*a, **k):
                self.calls.append(name)
                raise AssertionError(f"unexpected call: {name}")
            return boom

        last_pagination_truncated = False

    c = C()
    collectors.collect_user(c, "torvalds")
    assert c.calls == ["user", "repos"]


def test_collect_user_fetch_extra_calls_everything():
    from gitspyx import collectors

    class C:
        def user(self, u):
            return dict(PROFILE)

        def user_repos(self, u, **k):
            return []

        def user_orgs(self, u):
            return []

        def user_gists(self, u):
            return []

        def user_events(self, u, per_page=30):
            return []

        last_pagination_truncated = False

    report = collectors.collect_user(C(), "torvalds", fetch_extra=True)
    assert "organizations" in report
    assert "gists" in report
    assert "activity" in report
    assert "recent" in report["activity_note"].lower()
