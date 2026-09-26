"""Rich terminal presentation layer for GitSpyX reports.

All renderers tolerate missing/null API fields (issue #33) and label
single-page data as "recent" (issues #34, #35).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .utils import format_count, safe_str

console = Console()

BLUE = "#4A90E2"
ORANGE = "#F5A623"
GREEN = "#7ED321"
PURPLE = "#BD10E0"


def _fmt_dt(iso_str: Any) -> str:
    """Human-readable datetime in the system's local timezone.

    GitHub timestamps are UTC; they are converted to local time for display
    (issue: users expect local clock times). Tolerates missing/garbage input.
    """
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()  # -> system local timezone
        tz_name = local.tzname() or "local"
        return local.strftime(f"%d %b %Y %H:%M {tz_name}")
    except (ValueError, TypeError):
        return safe_str(iso_str)


def _bar(pct: float, width: int = 25) -> str:
    filled = max(0, min(width, int(pct / (100 / width))))
    return "█" * filled + "░" * (width - filled)


def _section(title: str) -> None:
    """Print a left-aligned, highlighted section heading.

    Every section in every report mode uses this so headings are visually
    consistent: dark text on an orange highlight bar, flush left.
    """
    console.print(f"[bold #1a1a1a on {ORANGE}] {title} [/bold #1a1a1a on {ORANGE}]")


def render(report: dict, mode: str) -> None:
    """Dispatch to the right renderer for a report dict."""
    dispatch = {
        "user": render_user_report,
        "repo": render_repo_report,
        "repo_activity": render_repo_activity,
        "org": render_org_report,
        "search": render_search_report,
    }
    fn = dispatch.get(mode)
    if fn is None:
        console.print(f"[bold red]Unknown render mode '{mode}'[/bold red]")
        return
    fn(report)


# ---------------------------------------------------------------------------
# User reports
# ---------------------------------------------------------------------------

def render_user_report(report: dict) -> None:
    profile = report.get("profile") or {}
    stats = report.get("stats") or {}

    _section(f"Profile Intelligence: {safe_str(profile.get('login'), report.get('subject', '?'))}")
    table = Table(
        show_header=True,
        header_style=f"bold {BLUE}",
        box=box.ROUNDED,
    )
    table.add_column("Field", style=ORANGE, width=24)
    table.add_column("Value", style=f"bold {GREEN}")
    for label, value in (
        ("• Name", profile.get("name")),
        ("• Username", f"@{profile.get('login')}" if profile.get("login") else None),
        ("• Bio", profile.get("bio")),
        ("• Company", profile.get("company")),
        ("• Location", profile.get("location")),
        ("• Blog", profile.get("blog")),
        ("• Email", profile.get("email")),
        ("• Twitter", f"@{profile.get('twitter_username')}" if profile.get("twitter_username") else None),
        ("• Public Repos", format_count(profile.get("public_repos"))),
        ("• Followers", format_count(profile.get("followers"))),
        ("• Following", format_count(profile.get("following"))),
        ("• Public Gists", format_count(profile.get("public_gists"))),
        ("• Type", profile.get("type")),
        ("• Hireable", "Yes" if profile.get("hireable") else "No"),
        ("• Created", _fmt_dt(profile.get("created_at"))),
        ("• Profile updated", _fmt_dt(profile.get("updated_at"))),
    ):
        table.add_row(label, safe_str(value))
    console.print(table)

    if stats:
        render_stats_panel(stats)
    else:
        console.print("[yellow]No repository data available.[/yellow]")

    _render_extra_sections(report)
    if report.get("repositories_truncated"):
        console.print("[yellow]Note: repository list was truncated by pagination limits; "
                      "aggregates cover the fetched subset only.[/yellow]")


def render_repositories_table(report: dict) -> None:
    """Full repository table (shown with -r / --repos)."""
    repos = report.get("repositories") or []
    if not repos:
        console.print("[yellow]No public repositories found.[/yellow]")
        return

    _section(
        f"Repositories: {safe_str((report.get('profile') or {}).get('login'), report.get('subject', '?'))}"
        + (f" — showing {len(repos)}" if report.get("repositories_truncated") else "")
    )
    table = Table(
        show_header=True,
        header_style=f"bold {BLUE}",
        box=box.SIMPLE,
    )
    table.add_column("Name", style=f"bold {ORANGE}")
    table.add_column("Description", ratio=2, style="dim")
    table.add_column("Language", style=PURPLE)
    table.add_column("Stars", justify="right", style=GREEN)
    table.add_column("Forks", justify="right", style=GREEN)
    table.add_column("Subs", justify="right", style=GREEN)
    table.add_column("Issues", justify="right")
    table.add_column("Fork", justify="center")
    table.add_column("Updated", style="dim")
    table.add_column("Pushed", style="dim")
    for r in repos:
        table.add_row(
            safe_str(r.get("name"), "?"),
            safe_str(r.get("description"), "—"),
            safe_str(r.get("language"), "—"),
            format_count(r.get("stargazers_count")),
            format_count(r.get("forks_count")),
            format_count(r.get("subscribers_count")),
            format_count(r.get("open_issues_count")),
            "yes" if r.get("fork") else "no",
            _fmt_dt(r.get("updated_at"))[:12],
            _fmt_dt(r.get("pushed_at"))[:12],
        )
    console.print(table)


def render_deep_dive(report: dict) -> None:
    """Deep-scan section: contributor insight per top repository."""
    deep = report.get("deep_dive") or []
    if not deep:
        return
    for entry in deep:
        contribs = entry.get("top_contributors") or []
        _section(
            f"Deep Dive: {safe_str(entry.get('repo'), '?')}"
            f" ({format_count(entry.get('stars'))} ★)"
        )
        table = Table(
            show_header=True,
            header_style=f"bold {BLUE}",
            box=box.SIMPLE,
        )
        table.add_column("#", justify="right", style="dim")
        table.add_column("Contributor", style=f"bold {ORANGE}")
        table.add_column("Type", style=PURPLE)
        table.add_column("Commits", justify="right", style=GREEN)
        table.add_column("Share", ratio=2)
        total = sum(c.get("contributions") or 0 for c in contribs) or 1
        if contribs:
            for i, c in enumerate(contribs, 1):
                pct = (c.get("contributions") or 0) / total * 100
                table.add_row(
                    str(i),
                    safe_str(c.get("login"), "anonymous"),
                    safe_str(c.get("type"), "User"),
                    format_count(c.get("contributions")),
                    f"[{BLUE}]{_bar(pct, 20)}[/{BLUE}] {pct:.0f}%",
                )
        else:
            table.add_row("—", "No contributor data available", "—", "—", "—")
        console.print(table)


def render_stats_panel(stats: dict) -> None:
    """Aggregate stats: same two-column bullet style as the profile table."""
    most_starred = stats.get("most_starred")

    _section("Aggregate Statistics")
    table = Table(
        show_header=True,
        header_style=f"bold {BLUE}",
        box=box.ROUNDED,
    )
    table.add_column("Field", style=ORANGE, width=24)
    table.add_column("Value", style=f"bold {GREEN}")
    rows: list[tuple[str, str]] = [
        ("• Repositories", format_count(stats.get("total_repos"))),
        ("• Total stars", format_count(stats.get("total_stars"))),
        ("• Total forks", format_count(stats.get("total_forks"))),
        ("• Subscribers (watchers)", format_count(stats.get("total_watchers"))),
        ("• Open issues", format_count(stats.get("total_open_issues"))),
    ]
    if most_starred:
        rows.append(
            ("• Most starred", f"{safe_str(most_starred.get('name'))} ({format_count(most_starred.get('stars'))} ★)")
        )
    rows.append(("• Avg stars/repo", str(stats.get("avg_stars_per_repo", 0))))
    rows.append(("• Forked repos", f"{stats.get('forked_share_pct', 0)}%"))
    for label, value in rows:
        table.add_row(label, value)
    console.print(table)

    languages = stats.get("languages") or {}
    if languages:
        _section("Language Distribution")
        lang_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        lang_table.add_column("Language", style=f"bold {PURPLE}", ratio=1)
        lang_table.add_column("Repos", justify="right", style=GREEN)
        lang_table.add_column("Share", ratio=3)
        total = sum(languages.values())
        for lang, count in languages.items():
            pct = (count / total) * 100 if total else 0
            lang_table.add_row(safe_str(lang), format_count(count), f"[{BLUE}]{_bar(pct)}[/{BLUE}] {pct:.0f}%")
        console.print(lang_table)

    for key, label, metric_key in (
        ("top_starred", "Top Starred Repositories", "stars"),
        ("top_forked", "Top Forked Repositories", "forks"),
    ):
        entries = stats.get(key) or []
        if entries:
            _section(label)
            t = Table(show_header=True, header_style=f"bold {BLUE}", box=box.SIMPLE)
            t.add_column("Repository", style=f"bold {ORANGE}")
            t.add_column(metric_key.title(), justify="right", style=GREEN)
            t.add_column("URL", style="dim")
            for e in entries:
                t.add_row(safe_str(e.get("name"), "N/A"), format_count(e.get(metric_key)), safe_str(e.get("url"), ""))
            console.print(t)


def _render_extra_sections(report: dict) -> None:
    """Show orgs/gists/recent-activity summaries when they were fetched."""
    orgs = report.get("organizations") or []
    if orgs:
        names = ", ".join(safe_str(o.get("login"), "?") for o in orgs if isinstance(o, dict))
        _section(f"Organizations ({len(orgs)})")
        console.print(Panel(names or "None", border_style=PURPLE, expand=False))

    gists = report.get("gists") or []
    if gists:
        _section("Gists")
        console.print(
            Panel(
                f"{len(gists)} public gists" + (" (first page)" if report.get("gists_truncated") else ""),
                border_style=PURPLE,
                expand=False,
            )
        )

    activity = report.get("activity") or {}
    if activity:
        parts = [f"Events analyzed: {activity.get('events_analyzed', 0)}"]
        types = activity.get("event_types") or {}
        if types:
            top_types = ", ".join(f"{k} ({v})" for k, v in list(types.items())[:5])
            parts.append(f"Top event types: {top_types}")
        top_repos = activity.get("top_active_repos") or {}
        if top_repos:
            parts.append("Most active in: " + ", ".join(list(top_repos.keys())[:3]))
        note = report.get("activity_note")
        body = "\n".join(parts) + (f"\n[dim]{note}[/dim]" if note else "")
        _section("Recent Public Activity")
        console.print(Panel(body, border_style=BLUE, expand=False))


# ---------------------------------------------------------------------------
# Repo reports
# ---------------------------------------------------------------------------

def render_repo_report(report: dict) -> None:
    data = report.get("repository") or {}

    _section(f"Repository Dossier: {safe_str(data.get('full_name'), report.get('subject', '?'))}")
    table = Table(
        show_header=True,
        header_style=f"bold {BLUE}",
        box=box.ROUNDED,
    )
    table.add_column("Field", style=ORANGE, width=24)
    table.add_column("Value", style=f"bold {GREEN}")
    lic = data.get("license") or {}
    parent = data.get("parent") or {}
    source = data.get("source") or {}
    rows = [
        ("• Description", safe_str(data.get("description"))),
        ("• URL", safe_str(data.get("html_url"))),
        ("• Homepage", safe_str(data.get("homepage"))),
        ("• Language", safe_str(data.get("language"))),
        ("• Default Branch", safe_str(data.get("default_branch"))),
        ("• Size (KB)", format_count(data.get("size"))),
        ("• Stars", format_count(data.get("stargazers_count"))),
        ("• Subscribers / Watchers", format_count(data.get("subscribers_count"))),
        ("• Forks", format_count(data.get("forks_count"))),
        ("• Open Issues", format_count(data.get("open_issues_count"))),
        ("• License", safe_str(lic.get("name"))),
        ("• Topics", ", ".join(data.get("topics") or []) or "N/A"),
        ("• Visibility", safe_str(data.get("visibility"))),
        ("• Archived", "Yes" if data.get("archived") else "No"),
        ("• Is Fork", "Yes" if data.get("fork") else "No"),
        ("• Parent Repo", safe_str(parent.get("full_name")) if data.get("fork") else None),
        ("• Source Repo", safe_str(source.get("full_name")) if data.get("fork") else None),
        ("• Created At", _fmt_dt(data.get("created_at"))),
        ("• Updated At", _fmt_dt(data.get("updated_at"))),
        ("• Last Push", _fmt_dt(data.get("pushed_at"))),
    ]
    for label, value in rows:
        if value is None:
            continue
        table.add_row(label, str(value))
    console.print(table)

    languages = report.get("languages") or {}
    if languages:
        total = sum(languages.values())
        _section("Language Breakdown (bytes)")
        lang_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        lang_table.add_column("Language", style=f"bold {PURPLE}", ratio=1)
        lang_table.add_column("Bytes", justify="right", style=GREEN)
        lang_table.add_column("Share", ratio=3)
        for lang, nbytes in languages.items():
            pct = (nbytes / total) * 100 if total else 0
            lang_table.add_row(safe_str(lang), format_count(nbytes), f"[{BLUE}]{_bar(pct)}[/{BLUE}] {pct:.0f}%")
        console.print(lang_table)
    else:
        console.print("[dim]No language data available.[/dim]")

    contribs = report.get("contributors") or []
    if contribs:
        _section("Top Contributors")
        ct = Table(show_header=True, header_style=f"bold {BLUE}", box=box.SIMPLE)
        ct.add_column("#", justify="right", style="dim")
        ct.add_column("Contributor", style=f"bold {ORANGE}")
        ct.add_column("Type", style=PURPLE)
        ct.add_column("Commits", justify="right", style=GREEN)
        for i, c in enumerate(contribs[:10], 1):
            ct.add_row(str(i), safe_str(c.get("login"), "anonymous"), safe_str(c.get("type"), "User"),
                       format_count(c.get("contributions")))
        console.print(ct)
    else:
        console.print("[dim]No contributor data available.[/dim]")

    branches = report.get("branches") or []
    if branches:
        _section(f"Branches ({len(branches)})")
        console.print(Panel(", ".join(str(b) for b in branches), border_style=PURPLE, expand=False))
    else:
        console.print("[dim]No branch data available.[/dim]")


def render_repo_activity(report: dict) -> None:
    commits = report.get("recent_commits") or []
    if commits:
        _section("Recent Commits")
        ct = Table(show_header=True, header_style=f"bold {BLUE}", box=box.SIMPLE)
        ct.add_column("SHA", style=ORANGE)
        ct.add_column("Author", style=PURPLE)
        ct.add_column("Message", ratio=2)
        for c in commits:
            ct.add_row(safe_str(c.get("sha"), ""), safe_str(c.get("author"), "unknown"),
                       safe_str(c.get("message"), "")[:80])
        console.print(ct)
        if report.get("commits_note"):
            console.print(f"[dim]{report['commits_note']}[/dim]")
    else:
        console.print("[yellow]No recent commit data available (empty repository?).[/yellow]")

    committers = report.get("top_committers") or {}
    if committers:
        _section("Top Committers (recent commits)")
        t = Table(show_header=True, header_style=f"bold {BLUE}", box=box.SIMPLE)
        t.add_column("Committer", style=f"bold {ORANGE}")
        t.add_column("Commits", justify="right", style=GREEN)
        t.add_column("Share", ratio=2)
        total = sum(committers.values()) or 1
        for name, count in committers.items():
            pct = count / total * 100
            t.add_row(safe_str(name), format_count(count), f"[{BLUE}]{_bar(pct, 20)}[/{BLUE}] {pct:.0f}%")
        console.print(t)

    events = report.get("event_types") or {}
    if events:
        _section("Recent Public Events")
        et = Table(show_header=True, header_style=f"bold {BLUE}", box=box.SIMPLE)
        et.add_column("Event Type", style=PURPLE)
        et.add_column("Count", justify="right", style=GREEN)
        et.add_column("Share", ratio=2)
        total = sum(events.values()) or 1
        for etype, count in events.items():
            pct = count / total * 100
            et.add_row(safe_str(etype), format_count(count), f"[{BLUE}]{_bar(pct, 20)}[/{BLUE}] {pct:.0f}%")
        console.print(et)
        if report.get("events_note"):
            console.print(f"[dim]{report['events_note']}[/dim]")
    else:
        console.print("[dim]No recent public events for this repository.[/dim]")


# ---------------------------------------------------------------------------
# Org / search reports
# ---------------------------------------------------------------------------

def render_org_report(report: dict) -> None:
    org = report.get("organization") or {}
    _section(f"Organization: {safe_str(org.get('login'), report.get('subject', '?'))}")
    table = Table(
        show_header=True,
        header_style=f"bold {BLUE}",
        box=box.ROUNDED,
    )
    table.add_column("Field", style=ORANGE, width=24)
    table.add_column("Value", style=f"bold {GREEN}")
    for label, value in (
        ("• Name", safe_str(org.get("name"))),
        ("• Description", safe_str(org.get("description"))),
        ("• Location", safe_str(org.get("location"))),
        ("• Blog", safe_str(org.get("blog"))),
        ("• Email", safe_str(org.get("email"))),
        ("• Twitter", f"@{org.get('twitter_username')}" if org.get("twitter_username") else None),
        ("• Public Repos", format_count(org.get("public_repos"))),
        ("• Followers", format_count(org.get("followers"))),
        ("• Created At", _fmt_dt(org.get("created_at"))),
        ("• Updated At", _fmt_dt(org.get("updated_at"))),
    ):
        if value is None:
            continue
        table.add_row(label, str(value))
    console.print(table)


def render_search_report(report: dict) -> None:
    results = report.get("results") or []
    if not results:
        console.print(f"[yellow]No users found for query '{report.get('subject')}'.[/yellow]")
        return
    _section(f"Search: '{report.get('subject')}' — {format_count(report.get('total_count'))} matches")
    table = Table(
        show_header=True,
        header_style=f"bold {BLUE}",
        box=box.ROUNDED,
    )
    table.add_column("Username", style=f"bold {ORANGE}")
    table.add_column("Type", style=PURPLE)
    table.add_column("ID", justify="right", style=GREEN)
    table.add_column("Profile URL", style="dim")
    for user in results:
        table.add_row(
            safe_str(user.get("login"), "?"),
            safe_str(user.get("type"), "User"),
            str(user.get("id", "?")),
            safe_str(user.get("html_url"), ""),
        )
    console.print(table)
    if report.get("incomplete_results"):
        console.print("[yellow]GitHub flagged these results as incomplete (try a more specific query).[/yellow]")
