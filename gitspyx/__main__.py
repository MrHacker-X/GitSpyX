#!/usr/bin/env python3
"""GitSpyX — Advanced GitHub Intelligence CLI.

Usage via ``python3 -m gitspyx`` or the installed ``gitspyx`` entry point.
The root ``gitspyx.py`` shim routes here too, translating the legacy
``-u OWNER -i REPO`` syntax to repository investigation.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import __version__
from .banner import print_banner as _render_banner
from .client import GitSpyXClient
from .collectors import (
    DEFAULT_DEEP_LIMIT,
    MAX_DEEP_LIMIT,
    collect_full_report,
    collect_org,
    collect_repo,
    collect_repo_activity,
    collect_search,
    collect_user,
)
from .exceptions import GitSpyXError
from .exporters import ExportManager
from .ui import BLUE, GREEN, ORANGE, PURPLE, render, render_deep_dive, render_repositories_table
from .utils import build_output_slug, parse_repo_slug

# Regular report output goes to stdout; errors/warnings to stderr (#30).
console = Console()
err_console = Console(stderr=True)

def print_banner() -> None:
    """Render the gradient wordmark + info panel + gradient rule."""
    _render_banner(console)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitspyx",
        description="GitSpyX — Advanced GitHub Intelligence & OSINT Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  gitspyx -u torvalds                    profile + aggregates
  gitspyx -u torvalds -r                 include full repository table
  gitspyx -u torvalds --deep             deep scan (contributor insight on top repos)
  gitspyx -u torvalds --deep --deep-limit 5
  gitspyx -i owner/repo                  full repository dossier
  gitspyx -i owner/repo --activity       recent commits + public event timeline
  gitspyx -s "john doe"                  search users (quoted)
  gitspyx -o github                      organization metadata
  gitspyx -u torvalds -f json md html    export in three formats
  gitspyx -u torvalds --max-items 200    cap repository pagination
  gitspyx --rate-limit                   check your API budget
  gitspyx --clear-cache                  purge the local ETag cache

legacy syntax (still supported):
  gitspyx -u OWNER -i REPO               same as: gitspyx -i OWNER/REPO
""",
    )
    parser.add_argument("-u", "--username", help="GitHub username to investigate.")
    parser.add_argument("-r", "--repos", action="store_true", help="Print the full repository table.")
    parser.add_argument("--deep", action="store_true", help="Deep scan: contributor insight for top repos.")
    parser.add_argument("--deep-limit", type=int, default=DEFAULT_DEEP_LIMIT, metavar="N",
                        help=f"Repos to deep-dive with --deep (default {DEFAULT_DEEP_LIMIT}, max {MAX_DEEP_LIMIT}).")
    parser.add_argument("-i", "--investigate", metavar="OWNER/REPO", help="Investigate a repository (owner/name).")
    parser.add_argument("--activity", action="store_true", help="With -i: recent commits + event timeline.")
    parser.add_argument("-s", "--search", help="Search GitHub users (quote multi-word queries).")
    parser.add_argument("-o", "--org", help="Fetch organization metadata.")
    parser.add_argument("-f", "--format", nargs="+", default=["json"], choices=["json", "md", "csv", "html"],
                        help="Export formats (default: json).")
    parser.add_argument("--token", help="GitHub personal access token (or set GITHUB_TOKEN; overrides GH_TOKEN).")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds (default 30).")
    parser.add_argument("--max-pages", type=int, default=100, metavar="N",
                        help="Max pages per paginated endpoint (default 100).")
    parser.add_argument("--max-items", type=int, default=None, metavar="N",
                        help="Cap total paginated items (e.g. repositories).")
    parser.add_argument("--no-cache", action="store_true", help="Disable the persistent ETag cache.")
    parser.add_argument("--clear-cache", action="store_true", help="Purge the local cache and exit.")
    parser.add_argument("--rate-limit", action="store_true", help="Show remaining API budget and exit.")
    parser.add_argument("--no-display", action="store_true",
                        help="Fully silent: no banner/tables/summary; exports only (automation mode).")
    parser.add_argument("--about", action="store_true", help="About GitSpyX.")
    parser.add_argument("--connect", action="store_true", help="Developer links.")
    parser.add_argument("-v", "--version", action="store_true", help="Show version.")
    return parser


def show_about() -> None:
    about = f"""GitSpyX is an advanced open-source intelligence (OSINT) tool for
GitHub reconnaissance. v{__version__} ships a resilient API client (tokens,
retries, ETag caching), deep-dive collectors, Rich dashboards, and
multi-format exports (JSON / Markdown / CSV / self-contained HTML).

Developed and maintained by Vritra Security Organization."""
    console.print(Panel(Text(about, justify="center"), title="About GitSpyX", border_style=f"bold {BLUE}"))


def show_connect() -> None:
    links = """GitHub:    https://github.com/MrHacker-X
Instagram: https://instagram.com/vritrasec
YouTube:   https://youtube.com/@Technolex
Website:   https://vritrasec.com
Community: t.me/MrHackerX
Channel:   t.me/LinkCentralX
Main:      t.me/VritraSec"""
    console.print(Panel(Text(links), title="Connect with the Developer", border_style=f"bold {ORANGE}"))


def validate_args(args, parser) -> Optional[str]:
    """Local argument validation; returns an error message or None."""
    if args.username and any([args.investigate, args.search, args.org]):
        return "The -u/--username flag cannot be combined with -i, -s, or -o."
    if args.investigate and any([args.search, args.org]):
        return "The -i/--investigate flag cannot be combined with -s or -o."
    if args.search and args.org:
        return "Use either -s (search) or -o (org), not both."
    if (args.repos or args.deep) and not args.username:
        return "The -r/--repos and --deep flags require a username (-u)."
    if args.activity and not args.investigate:
        return "The --activity flag requires -i OWNER/REPO."
    if args.deep_limit < 0:
        return "--deep-limit must be >= 0."
    if args.max_pages < 1:
        return "--max-pages must be >= 1."
    if args.max_items is not None and args.max_items < 1:
        return "--max-items must be >= 1."
    # Validate identifiers locally before any API call (#19, #20).
    if args.username:
        from .utils import is_valid_github_login

        if not is_valid_github_login(args.username):
            return f"'{args.username}' is not a valid GitHub username."
    if args.org:
        from .utils import is_valid_github_login

        if not is_valid_github_login(args.org):
            return f"'{args.org}' is not a valid GitHub organization name."
    try:
        if args.investigate:
            parse_repo_slug(args.investigate)
    except ValueError as exc:
        return str(exc)
    return None


def _normalize_legacy(args) -> None:
    """Translate legacy ``-u OWNER -i REPO`` into ``-i OWNER/REPO``.

    Old GitSpyX took the repo name separately; if ``args.investigate`` has no
    slash and both flags are present, join them (issue #4).
    """
    if args.username and args.investigate and "/" not in args.investigate:
        args.investigate = f"{args.username.strip()}/{args.investigate.strip()}"
        args.username = None


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return _run(args, parser)
    except GitSpyXError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc.message}")
        if exc.hint:
            err_console.print(f"[yellow]hint:[/yellow] {exc.hint}")
        return exc.exit_code
    except ValueError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    except BrokenPipeError:
        # Downstream closed the pipe (e.g. `gitspyx ... | head`): exit quietly.
        return 0


def _run(args, parser) -> int:
    _normalize_legacy(args)

    if args.version:
        console.print(f"[bold {BLUE}]GitSpyX Version: {__version__}[/bold {BLUE}]")
        return 0
    if args.about:
        show_about()
        return 0
    if args.connect:
        show_connect()
        return 0

    silent = args.no_display

    error = validate_args(args, parser)
    if error:
        err_console.print(f"[bold red]Error:[/bold red] {error}")
        return 1

    with GitSpyXClient(
        token=args.token, timeout=args.timeout, use_cache=not args.no_cache, quiet=silent
    ) as client:
        if args.clear_cache:
            n = client.cache.clear() if client.cache else 0
            console.print(f"[bold {GREEN}]Cache cleared ({n} entries).[/bold {GREEN}]")
            return 0

        if args.rate_limit:
            data = client.rate_limit() or {}
            core = (data.get("resources") or {}).get("core", {})
            state = client.rate_limit_state()
            remaining = core.get("remaining", state.get("rate_limit_remaining"))
            limit = core.get("limit", state.get("rate_limit_limit"))
            console.print(
                f"[bold {BLUE}]API budget:[/bold {BLUE}] "
                f"{remaining if remaining is not None else '?'}/{limit if limit is not None else '?'} remaining · "
                f"token: {'yes' if client.token_present else 'no (60 req/hour unauthenticated)'}"
            )
            return 0

        if not any([args.username, args.investigate, args.search, args.org]):
            print_banner()
            parser.print_help()
            return 0

        report: dict = {}
        mode: str = ""
        slug_prefix = "gitspyx"
        subject = args.username or args.investigate or args.search or args.org

        if not silent:
            console.print()
            print_banner()

        try:
            if args.username:
                slug_prefix, mode = "user", "user"
                if args.deep:
                    if args.deep_limit > MAX_DEEP_LIMIT:
                        err_console.print(
                            f"[yellow]--deep-limit capped at {MAX_DEEP_LIMIT} (was {args.deep_limit}).[/yellow]"
                        )
                    report = collect_full_report(client, args.username, deep_limit=args.deep_limit)
                else:
                    report = collect_user(
                        client, args.username,
                        include_repos=True,  # always needed for stats
                        max_pages=args.max_pages, max_items=args.max_items,
                    )
            elif args.investigate:
                slug_prefix = "repo"
                if args.activity:
                    mode = "repo_activity"
                    owner, repo = parse_repo_slug(args.investigate)
                    report = collect_repo_activity(client, owner, repo)
                else:
                    mode = "repo"
                    report = collect_repo(client, args.investigate)
            elif args.search:
                slug_prefix, mode = "search", "search"
                report = collect_search(client, args.search)
            elif args.org:
                slug_prefix, mode = "org", "org"
                report = collect_org(client, args.org)
        except ValueError as exc:
            err_console.print(f"[bold red]Error:[/bold red] {exc}")
            return 1

        if not report:
            return 1

        # Terminal rendering (#1: -r now actually controls the repo table;
        # #2: --deep renders its own section; #3: silent skips everything).
        if not silent:
            render(report, mode)
            if args.username:
                if args.deep:
                    render_deep_dive(report)
                if args.repos:
                    render_repositories_table(report)
            for warning in report.get("warnings") or []:
                err_console.print(f"[yellow]warning:[/yellow] {warning}")

        # Exports
        exporter = ExportManager()
        slug = build_output_slug(slug_prefix, str(report.get("subject", "unknown")))
        files = exporter.export(report, slug, args.format)
        if not silent:
            for f in files:
                console.print(f"[bold {BLUE}]Saved:[/bold {BLUE}] {f}")
            s = client.stats
            cache_note = f", {s['cache_hits']} served from cache" if s["cache_hits"] else ""
            retry_note = f", {s['retries']} retries" if s["retries"] else ""
            token_note = "token present" if client.token_present else "unauthenticated"
            remaining = s.get("rate_limit_remaining")
            budget_note = f", {remaining} API credits left" if remaining is not None else ""
            console.print(f"[dim]{s['requests']} HTTP requests{cache_note}{retry_note} · {token_note}{budget_note}[/dim]")

        return 0


if __name__ == "__main__":
    sys.exit(main())
