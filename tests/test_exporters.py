"""Exporter tests: verify file CONTENTS, not just creation (issue #26)."""

import csv
import json

import pytest

from gitspyx.exporters import ExportManager


@pytest.fixture
def em(tmp_path):
    return ExportManager(tmp_path)


def slugify_subject(report):
    from gitspyx.utils import build_output_slug
    return build_output_slug("user", report["subject"])


# --- user report -------------------------------------------------------------

def test_user_json_full_structure(em, user_report):
    files = em.export(user_report, slugify_subject(user_report), ["json"])
    data = json.loads(open(files[0], encoding="utf-8").read())
    assert data["subject"] == "torvalds"
    assert data["profile"]["login"] == "torvalds"
    assert len(data["repositories"]) == 2
    assert data["stats"]["total_stars"] > 0


def test_user_markdown_contents(em, user_report):
    files = em.export(user_report, slugify_subject(user_report), ["md"])
    text = open(files[0], encoding="utf-8").read()
    assert "## Profile" in text
    assert "torvalds" in text
    assert "Aggregate Statistics" in text
    assert "Language" in text
    assert "Top Starred" in text


def test_user_markdown_with_repos_and_deep(em, deep_report):
    files = em.export(deep_report, slugify_subject(deep_report), ["md"])
    text = open(files[0], encoding="utf-8").read()
    assert "## Repositories" in text          # -r data
    assert "Deep Dive" in text                # --deep data
    assert "torvalds" in text                 # contributor login
    assert "30,000" in text                   # contribution count


def test_user_csv_is_repositories(em, user_report):
    files = em.export(user_report, slugify_subject(user_report), ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {"linux", "subsurface-for-zander"}
    assert "stars" in rows[0] and "subscribers" in rows[0]


def test_user_html_contents(em, user_report):
    files = em.export(user_report, slugify_subject(user_report), ["html"])
    text = open(files[0], encoding="utf-8").read()
    assert "torvalds" in text
    assert "Profile" in text
    assert "Language Distribution" in text
    assert "Top Starred" in text
    assert "<style>" in text  # self-contained


# --- repo report -------------------------------------------------------------

def test_repo_html_contents(em, repo_report):
    files = em.export(repo_report, build("repo", repo_report), ["html"])
    text = open(files[0], encoding="utf-8").read()
    assert "torvalds/linux" in text
    assert "Language Breakdown" in text
    assert "Contributors" in text
    assert "anonymous" in text               # null-login contributor handled
    assert "Branches" in text
    assert "Last push" in text


def test_repo_markdown_contents(em, repo_report):
    files = em.export(repo_report, build("repo", repo_report), ["md"])
    text = open(files[0], encoding="utf-8").read()
    assert "## Repository" in text
    assert "Default branch" in text
    assert "Visibility" in text
    assert "### Contributors" in text
    assert "### Branches" in text


def test_repo_csv_is_contributors(em, repo_report):
    files = em.export(repo_report, build("repo", repo_report), ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["login"] for r in rows} == {"torvalds", "anonymous"}
    assert rows[0]["contributions"] == "30000"


def build(prefix, report):
    from gitspyx.utils import build_output_slug
    return build_output_slug(prefix, report["subject"])


# --- activity report -----------------------------------------------------------

@pytest.fixture
def activity_report():
    return {
        "subject": "torvalds/linux",
        "recent_commits": [
            {"sha": "abc123de", "author": "Linus Torvalds", "login": "torvalds",
             "date": "2026-09-20T12:00:00Z", "message": "Fix the thing"}
        ],
        "commits_note": "Most recent 1 commits on the default branch.",
        "top_committers": {"torvalds": 1},
        "event_types": {"PushEvent": 2, "WatchEvent": 1},
        "events_analyzed": 3,
        "events_note": "Based on the 3 most recent public events for this repository.",
        "collected_at": "2026-09-26T00:00:00Z",
    }


def test_activity_html_contents(em, activity_report):
    files = em.export(activity_report, build("repo", activity_report), ["html"])
    text = open(files[0], encoding="utf-8").read()
    assert "Recent Commits" in text
    assert "abc123de" in text
    assert "Top Committers" in text
    assert "Recent Public Events" in text
    assert "PushEvent" in text


def test_activity_markdown_contents(em, activity_report):
    files = em.export(activity_report, build("repo", activity_report), ["md"])
    text = open(files[0], encoding="utf-8").read()
    assert "## Recent Commits" in text
    assert "Top Committers" in text
    assert "Recent Public Events" in text


def test_activity_csv_is_commits(em, activity_report):
    files = em.export(activity_report, build("repo", activity_report), ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["sha"] == "abc123de"
    assert rows[0]["author"] == "Linus Torvalds"


# --- org / search / empty -------------------------------------------------------

ORG_REPORT = {
    "subject": "github",
    "organization": {"login": "github", "name": "GitHub", "public_repos": 564,
                     "followers": 87480, "blog": "https://github.com/about", "email": None},
    "collected_at": "2026-09-26T00:00:00Z",
}

SEARCH_REPORT = {
    "subject": "john doe",
    "total_count": 2,
    "incomplete_results": False,
    "results": [
        {"login": "johndoe", "type": "User", "id": 1, "html_url": "https://github.com/johndoe"},
        {"login": "janedoe", "type": "User", "id": 2, "html_url": "https://github.com/janedoe"},
    ],
    "collected_at": "2026-09-26T00:00:00Z",
}


def test_org_html_and_md(em):
    files = em.export(ORG_REPORT, build("org", ORG_REPORT), ["html", "md"])
    html = open(files[0], encoding="utf-8").read()
    md = open(files[1], encoding="utf-8").read()
    assert "Organization" in html and "GitHub" in html
    assert "## Organization" in md and "564" in md


def test_org_csv_fields(em):
    files = em.export(ORG_REPORT, build("org", ORG_REPORT), ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    fields = {r["field"] for r in rows}
    assert "login" in fields and "public_repos" in fields


def test_search_csv_headers_and_rows(em):
    files = em.export(SEARCH_REPORT, build("search", SEARCH_REPORT), ["csv"])
    with open(files[0], newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert set(reader.fieldnames) == {"login", "type", "id", "url"}
    assert {r["login"] for r in rows} == {"johndoe", "janedoe"}


def test_search_html_contents(em):
    files = em.export(SEARCH_REPORT, build("search", SEARCH_REPORT), ["html"])
    text = open(files[0], encoding="utf-8").read()
    assert "john doe" in text
    assert "Search Results" in text
    assert "johndoe" in text


def test_empty_user_report_no_crash(em):
    empty = {"subject": "ghost", "profile": {"login": "ghost"}, "repositories": [],
             "stats": None, "organizations": [], "gists": [], "activity": {}}
    for fmt in ("json", "md", "csv", "html"):
        files = em.export(empty, "user-ghost", [fmt])
        assert len(files) == 1


def test_filenames_are_deterministic_and_safe(em, user_report):
    files = em.export(user_report, "user-torvalds", ["json", "md", "csv", "html"])
    for f in files:
        name = f.split("/")[-1]
        assert name.startswith("gitspyx_user-torvalds_")
        assert "/" not in name[len("gitspyx_user-torvalds_"):]


def test_stats_panel_wraps_content_not_full_width(user_report, monkeypatch):
    """Aggregate Statistics box must size to content, like the profile table.

    Regression: Panel defaults to expand=True and stretched edge-to-edge.
    """
    import io
    import re

    from rich.console import Console

    from gitspyx import ui

    buf = io.StringIO()
    test_console = Console(file=buf, width=200, force_terminal=True, _environ={})
    monkeypatch.setattr(ui, "console", test_console)
    ui.render(user_report, "user")
    out = re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue())  # strip ANSI colors

    lines = out.splitlines()
    title_idx = next(i for i, ln in enumerate(lines) if "Aggregate Statistics" in ln)
    # The stats block is now a Rich Table: centered title line, then the box.
    top = next(ln for ln in lines[title_idx:] if ln.strip().startswith("╭"))
    bottom = next(ln for ln in lines[title_idx:] if ln.strip().startswith("╰"))
    box_width = len(top.strip())
    assert box_width < 100, f"Stats box spans {box_width} cols — table is expanding to full width"
    # and it must actually close on screen (right border present)
    assert "╮" in top and "╯" in bottom
    # Bullet-style left-aligned labels, same as the profile table (#49)
    joined = "\n".join(lines[title_idx:])
    assert "• Repositories" in joined
    assert "• Total stars" in joined
