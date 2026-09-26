"""Export layer: JSON, Markdown, CSV and self-contained HTML reports.

All writers are report-type aware (user / repo / repo-activity / org /
search) and tolerate missing or null API fields. JSON remains the canonical
full structured output; MD/HTML expose the human-readable sections; CSV
exposes the most meaningful table for the report type.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .utils import format_count, safe_str

EXPORT_DIR = "output-gitspyx"

# Cells starting with these characters can execute as formulas in Excel /
# LibreOffice / Google Sheets (CSV injection). The tab and CR prefixes are
# the documented Word/Excel bypass variants.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in exported cells.

    A cell beginning with ``= + - @`` (or the tab/CR/LF bypass forms) is
    prefixed with a single quote, which spreadsheets treat as literal text.
    Numbers, bools and ordinary strings pass through untouched so legitimate
    values are not corrupted.
    """
    if not isinstance(value, str):
        return value  # ints/bools/None are inert
    if value.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _esc(value: Any) -> str:
    """Minimal HTML escaping for report values."""
    s = str(value if value is not None else "")
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


class SafeHTML:
    """Marker wrapper for *internally generated* trusted HTML fragments.

    Cells wrapped in :class:`SafeHTML` bypass :func:`_esc` inside
    :meth:`ExportManager._html_table`. ONLY ever wrap markup this module
    itself constructs from already-escaped components (e.g. ``<a>`` tags
    whose href and label were escaped first). Never wrap raw API data.
    """

    __slots__ = ("html",)

    def __init__(self, html: str):
        self.html = html

    def __repr__(self) -> str:  # keep debug output honest
        return f"SafeHTML({self.html!r})"


def _anchor(url: Any, label: Any) -> SafeHTML:
    """Build a trusted anchor from escaped href + escaped label.

    The href is additionally validated: anything not looking like an http(s)
    URL or a relative path falls back to '#' so ``javascript:`` and other
    scheme-injection payloads cannot be smuggled through API data.
    """
    raw = str(url or "").strip()
    if raw.lower().startswith(("http://", "https://", "/")) and " " not in raw:
        href = _esc(raw)
    else:
        href = "#"
    return SafeHTML(f'<a href="{href}">{_esc(label)}</a>')


class ExportManager:
    """Writes timestamped, collision-safe report files under ``output-gitspyx/``."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(EXPORT_DIR)
        self._used_names: set[str] = set()

    def _prepare(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def _stamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

    def export(self, report: dict, slug: str, formats: list[str]) -> list[str]:
        """Export a report in the requested formats; returns file paths."""
        written: list[str] = []
        for fmt in formats:
            fmt = fmt.lower().lstrip(".")
            path = self._prepare() / f"gitspyx_{slug}_{self._stamp()}.{fmt}"
            # Collision avoidance when several exports share a second.
            n = 1
            while str(path) in self._used_names and n < 100:
                path = self._prepare() / f"gitspyx_{slug}_{self._stamp()}_{n}.{fmt}"
                n += 1
            self._used_names.add(str(path))
            writer = getattr(self, f"_write_{fmt}", None)
            if writer is None:
                continue
            writer(report, path)
            written.append(str(path))
        return written

    # ------------------------------------------------------------------ JSON
    def _write_json(self, report: dict, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False, default=str)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
        out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        for row in rows:
            cells = [str(c if c is not None else "").replace("|", "\\|") for c in row]
            out.append("| " + " | ".join(cells) + " |")
        return out

    @staticmethod
    def _html_table(headers: list[str], rows: list[list[Any]]) -> str:
        head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
        body_parts = []
        for row in rows:
            cells = []
            for c in row:
                if isinstance(c, SafeHTML):
                    cells.append(c.html)  # trusted: built from escaped parts
                else:
                    cells.append(_esc(c))
            body_parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        return f"<table><tr>{head}</tr>{''.join(body_parts)}</table>"

    @staticmethod
    def _contributor_rows(contribs: list) -> list[list[Any]]:
        rows = []
        for c in contribs:
            if not isinstance(c, dict):
                continue
            login = c.get("login") or "anonymous"
            rows.append([login, safe_str(c.get("type"), "User"), format_count(c.get("contributions"))])
        return rows

    # -------------------------------------------------------------- Markdown
    def _write_markdown(self, report: dict, path: Path) -> None:
        lines: list[str] = [f"# GitSpyX Report — {safe_str(report.get('subject'), 'unknown')}", ""]
        lines.append(f"_Generated {datetime.now().astimezone().strftime('%d %B %Y at %H:%M:%S %Z')}_")
        lines.append("")

        profile = report.get("profile") or {}
        if profile:
            lines.append("## Profile")
            lines.append("")
            for key in ("login", "name", "company", "location", "blog", "email", "twitter_username"):
                if profile.get(key):
                    lines.append(f"- **{key.replace('_', ' ').title()}:** {profile[key]}")
            lines.append(
                f"- **Followers:** {format_count(profile.get('followers'))} · "
                f"**Following:** {format_count(profile.get('following'))} · "
                f"**Public repos:** {format_count(profile.get('public_repos'))}"
            )
            lines.append("")

        stats = report.get("stats") or {}
        if stats:
            lines.append("## Aggregate Statistics")
            lines.append("")
            lines += self._md_table(
                ["Metric", "Value"],
                [
                    ["Total repositories", format_count(stats.get("total_repos"))],
                    ["Total stars", format_count(stats.get("total_stars"))],
                    ["Total forks", format_count(stats.get("total_forks"))],
                    ["Subscribers (watchers)", format_count(stats.get("total_watchers"))],
                    ["Open issues", format_count(stats.get("total_open_issues"))],
                    ["Avg stars/repo", stats.get("avg_stars_per_repo", 0)],
                ],
            )
            lines.append("")

            languages = stats.get("languages") or {}
            if languages:
                lines.append("### Languages")
                lines.append("")
                total = sum(languages.values())
                lines += self._md_table(
                    ["Language", "Repos", "Share"],
                    [[lang, format_count(count), f"{(count / total * 100) if total else 0:.0f}%"]
                     for lang, count in languages.items()],
                )
                lines.append("")

            for key, title, metric in (("top_starred", "Top Starred", "stars"), ("top_forked", "Top Forked", "forks")):
                entries = stats.get(key) or []
                if entries:
                    lines.append(f"### {title}")
                    lines.append("")
                    lines += self._md_table(
                        ["Repository", metric.title(), "URL"],
                        [[e.get("name"), format_count(e.get(metric)), e.get("url")] for e in entries],
                    )
                    lines.append("")

        # -r repository table
        repos = report.get("repositories") or []
        if repos:
            lines.append("## Repositories")
            lines.append("")
            lines += self._md_table(
                ["Name", "Language", "Stars", "Forks", "Fork", "Pushed"],
                [
                    [
                        r.get("name"),
                        safe_str(r.get("language"), "—"),
                        format_count(r.get("stargazers_count")),
                        format_count(r.get("forks_count")),
                        "yes" if r.get("fork") else "no",
                        safe_str(r.get("pushed_at"), "—")[:10],
                    ]
                    for r in repos
                ],
            )
            lines.append("")

        # deep dive
        deep = report.get("deep_dive") or []
        if deep:
            lines.append("## Deep Dive — Top Contributors per Repository")
            lines.append("")
            for entry in deep:
                lines.append(f"### {safe_str(entry.get('repo'), '?')} ({format_count(entry.get('stars'))} ★)")
                lines.append("")
                contribs = entry.get("top_contributors") or []
                if contribs:
                    lines += self._md_table(
                        ["Contributor", "Type", "Commits"],
                        [[c.get("login") or "anonymous", safe_str(c.get("type"), "User"),
                          format_count(c.get("contributions"))] for c in contribs],
                    )
                else:
                    lines.append("_No contributor data available._")
                lines.append("")

        # repository dossier
        repository = report.get("repository") or {}
        if repository:
            lines.append("## Repository")
            lines.append("")
            lic = repository.get("license") or {}
            parent = repository.get("parent") or {}
            lines.append(f"- **URL:** {safe_str(repository.get('html_url'))}")
            lines.append(f"- **Stars:** {format_count(repository.get('stargazers_count'))}")
            lines.append(f"- **Forks:** {format_count(repository.get('forks_count'))}")
            lines.append(f"- **Subscribers (watchers):** {format_count(repository.get('subscribers_count'))}")
            lines.append(f"- **Open issues:** {format_count(repository.get('open_issues_count'))}")
            lines.append(f"- **License:** {safe_str(lic.get('name'))}")
            lines.append(f"- **Default branch:** {safe_str(repository.get('default_branch'))}")
            lines.append(f"- **Visibility:** {safe_str(repository.get('visibility'))}")
            lines.append(f"- **Archived:** {'Yes' if repository.get('archived') else 'No'} · "
                         f"**Fork:** {'Yes' if repository.get('fork') else 'No'}")
            if repository.get("fork") and parent.get("full_name"):
                lines.append(f"- **Parent repo:** {parent.get('full_name')}")
            lines.append(f"- **Created:** {safe_str(repository.get('created_at'))}")
            lines.append(f"- **Updated:** {safe_str(repository.get('updated_at'))}")
            lines.append(f"- **Last push:** {safe_str(repository.get('pushed_at'))}")
            lines.append("")

        langs = report.get("languages") or {}
        if langs:
            lines.append("### Language Breakdown (bytes)")
            lines.append("")
            total = sum(langs.values())
            lines += self._md_table(
                ["Language", "Bytes", "Share"],
                [[lang, format_count(n), f"{(n / total * 100) if total else 0:.0f}%"] for lang, n in langs.items()],
            )
            lines.append("")

        contribs = report.get("contributors") or []
        if contribs:
            lines.append("### Contributors")
            lines.append("")
            lines += self._md_table(
                ["Contributor", "Type", "Commits"], self._contributor_rows(contribs)
            )
            lines.append("")

        branches = report.get("branches") or []
        if branches:
            lines.append(f"### Branches ({len(branches)})")
            lines.append("")
            lines.append(", ".join(str(b) for b in branches))
            lines.append("")

        # activity report
        commits = report.get("recent_commits") or []
        if commits:
            lines.append("## Recent Commits")
            lines.append("")
            lines += self._md_table(
                ["SHA", "Author", "Date", "Message"],
                [[c.get("sha"), c.get("author"), safe_str(c.get("date"), "—")[:10],
                  (c.get("message") or "")[:60]] for c in commits],
            )
            lines.append("")
        committers = report.get("top_committers") or {}
        if committers:
            lines.append("### Top Committers (recent commits)")
            lines.append("")
            lines += self._md_table(
                ["Committer", "Commits"],
                [[name, format_count(n)] for name, n in committers.items()],
            )
            lines.append("")
        event_types = report.get("event_types") or {}
        if event_types:
            lines.append(f"### Recent Public Events ({report.get('events_analyzed', 0)} analyzed)")
            lines.append("")
            lines += self._md_table(["Event Type", "Count"], [[k, format_count(v)] for k, v in event_types.items()])
            lines.append("")

        # org
        org = report.get("organization") or {}
        if org:
            lines.append("## Organization")
            lines.append("")
            for label, key in (
                ("Name", "name"), ("Description", "description"), ("Location", "location"),
                ("Blog", "blog"), ("Email", "email"), ("Public repos", "public_repos"),
                ("Followers", "followers"), ("Created", "created_at"),
            ):
                val = org.get(key)
                if val:
                    lines.append(f"- **{label}:** {val}")
            lines.append("")

        # search
        results = report.get("results") or []
        if results:
            lines.append(f"## Search Results — {format_count(report.get('total_count'))} total matches")
            lines.append("")
            lines += self._md_table(
                ["Username", "Type", "Profile"],
                [[u.get("login"), safe_str(u.get("type"), "User"), u.get("html_url")] for u in results],
            )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    # md is the user-facing alias for the markdown writer.
    _write_md = _write_markdown

    # -------------------------------------------------------------------- CSV
    def _write_csv(self, report: dict, path: Path) -> None:
        """Pick the most meaningful table for the report type."""
        rows: list[dict] = []
        if report.get("repositories"):
            rows = [
                {
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "language": r.get("language"),
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "subscribers": r.get("subscribers_count", 0),
                    "open_issues": r.get("open_issues_count", 0),
                    "is_fork": bool(r.get("fork")),
                    "updated_at": r.get("updated_at"),
                    "pushed_at": r.get("pushed_at"),
                    "url": r.get("html_url"),
                }
                for r in report["repositories"]
            ]
        elif report.get("results"):
            rows = [
                {"login": u.get("login"), "type": u.get("type", "User"), "id": u.get("id"), "url": u.get("html_url")}
                for u in report["results"]
            ]
        elif report.get("contributors"):
            rows = [
                {"login": c.get("login") or "anonymous", "type": safe_str(c.get("type"), "User"),
                 "contributions": c.get("contributions", 0)}
                for c in report["contributors"]
                if isinstance(c, dict)
            ]
        elif report.get("recent_commits"):
            rows = [
                {"sha": c.get("sha"), "author": c.get("author"), "login": c.get("login"),
                 "date": c.get("date"), "message": c.get("message")}
                for c in report["recent_commits"]
            ]
        elif report.get("organization"):
            org = report["organization"]
            rows = [{"field": k, "value": str(v)} for k, v in org.items() if k not in ("owner",)]
        elif report.get("repository"):
            # Repo dossier without contributor data: fall back to language bytes.
            rows = [
                {"language": lang, "bytes": n}
                for lang, n in (report.get("languages") or {}).items()
            ]

        with open(path, "w", encoding="utf-8", newline="") as fh:
            if not rows:
                fh.write("no_tabular_data\n")
                return
            safe_rows = [
                {k: _csv_safe(v) for k, v in row.items()} for row in rows
            ]
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(safe_rows)

    # ------------------------------------------------------------------- HTML
    def _write_html(self, report: dict, path: Path) -> None:
        subject = _esc(safe_str(report.get("subject"), "unknown"))
        stats = report.get("stats") or {}

        sections: list[str] = []

        # Stat cards for user reports
        if stats:
            cards = "".join(
                f'<div class="card"><div class="num">{_esc(format_count(stats.get(k)))}</div>'
                f'<div class="lbl">{lbl}</div></div>'
                for k, lbl in (
                    ("total_repos", "Repositories"),
                    ("total_stars", "Stars"),
                    ("total_forks", "Forks"),
                    ("total_watchers", "Subscribers"),
                )
            )
            sections.append(f'<div class="cards">{cards}</div>')

        profile = report.get("profile") or {}
        if profile:
            sections.append("<h2>Profile</h2>")
            sections.append(
                self._html_table(
                    ["Field", "Value"],
                    [
                        ["Username", safe_str(profile.get("login"))],
                        ["Name", safe_str(profile.get("name"))],
                        ["Bio", safe_str(profile.get("bio"))],
                        ["Location", safe_str(profile.get("location"))],
                        ["Followers", format_count(profile.get("followers"))],
                        ["Following", format_count(profile.get("following"))],
                        ["Public repos", format_count(profile.get("public_repos"))],
                        ["Created", safe_str(profile.get("created_at"))],
                    ],
                )
            )

        langs = stats.get("languages") or {}
        if langs:
            total = sum(langs.values())
            sections.append("<h2>Language Distribution</h2>")
            sections.append(
                self._html_table(
                    ["Language", "Repos", "Share"],
                    [
                        [lang, format_count(count),
                         # Trusted markup: lang name is escaped separately;
                         # only numeric percentages are interpolated here.
                         SafeHTML(
                             f'<div class="bar"><span style="width:{(count / total * 100) if total else 0:.0f}%"></span></div> '
                             f"{_esc(f'{(count / total * 100) if total else 0:.0f}%')}"
                         )]
                        for lang, count in langs.items()
                    ],
                )
            )

        top = stats.get("top_starred") or []
        if top:
            sections.append("<h2>Top Starred</h2>")
            sections.append(
                self._html_table(
                    ["Repository", "Stars"],
                    [[_anchor(e.get("url"), e.get("name") or "N/A"),
                      format_count(e.get("stars"))] for e in top],
                )
            )

        repos = report.get("repositories") or []
        if repos:
            sections.append(f"<h2>Repositories ({len(repos)})</h2>")
            sections.append(
                self._html_table(
                    ["Name", "Language", "Stars", "Forks", "Fork", "Pushed"],
                    [
                        [r.get("name"), safe_str(r.get("language"), "—"), format_count(r.get("stargazers_count")),
                         format_count(r.get("forks_count")), "yes" if r.get("fork") else "no",
                         safe_str(r.get("pushed_at"), "—")[:10]]
                        for r in repos[:50]
                    ],
                )
            )

        deep = report.get("deep_dive") or []
        for entry in deep:
            sections.append(
                f"<h2>Deep Dive — {_esc(safe_str(entry.get('repo'), '?'))} ({_esc(format_count(entry.get('stars')))} ★)</h2>"
            )
            contribs = entry.get("top_contributors") or []
            if contribs:
                sections.append(
                    self._html_table(
                        ["Contributor", "Type", "Commits"],
                        [[c.get("login") or "anonymous", safe_str(c.get("type"), "User"),
                          format_count(c.get("contributions"))] for c in contribs],
                    )
                )

        repository = report.get("repository") or {}
        if repository:
            lic = repository.get("license") or {}
            parent = repository.get("parent") or {}
            rows = [
                ["URL", _anchor(repository.get("html_url"), safe_str(repository.get("full_name")))],
                ["Description", safe_str(repository.get("description"))],
                ["Stars", format_count(repository.get("stargazers_count"))],
                ["Forks", format_count(repository.get("forks_count"))],
                ["Subscribers (watchers)", format_count(repository.get("subscribers_count"))],
                ["Open issues", format_count(repository.get("open_issues_count"))],
                ["License", safe_str(lic.get("name"))],
                ["Default branch", safe_str(repository.get("default_branch"))],
                ["Visibility", safe_str(repository.get("visibility"))],
                ["Archived", "Yes" if repository.get("archived") else "No"],
                ["Fork", "Yes" if repository.get("fork") else "No"],
            ]
            if repository.get("fork") and parent.get("full_name"):
                rows.append(["Parent repo", safe_str(parent.get("full_name"))])
            rows += [
                ["Created", safe_str(repository.get("created_at"))],
                ["Updated", safe_str(repository.get("updated_at"))],
                ["Last push", safe_str(repository.get("pushed_at"))],
            ]
            sections.append("<h2>Repository</h2>")
            sections.append(self._html_table(["Field", "Value"], rows))

        repo_langs = report.get("languages") or {}
        if repo_langs:
            total = sum(repo_langs.values())
            sections.append("<h2>Language Breakdown</h2>")
            sections.append(
                self._html_table(
                    ["Language", "Bytes", "Share"],
                    [
                        [lang, format_count(n),
                         # Trusted markup: same construction as above.
                         SafeHTML(
                             f'<div class="bar"><span style="width:{(n / total * 100) if total else 0:.0f}%"></span></div> '
                             f"{_esc(f'{(n / total * 100) if total else 0:.0f}%')}"
                         )]
                        for lang, n in repo_langs.items()
                    ],
                )
            )

        contribs = report.get("contributors") or []
        if contribs:
            sections.append("<h2>Contributors</h2>")
            sections.append(
                self._html_table(["Contributor", "Type", "Commits"], self._contributor_rows(contribs))
            )

        branches = report.get("branches") or []
        if branches:
            sections.append(f"<h2>Branches ({len(branches)})</h2>")
            sections.append("<p>" + _esc(", ".join(str(b) for b in branches)) + "</p>")

        commits = report.get("recent_commits") or []
        if commits:
            sections.append("<h2>Recent Commits</h2>")
            sections.append(
                self._html_table(
                    ["SHA", "Author", "Date", "Message"],
                    [[c.get("sha"), c.get("author"), safe_str(c.get("date"), "—")[:10],
                      (c.get("message") or "")[:60]] for c in commits],
                )
            )
        committers = report.get("top_committers") or {}
        if committers:
            sections.append("<h2>Top Committers (recent commits)</h2>")
            sections.append(
                self._html_table(["Committer", "Commits"], [[n, format_count(v)] for n, v in committers.items()])
            )
        event_types = report.get("event_types") or {}
        if event_types:
            sections.append(f"<h2>Recent Public Events ({report.get('events_analyzed', 0)} analyzed)</h2>")
            sections.append(
                self._html_table(["Event Type", "Count"], [[k, format_count(v)] for k, v in event_types.items()])
            )

        org = report.get("organization") or {}
        if org:
            sections.append("<h2>Organization</h2>")
            sections.append(
                self._html_table(
                    ["Field", "Value"],
                    [
                        ["Name", safe_str(org.get("name"))],
                        ["Description", safe_str(org.get("description"))],
                        ["Location", safe_str(org.get("location"))],
                        ["Blog", safe_str(org.get("blog"))],
                        ["Email", safe_str(org.get("email"))],
                        ["Public repos", format_count(org.get("public_repos"))],
                        ["Followers", format_count(org.get("followers"))],
                        ["Created", safe_str(org.get("created_at"))],
                    ],
                )
            )

        results = report.get("results") or []
        if results:
            sections.append(f"<h2>Search Results — {_esc(format_count(report.get('total_count')))} total matches</h2>")
            sections.append(
                self._html_table(
                    ["Username", "Type", "Profile"],
                    [[u.get("login"), safe_str(u.get("type"), "User"),
                      _anchor(u.get("html_url"), u.get("html_url") or "")]
                     for u in results],
                )
            )

        if not sections:
            sections.append("<p>No data available for this report.</p>")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>GitSpyX Report — {subject}</title>
<style>
  :root {{ --bg:#0d1117; --fg:#c9d1d9; --accent:#4A90E2; --good:#7ED321; }}
  body {{ background:var(--bg); color:var(--fg); font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;
         max-width:960px; margin:0 auto; padding:2rem; }}
  h1 {{ color:var(--accent); border-bottom:1px solid #21262d; padding-bottom:.4rem; }}
  h2 {{ color:var(--good); margin-top:2rem; }}
  .cards {{ display:flex; gap:1rem; flex-wrap:wrap; margin:1.5rem 0; }}
  .card {{ background:#161b22; border:1px solid #21262d; border-radius:10px; padding:1rem 1.4rem; min-width:130px; }}
  .num {{ font-size:1.9rem; font-weight:700; color:var(--accent); }}
  .lbl {{ color:#8b949e; font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; }}
  th, td {{ text-align:left; padding:.5rem .8rem; border-bottom:1px solid #21262d; }}
  th {{ color:var(--accent); }}
  a {{ color:var(--accent); text-decoration:none; }}
  .bar {{ display:inline-block; width:160px; height:10px; background:#21262d; border-radius:5px; overflow:hidden; }}
  .bar span {{ display:block; height:100%; background:linear-gradient(90deg,#4A90E2,#7ED321); }}
  footer {{ margin-top:3rem; color:#8b949e; font-size:.8rem; }}
</style>
</head>
<body>
<h1>🕵️ GitSpyX Report — {subject}</h1>
<p><em>Generated {datetime.now().astimezone().strftime('%d %B %Y at %H:%M:%S %Z')} by GitSpyX</em></p>
{chr(10).join(sections)}
<footer>Self-contained report — no external assets. Data © GitHub, collected under GitHub API ToS.</footer>
</body>
</html>"""
        path.write_text(html, encoding="utf-8")
