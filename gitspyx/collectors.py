"""Intelligence collectors: turn raw API payloads into structured reports.

Design rules:
    * Only fetch what the command actually needs (``fetch_extra=False`` by
      default for plain user lookups; orgs/gists/activity are opt-in).
    * Label anything fetched from a single Events/Commits page as "recent".
    * Never trust optional fields; contributors/events can contain nulls.
    * Optional enrichment (languages/contributors/branches/orgs/gists/
      activity) degrades gracefully on *recoverable* errors, but the
      degradation is recorded in ``report["warnings"]`` so an empty section
      cannot be mistaken for "genuinely no data". Fatal conditions —
      authentication, rate limiting, network failure — propagate to the CLI
      instead of silently producing hollow reports.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from .client import GitSpyXClient
from .exceptions import GitSpyXError
from .utils import parse_repo_slug

MAX_DEEP_LIMIT = 20
DEFAULT_DEEP_LIMIT = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_warning(report: dict, section: str, exc: Exception) -> None:
    """Record graceful degradation of an optional section."""
    report.setdefault("warnings", []).append(
        f"{section}: section unavailable ({type(exc).__name__}: {exc})"
    )


def _fetch_optional(report: dict, section: str, func, default):
    """Run an optional enrichment fetch; degrade with a warning on failure.

    Returns the fetched value or ``default``. Fatal conditions (auth,
    rate limit, network) are re-raised; only other API errors (e.g. 404 on
    an optional sub-endpoint, 422) degrade gracefully.
    """
    try:
        return func()
    except (GitSpyXError,) as exc:
        if getattr(exc, "exit_code", 1) in (2, 3, 5):
            raise  # network / auth / rate limit: fatal for the whole scan
        _add_warning(report, section, exc)
        return default
    except Exception as exc:  # defensive: malformed payloads etc.
        _add_warning(report, section, exc)
        return default


# ---------------------------------------------------------------------------
# User reports
# ---------------------------------------------------------------------------

def collect_user(
    client: GitSpyXClient,
    username: str,
    include_repos: bool = True,
    fetch_extra: bool = False,
    max_pages: int = 100,
    max_items: Optional[int] = None,
) -> dict:
    """Profile (+ aggregates when repos fetched).

    ``fetch_extra`` additionally pulls organizations, gists and recent public
    activity — only used when the caller will actually surface them.
    """
    profile = client.user(username)
    report: dict[str, Any] = {
        "subject": username,
        "profile": profile,
        "collected_at": _now_iso(),
    }

    if include_repos:
        repos = client.user_repos(username, max_pages=max_pages, max_items=max_items)
        report["repositories"] = repos
        report["stats"] = _repo_aggregates(repos)
        report["repositories_truncated"] = bool(getattr(client, "last_pagination_truncated", False))

    if fetch_extra:
        report["organizations"] = _fetch_optional(
            report, "organizations", lambda: client.user_orgs(username), []
        )
        gists = _fetch_optional(report, "gists", lambda: client.user_gists(username), [])
        report["gists"] = gists
        report["gists_truncated"] = isinstance(gists, list) and len(gists) >= 100
        events = _fetch_optional(
            report, "activity", lambda: client.user_events(username, per_page=100), []
        )
        report["activity"] = _activity_summary(events)
        report["activity_note"] = (
            f"Based on the {report['activity'].get('events_analyzed', 0)} most recent public events only — "
            "not complete lifetime history."
        )

    return report


def _repo_aggregates(repos: list) -> dict:
    """Compute stars/forks/language/attention aggregates over a repo list."""
    stars = sum(r.get("stargazers_count") or 0 for r in repos)
    forks = sum(r.get("forks_count") or 0 for r in repos)
    watchers = sum(r.get("subscribers_count") or 0 for r in repos)
    issues = sum(r.get("open_issues_count") or 0 for r in repos)

    lang_counter: Counter = Counter()
    star_by_lang: dict[str, int] = {}
    for r in repos:
        lang = r.get("language")
        if lang:
            lang_counter[lang] += 1
            star_by_lang[lang] = star_by_lang.get(lang, 0) + (r.get("stargazers_count") or 0)

    top_starred = sorted(repos, key=lambda r: r.get("stargazers_count") or 0, reverse=True)[:5]
    top_forked = sorted(repos, key=lambda r: r.get("forks_count") or 0, reverse=True)[:5]
    most_starred = top_starred[0] if top_starred else None

    return {
        "total_repos": len(repos),
        "total_stars": stars,
        "total_forks": forks,
        "total_watchers": watchers,
        "total_open_issues": issues,
        "languages": dict(lang_counter.most_common()),
        "star_by_language": star_by_lang,
        "top_starred": [
            {"name": r.get("name"), "stars": r.get("stargazers_count") or 0, "url": r.get("html_url")}
            for r in top_starred
        ],
        "top_forked": [
            {"name": r.get("name"), "forks": r.get("forks_count") or 0, "url": r.get("html_url")}
            for r in top_forked
        ],
        "most_starred": {"name": most_starred.get("name"), "stars": most_starred.get("stargazers_count") or 0}
        if most_starred
        else None,
        "avg_stars_per_repo": round(stars / len(repos), 2) if repos else 0.0,
        "forked_share_pct": round(100 * sum(1 for r in repos if r.get("fork")) / len(repos), 1) if repos else 0.0,
    }


def _activity_summary(events: list) -> dict:
    """Summarise recent public events: type counts, top repos, active days."""
    type_counts: Counter = Counter(e.get("type") for e in events if e.get("type"))
    repo_counts: Counter = Counter(
        e.get("repo", {}).get("name") for e in events if isinstance(e.get("repo"), dict) and e["repo"].get("name")
    )
    day_counts: Counter = Counter()
    for e in events:
        created = e.get("created_at")
        if created:
            day_counts[str(created)[:10]] += 1
    return {
        "events_analyzed": len(events),
        "event_types": dict(type_counts.most_common()),
        "top_active_repos": dict(repo_counts.most_common(5)),
        "most_active_day": max(day_counts, key=day_counts.get) if day_counts else None,
    }


def collect_repo_activity(
    client: GitSpyXClient, owner: str, repo: str, commit_limit: int = 30, event_limit: int = 30
) -> dict:
    """Recent commit stream + recent public events for one repository."""
    commits = client.repo_commits(owner, repo, per_page=commit_limit) or []
    events = client.repo_events(owner, repo, per_page=event_limit) or []

    authors: Counter = Counter()
    for c in commits:
        login = (c.get("author") or {}).get("login") if isinstance(c.get("author"), dict) else None
        if not login:
            commit_meta = c.get("commit") if isinstance(c.get("commit"), dict) else {}
            login = ((commit_meta.get("author") or {}).get("name")) or "unknown"
        authors[login] += 1
    event_types: Counter = Counter(e.get("type") for e in events if e.get("type"))

    recent_commits = []
    for c in commits[:15]:
        commit_meta = c.get("commit") if isinstance(c.get("commit"), dict) else {}
        author_meta = commit_meta.get("author") or {}
        message = (commit_meta.get("message") or "").splitlines()
        recent_commits.append(
            {
                "sha": (c.get("sha") or "")[:8],
                "author": author_meta.get("name") or "unknown",
                "login": (c.get("author") or {}).get("login") if isinstance(c.get("author"), dict) else None,
                "date": author_meta.get("date"),
                "message": message[0][:120] if message else "",
            }
        )

    return {
        "subject": f"{owner}/{repo}",
        "recent_commits": recent_commits,
        "commits_note": f"Most recent {len(recent_commits)} commits on the default branch.",
        "top_committers": dict(authors.most_common(10)),
        "event_types": dict(event_types.most_common()),
        "events_analyzed": len(events),
        "events_note": f"Based on the {len(events)} most recent public events for this repository.",
        "collected_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Repo / org / search reports
# ---------------------------------------------------------------------------

def collect_repo(
    client: GitSpyXClient,
    owner_repo: str,
    deep: bool = True,
    max_pages: int = 10,
) -> dict:
    """Full repository dossier. ``owner_repo`` must be ``owner/name``."""
    owner, repo = parse_repo_slug(owner_repo)  # raises ValueError on malformed
    data = client.repo(owner, repo)
    report: dict[str, Any] = {"subject": f"{owner}/{repo}", "repository": data, "collected_at": _now_iso()}

    if deep:
        report["languages"] = _fetch_optional(
            report, "languages", lambda: client.repo_languages(owner, repo), {}
        )
        contribs = _fetch_optional(
            report, "contributors", lambda: client.repo_contributors(owner, repo, max_pages=max_pages), []
        )
        report["contributors"] = [_safe_contributor(c) for c in (contribs or [])[:20]]
        branches = _fetch_optional(
            report, "branches", lambda: client.repo_branches(owner, repo, max_pages=2), []
        )
        report["branches"] = [b.get("name") for b in (branches or []) if isinstance(b, dict) and b.get("name")]

    return report


def _safe_contributor(c: Any) -> dict:
    """Normalise a contributor entry, tolerating nulls/anonymous entries."""
    if not isinstance(c, dict):
        return {"login": "anonymous", "contributions": c.get("contributions") if isinstance(c, dict) else 0}
    login = c.get("login")
    contributions = c.get("contributions")
    try:
        contributions = int(contributions or 0)
    except (TypeError, ValueError):
        contributions = 0
    return {
        "login": login or "anonymous",
        "contributions": contributions,
        "type": c.get("type") or "User",
        "html_url": c.get("html_url") if login else None,
    }


def collect_org(client: GitSpyXClient, org: str) -> dict:
    """Organization metadata report."""
    data = client.org(org.strip())
    return {"subject": org.strip(), "organization": data, "collected_at": _now_iso()}


def collect_search(client: GitSpyXClient, query: str) -> dict:
    """User search; the raw query is sent URL-encoded by the client."""
    data = client.search_users(query) or {}
    items = data.get("items") or []
    return {
        "subject": query,
        "total_count": data.get("total_count", len(items)),
        "incomplete_results": bool(data.get("incomplete_results", False)),
        "results": items,
        "collected_at": _now_iso(),
    }


def collect_full_report(
    client: GitSpyXClient,
    username: str,
    deep_limit: int = DEFAULT_DEEP_LIMIT,
    fetch_extra: bool = True,
) -> dict:
    """Deep scan: user aggregates + contributor insight on top repositories.

    Makes one contributors request per selected repo — bounded by
    ``deep_limit`` (capped at :data:`MAX_DEEP_LIMIT`) so the request count
    stays predictable.
    """
    deep_limit = max(0, min(int(deep_limit), MAX_DEEP_LIMIT))
    report = collect_user(client, username, include_repos=True, fetch_extra=fetch_extra)
    repos = report.get("repositories") or []

    top = sorted(repos, key=lambda r: r.get("stargazers_count") or 0, reverse=True)[:deep_limit]
    enriched = []
    for r in top:
        owner_login = (r.get("owner") or {}).get("login") if isinstance(r.get("owner"), dict) else None
        if not owner_login or not r.get("name"):
            continue
        try:
            contribs = client.repo_contributors(owner_login, r["name"], max_pages=1) or []
        except GitSpyXError as exc:
            if getattr(exc, "exit_code", 1) in (2, 3, 5):
                raise  # network / auth / rate limit: fatal
            _add_warning(report, f"deep_dive:{r.get('name')}", exc)
            continue
        except Exception as exc:
            _add_warning(report, f"deep_dive:{r.get('name')}", exc)
            continue
        enriched.append(
            {
                "repo": r.get("name"),
                "stars": r.get("stargazers_count") or 0,
                "url": r.get("html_url"),
                "top_contributors": [_safe_contributor(c) for c in contribs[:10]],
            }
        )
    report["deep_dive"] = enriched
    report["deep_dive_limit"] = deep_limit
    return report
