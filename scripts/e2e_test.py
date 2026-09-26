#!/usr/bin/env python3
"""GitSpyX end-to-end test runner.

Exercises the real CLI exactly as a user would (subprocess invocations of
``python -m gitspyx``) against the live GitHub API using stable public
targets. READ-ONLY: the script never performs any write operation against
GitHub — no issues, repos, follows, commits, nothing but GET requests.

Usage:
    python scripts/e2e_test.py --smoke   # fast essentials, few API calls
    python scripts/e2e_test.py --full    # everything: exports, cache, pagination

Optional:
    GITHUB_TOKEN=ghp_... python scripts/e2e_test.py --full
    (raises the API limit from 60 to 5000 requests/hour; never hardcode)

The runner stops-at-nothing: every check runs, failures are collected, and
the exit code is 0 only when all REQUIRED checks pass (skips are fine).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gitspyx  # noqa: E402  (version check + import sanity)
from gitspyx.exceptions import RateLimitError  # noqa: E402

# Stable public fixtures — widely known, not going anywhere.
USER = "octocat"
REPO_FULL = "octocat/Hello-World"
DOT_REPO_FULL = "github/.github"
ORG = "github"
SEARCH = "octocat"

PYTHON = sys.executable
CLI = [PYTHON, "-m", "gitspyx"]


# ---------------------------------------------------------------------------
# Result bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class Result:
    name: str
    state: str  # PASS / FAIL / SKIP
    detail: str = ""
    required: bool = True
    excerpt: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)
    start: float = field(default_factory=time.monotonic)

    def add(self, name: str, ok: bool | None, detail: str = "", excerpt: str = "", required: bool = True):
        state = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
        self.results.append(Result(name, state, detail, required, excerpt))
        mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[state]
        line = f"{mark} {name}"
        if detail:
            line += f" — {detail}"
        print(line)
        if excerpt:
            for line_ in excerpt.strip().splitlines()[:4]:
                print(f"       | {line_[:140]}")

    def summary(self) -> int:
        passed = sum(r.state == "PASS" for r in self.results)
        failed = sum(r.state == "FAIL" for r in self.results)
        skipped = sum(r.state == "SKIP" for r in self.results)
        duration = time.monotonic() - self.start
        print()
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Skipped: {skipped}")
        print(f"Duration: {duration:.1f}s")
        required_failures = [r for r in self.results if r.state == "FAIL" and r.required]
        return 1 if required_failures else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cli(args: list[str], cwd: Path | None = None, timeout: int = 90) -> subprocess.CompletedProcess:
    """Run the real CLI as a user would, capturing exit code and streams.

    PYTHONPATH is pinned to the repo root so a stale ``gitspyx`` from PyPI
    installed in the environment can never shadow the local package when
    the subprocess runs from a temp working directory.
    """
    env = {**os.environ, "NO_COLOR": "1"}  # deterministic output
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        CLI + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def no_traceback(proc: subprocess.CompletedProcess) -> bool:
    combined = (proc.stdout or "") + (proc.stderr or "")
    return "Traceback (most recent call last)" not in combined


def excerpt(proc: subprocess.CompletedProcess, lines: int = 3) -> str:
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return "\n".join(out.splitlines()[-lines:])


def latest_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


# ---------------------------------------------------------------------------
# 1. Environment
# ---------------------------------------------------------------------------

def check_environment(rep: Report, mode: str) -> bool:
    rep.add("Python import of gitspyx", sys.version_info >= (3, 9) or None,
            detail=f"Python {sys.version.split()[0]}")
    rep.add("GitSpyX version", gitspyx.__version__ == "3.1.0",
            detail=f"v{gitspyx.__version__}")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    rep.add("GitHub token", None if not token else True,
            detail="present via environment" if token else "not set — unauthenticated (60 req/h)",
            required=False)
    try:
        proc = subprocess.run([PYTHON, "-c", "import gitspyx; print('ok')"],
                              capture_output=True, text=True, timeout=30)
        rep.add("Module import works", proc.returncode == 0 and "ok" in proc.stdout)
    except Exception as exc:  # pragma: no cover
        rep.add("Module import works", False, detail=str(exc))
    return mode


# ---------------------------------------------------------------------------
# 2. CLI smoke tests
# ---------------------------------------------------------------------------

def check_cli_smoke(rep: Report) -> None:
    proc = run_cli(["--help"])
    rep.add("CLI help", proc.returncode == 0 and "usage:" in proc.stdout and no_traceback(proc))

    proc = run_cli(["-v"])
    rep.add("Version flag", proc.returncode == 0 and "3.1.0" in proc.stdout and no_traceback(proc))

    # Invalid combinations must fail cleanly with exit 1 and no traceback.
    proc = run_cli(["-u", USER, "-s", SEARCH])
    rep.add("Invalid flag combination",
            proc.returncode == 1 and no_traceback(proc) and "Error" in proc.stderr,
            excerpt=excerpt(proc))

    proc = run_cli(["-i", "just-a-repo-name"])
    rep.add("Malformed repo identifier",
            proc.returncode == 1 and no_traceback(proc) and "owner/repo" in (proc.stderr + proc.stdout),
            excerpt=excerpt(proc))

    proc = run_cli(["-u", "not a user!"])
    rep.add("Malformed username",
            proc.returncode == 1 and no_traceback(proc) and "not a valid GitHub username" in proc.stderr,
            excerpt=excerpt(proc))


# ---------------------------------------------------------------------------
# 3-4. Real scans through the CLI (the same path a user runs)
# ---------------------------------------------------------------------------

def check_public_scans(rep: Report, workdir: Path) -> None:
    """Real scans through the CLI. Rate-limit exhaustion (exit 5) is treated
    as a skip — the budget belongs to the user, not the test runner."""
    # Public user scan — the canonical full workflow.
    proc = run_cli(["-u", USER, "-f", "json"], cwd=workdir)
    out = proc.stdout + proc.stderr
    if proc.returncode == 5:
        rep.add("Public user scan (full CLI workflow)", None, detail="skipped: API rate limit exhausted")
        rep.add("Public repository scan", None, detail="skipped: API rate limit exhausted")
        rep.add("Dot-repository scan (github/.github)", None, detail="skipped: API rate limit exhausted")
        return
    rep.add("Public user scan (full CLI workflow)", proc.returncode == 0 and no_traceback(proc)
            and "Profile Intelligence" in out and "Aggregate Statistics" in out,
            excerpt=excerpt(proc))

    # Public repository scan.
    proc = run_cli(["-i", REPO_FULL], cwd=workdir)
    out = proc.stdout
    if proc.returncode == 5:
        rep.add("Public repository scan", None, detail="skipped: API rate limit exhausted")
    else:
        rep.add("Public repository scan",
                proc.returncode == 0 and no_traceback(proc) and "Repository Dossier" in out
                and "Last Push" in out and "Branches" in out,
                excerpt=excerpt(proc))

    # Dot-leading repository (github/.github) — validates relaxed repo naming.
    proc = run_cli(["-i", DOT_REPO_FULL], cwd=workdir)
    if proc.returncode == 5:
        rep.add("Dot-repository scan (github/.github)", None, detail="skipped: API rate limit exhausted")
    else:
        rep.add("Dot-repository scan (github/.github)",
                proc.returncode == 0 and no_traceback(proc) and "Repository Dossier" in proc.stdout,
                excerpt=excerpt(proc))


# ---------------------------------------------------------------------------
# 5. JSON export
# ---------------------------------------------------------------------------

def check_json_export(rep: Report, workdir: Path) -> None:
    proc = run_cli(["-u", USER, "-f", "json", "--no-display"], cwd=workdir)
    if proc.returncode == 5:
        rep.add("JSON export", None, detail="skipped: API rate limit exhausted")
        return
    if proc.returncode != 0:
        rep.add("JSON export", False, detail=f"exit {proc.returncode}", excerpt=excerpt(proc))
        return
    f = latest_file(workdir / "output-gitspyx", "*.json")
    if not f:
        rep.add("JSON export", False, detail="no file produced")
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as exc:
        rep.add("JSON export", False, detail=f"invalid JSON: {exc}")
        return
    problems = []
    if data.get("subject") != USER:
        problems.append("subject missing")
    for key in ("profile", "stats", "collected_at"):
        if key not in data:
            problems.append(f"missing '{key}'")
    if not isinstance((data.get("stats") or {}).get("total_repos"), int):
        problems.append("stats.total_repos not int")
    profile = data.get("profile") or {}
    if profile.get("login", "").lower() != USER:
        problems.append("profile.login mismatch")
    if f.stat().st_size < 100:
        problems.append("suspiciously empty file")
    rep.add("JSON export", not problems, detail="; ".join(problems) or f"{f.name} ({f.stat().st_size} bytes)")


# ---------------------------------------------------------------------------
# 6. CSV export (incl. formula-injection protection staying active)
# ---------------------------------------------------------------------------

def check_csv_export(rep: Report, workdir: Path) -> None:
    import csv as csvmod

    proc = run_cli(["-u", USER, "-f", "csv", "--no-display"], cwd=workdir)
    if proc.returncode == 5:
        rep.add("CSV export", None, detail="skipped: API rate limit exhausted")
        return
    if proc.returncode != 0:
        rep.add("CSV export", False, detail=f"exit {proc.returncode}", excerpt=excerpt(proc))
        return
    f = latest_file(workdir / "output-gitspyx", "*.csv")
    if not f:
        rep.add("CSV export", False, detail="no file produced")
        return
    with open(f, newline="", encoding="utf-8") as fh:
        rows = list(csvmod.reader(fh))
    problems = []
    if len(rows) < 2:
        problems.append("needs header + at least one row")
    header = rows[0] if rows else []
    expected_cols = {"name", "stars", "url"}
    if not expected_cols.issubset(set(header)):
        problems.append(f"headers missing {expected_cols - set(header)}")
    body = rows[1:]
    if any(len(r) != len(header) for r in body):
        problems.append("ragged rows (malformed CSV)")
    # Formula protection: craft a repo list with a dangerous name and export.
    from gitspyx.exporters import _csv_safe
    if _csv_safe("=cmd|' /C calc'!A0") != "'=cmd|' /C calc'!A0":
        problems.append("formula protection regressed")
    if _csv_safe("linux") != "linux":
        problems.append("normal values corrupted")
    rep.add("CSV export", not problems, detail="; ".join(problems) or f"{f.name} ({len(body)} data rows)")


# ---------------------------------------------------------------------------
# 7. HTML export
# ---------------------------------------------------------------------------

def check_html_export(rep: Report, workdir: Path) -> None:
    proc = run_cli(["-u", USER, "-f", "html", "--no-display"], cwd=workdir)
    if proc.returncode == 5:
        rep.add("HTML export", None, detail="skipped: API rate limit exhausted")
        return
    if proc.returncode != 0:
        rep.add("HTML export", False, detail=f"exit {proc.returncode}", excerpt=excerpt(proc))
        return
    f = latest_file(workdir / "output-gitspyx", "*.html")
    if not f:
        rep.add("HTML export", False, detail="no file produced")
        return
    html = f.read_text(encoding="utf-8")
    problems = []
    if len(html) < 500:
        problems.append("suspiciously small")
    if "GitSpyX Report" not in html:
        problems.append("missing report title")
    # Real anchors for repo links (trusted generated markup NOT escaped).
    if not re.search(r'<a href="https://github\.com/[^"]+">[^<]+</a>', html):
        problems.append("no clickable anchors")
    if "&lt;a " in html or "&lt;div" in html:
        problems.append("trusted markup escaped (broken links/bars)")
    # Language progress bars are real elements when language data exists.
    if "Language Distribution" in html and '<div class="bar">' not in html:
        problems.append("language bars missing/escaped")
    # XSS smoke: a hostile login must never appear raw.
    if "<script>alert" in html:
        problems.append("unescaped script tag!")
    rep.add("HTML export", not problems, detail="; ".join(problems) or f"{f.name} ({len(html)} chars)")


# ---------------------------------------------------------------------------
# 8. Cache behaviour (same scan twice)
# ---------------------------------------------------------------------------

def check_cache(rep: Report, workdir: Path) -> None:
    """Run the same scan twice (verbose, so the stats footer is printed).

    GitHub may or may not answer 304 for a given endpoint, so the invariants
    checked are: the stats line is present and internally consistent, and the
    second run never performs MORE network requests than the first.
    """
    args = ["-u", USER, "-f", "json"]
    first = run_cli(args, cwd=workdir)
    if first.returncode == 5:
        rep.add("Cache behaviour", None, detail="skipped: API rate limit exhausted")
        return
    if first.returncode != 0:
        rep.add("Cache behaviour", False, detail=f"first run exit {first.returncode}", excerpt=excerpt(first))
        return
    m1 = re.search(r"(\d+) HTTP requests(?:, (\d+) served from cache)?", first.stdout)
    second = run_cli(args, cwd=workdir)
    if second.returncode == 5:
        rep.add("Cache behaviour", None, detail="skipped: API rate limit exhausted on second run")
        return
    if second.returncode != 0:
        rep.add("Cache behaviour", False, detail=f"second run exit {second.returncode}", excerpt=excerpt(second))
        return
    m2 = re.search(r"(\d+) HTTP requests(?:, (\d+) served from cache)?", second.stdout)
    problems = []
    if not (m1 and m2):
        problems.append("session stats line not found")
    else:
        req1, cache1 = int(m1.group(1)), int(m1.group(2) or 0)
        req2, cache2 = int(m2.group(1)), int(m2.group(2) or 0)
        if req1 + cache1 == 0:
            problems.append("no activity on first run")
        if req2 + cache2 == 0:
            problems.append("no activity on second run")
        if req2 > req1:
            problems.append(f"second run did more network work ({req2} > {req1})")
    # Both runs must produce a usable JSON report.
    f = latest_file(workdir / "output-gitspyx", "*.json")
    if not f:
        problems.append("no output file")
    else:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            problems.append("latest output is not valid JSON")
    rep.add("Cache behaviour", not problems, detail="; ".join(problems) or "stats consistent across runs")


# ---------------------------------------------------------------------------
# 9. Pagination runtime (kept cheap: contributors of a mid-size repo)
# ---------------------------------------------------------------------------

def check_pagination(rep: Report, workdir: Path) -> None:
    from gitspyx.client import GitSpyXClient

    problems = []
    try:
        with GitSpyXClient(use_cache=False) as client:
            # max_pages=1 on a collection with >100 items must flag truncation.
            items = client.paginate(f"https://api.github.com/users/{USER}/repos", max_pages=1)
            if client.last_pagination_truncated is not True and len(items) >= 100:
                problems.append(f"max_pages=1 full page not flagged (n={len(items)})")
            # max_items caps results.
            items = client.paginate(f"https://api.github.com/users/{USER}/repos",
                                    max_pages=5, max_items=25)
            if len(items) > 25:
                problems.append(f"max_items ignored ({len(items)})")
            if len(items) == 25 and client.last_pagination_truncated is not True:
                problems.append("max_items hit but not flagged")
            # Small complete collection must not be flagged.
            branches = client.paginate(f"https://api.github.com/repos/{REPO_FULL}/branches", max_pages=2)
            if client.last_pagination_truncated and len(branches) < 100:
                problems.append("small collection wrongly flagged truncated")
    except RateLimitError:
        rep.add("Pagination runtime", None, detail="skipped: API rate limit exhausted")
        return
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    rep.add("Pagination runtime", not problems, detail="; ".join(problems) or "bounds + flags correct")


# ---------------------------------------------------------------------------
# 10. Error handling against the live API
# ---------------------------------------------------------------------------

def check_error_handling(rep: Report, workdir: Path) -> None:
    # Nonexistent user -> exit 4, clean error, no traceback.
    proc = run_cli(["-u", "gitspyx-no-such-user-zz9x"], cwd=workdir)
    if proc.returncode == 5:
        rep.add("Nonexistent user error", None, detail="skipped: API rate limit exhausted")
        rep.add("Nonexistent repository error", None, detail="skipped: API rate limit exhausted")
    else:
        rep.add("Nonexistent user error",
                proc.returncode == 4 and no_traceback(proc)
                and "not found" in (proc.stderr + proc.stdout).lower(),
                excerpt=excerpt(proc))
        # Nonexistent repository -> exit 4.
        proc = run_cli(["-i", "octocat/no-such-repo-zz9x"], cwd=workdir)
        if proc.returncode == 5:
            rep.add("Nonexistent repository error", None, detail="skipped: API rate limit exhausted")
        else:
            rep.add("Nonexistent repository error",
                    proc.returncode == 4 and no_traceback(proc),
                    excerpt=excerpt(proc))

    # Malformed owner/repo variants -> exit 1 before any request.
    for bad in ("owner/", "/repo", "a/b/c", "o//r"):
        proc = run_cli(["-i", bad], cwd=workdir)
        if not (proc.returncode == 1 and no_traceback(proc)):
            rep.add("Malformed owner/repo errors", False, detail=f"'{bad}' exit {proc.returncode}",
                    excerpt=excerpt(proc))
            return
    rep.add("Malformed owner/repo errors", True, detail="4 variants all rejected cleanly")


# ---------------------------------------------------------------------------
# Mode drivers
# ---------------------------------------------------------------------------

def run_smoke(rep: Report) -> None:
    print("== GitSpyX E2E — SMOKE mode ==")
    check_environment(rep, "smoke")
    check_cli_smoke(rep)
    with tempfile.TemporaryDirectory(prefix="gitspyx-e2e-") as tmp:
        workdir = Path(tmp)
        check_public_scans(rep, workdir)
        check_error_handling(rep, workdir)


def run_full(rep: Report) -> None:
    print("== GitSpyX E2E — FULL mode ==")
    check_environment(rep, "full")
    check_cli_smoke(rep)
    with tempfile.TemporaryDirectory(prefix="gitspyx-e2e-") as tmp:
        workdir = Path(tmp)
        check_public_scans(rep, workdir)
        check_json_export(rep, workdir)
        check_csv_export(rep, workdir)
        check_html_export(rep, workdir)
        check_cache(rep, workdir)
        check_pagination(rep, workdir)
        check_error_handling(rep, workdir)
        # Org scan last (optional but stable); kept cheap.
        proc = run_cli(["-o", ORG, "-f", "json", "--no-display"], cwd=workdir)
        if proc.returncode == 5:
            rep.add("Organization scan", None, detail="skipped: API rate limit exhausted",
                    required=False)
        else:
            rep.add("Organization scan", proc.returncode == 0 and no_traceback(proc),
                    excerpt=excerpt(proc), required=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitSpyX end-to-end test runner (read-only)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--smoke", action="store_true", help="fast essentials (default)")
    modes.add_argument("--full", action="store_true", help="all checks incl. exports, cache, pagination")
    args = parser.parse_args(argv)

    if shutil.which("git") and (REPO_ROOT / ".git").exists():
        pass  # informational only; the runner never touches tracked files

    rep = Report()
    try:
        if args.full:
            run_full(rep)
        else:
            run_smoke(rep)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
