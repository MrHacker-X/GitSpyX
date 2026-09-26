"""Optional integration tests against the real GitHub API.

These are NON-DESTRUCTIVE (read-only GETs) but hit the network and consume
rate-limit credits, so they are skipped by default:

    RUN_INTEGRATION=1 pytest tests/test_integration.py -v

Works unauthenticated; set GITHUB_TOKEN in the environment (or CI secret) to
avoid rate-limit flakiness.
"""

import os

import pytest

from gitspyx.client import GitSpyXClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Integration tests opt-in: set RUN_INTEGRATION=1",
)


@pytest.fixture(scope="module")
def client():
    c = GitSpyXClient()
    yield c
    c.close()


def test_fetch_octocat_profile(client):
    profile = client.user("octocat")
    assert profile["login"].lower() == "octocat"
    assert isinstance(profile["id"], int)


def test_fetch_octocat_repos(client):
    repos = client.user_repos("octocat", max_pages=1)
    assert isinstance(repos, list)
    assert all("name" in r for r in repos)


def test_fetch_repo_dossier(client):
    data = client.repo("torvalds", "linux")
    assert data["full_name"] == "torvalds/linux"
    assert data["stargazers_count"] > 0


def test_fetch_org(client):
    org = client.org("github")
    assert org["login"].lower() == "github"


def test_rate_limit_endpoint(client):
    data = client.rate_limit()
    core = data["resources"]["core"]
    assert core["limit"] in (60, 5000)
    assert core["remaining"] >= 0


def test_cli_end_to_end_user(tmp_path, monkeypatch):
    """Full CLI run against the live API, exporting to a temp dir."""
    from gitspyx import __main__ as cli

    monkeypatch.chdir(tmp_path)
    rc = cli.main(["-u", "octocat", "-f", "json", "--no-display"])
    assert rc == 0
    files = list((tmp_path / "output-gitspyx").glob("*.json"))
    assert len(files) == 1
