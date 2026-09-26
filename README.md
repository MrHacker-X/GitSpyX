# GitSpyX - Advanced GitHub Intelligence Tool

<div align="center">

```
 ██████╗ ██╗████████╗███████╗██████╗ ██╗   ██╗██╗  ██╗
██╔════╝ ██║╚══██╔══╝██╔════╝██╔══██╗╚██╗ ██╔╝╚██╗██╔╝
██║  ███╗██║   ██║   ███████╗██████╔╝ ╚████╔╝  ╚███╔╝
██║   ██║██║   ██║   ╚════██║██╔═══╝   ╚██╔╝   ██╔██╗
╚██████╔╝██║   ██║   ███████║██║        ██║   ██╔╝ ██╗
 ╚═════╝ ╚═╝   ╚═╝   ╚══════╝╚═╝        ╚═╝   ╚═╝  ╚═╝
```

**Advanced open-source intelligence (OSINT) for GitHub reconnaissance.**

[![PyPI version](https://img.shields.io/pypi/v/gitspyx?style=for-the-badge&color=brightgreen)](https://pypi.org/project/gitspyx/)
[![Python](https://img.shields.io/pypi/pyversions/gitspyx?style=for-the-badge&color=blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/pypi/l/gitspyx?style=for-the-badge&color=green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/MrHacker-X/GitSpyX?style=for-the-badge&logo=github)](https://github.com/MrHacker-X/GitSpyX)
[![Issues](https://img.shields.io/github/issues/MrHacker-X/GitSpyX?style=for-the-badge&color=orange)](https://github.com/MrHacker-X/GitSpyX/issues)

[![Install](https://img.shields.io/badge/pip%20install-gitspyx-0088CC?style=for-the-badge&logo=pypi)](https://pypi.org/project/gitspyx/)

</div>

---

## 📋 Table of Contents

- [What's New in v3](#-whats-new-in-v3)
- [Overview](#-overview)
- [Installation](#-installation)
- [Usage](#-usage)
- [Intelligence Modes](#-intelligence-modes)
- [Exports](#-exports)
- [API Tokens & Rate Limits](#-api-tokens--rate-limits)
- [Caching](#-caching)
- [Exit Codes](#-exit-codes)
- [Development & Testing](#-development--testing)
- [Project Structure](#-project-structure)
- [License](#-license)
- [Developer](#-developer)

## 🆕 What's New in v3

GitSpyX 3.x is a ground-up rewrite of the classic single-script tool:

| | v2.3 | v3.1 |
|---|---|---|
| **Architecture** | One 400-line script | Installable `gitspyx` package, importable API |
| **API client** | Bare `requests.get`, no retries | Sessions, exponential-backoff retries, timeout control |
| **Rate limit behaviour** | Crash with raw HTTP error | Distinct errors, local-time reset hints, `--rate-limit` meter |
| **Auth** | Not supported | `--token` > `GITHUB_TOKEN` > `GH_TOKEN` (5,000 req/hour) |
| **Caching** | None | Persistent ETag conditional requests - repeat runs cost **0 credits** |
| **Intelligence** | Raw field dumps | Star/fork/language aggregates, top-repo rankings, contributor insight, commit timelines, recent activity summaries |
| **Output** | JSON only | JSON · Markdown · CSV · self-contained dark-mode HTML |
| **Terminal UI** | Plain tables | Gradient banner, highlighted section headings, language share bars |
| **Errors & exit codes** | Always 0 | Distinct codes per failure class (CI-friendly) |
| **Safety** | Unsanitised filenames | Path-safe slugs, CSV formula-injection protection, HTML XSS escaping |
| **Testing** | None | 160+ offline pytest tests, CI matrix (3.9–3.13), live E2E runner |

## 🔮 Overview

GitSpyX gathers detailed intelligence about GitHub users, organizations and
repositories: profiles with aggregate statistics, repository dossiers with
language breakdowns and contributor insight, commit timelines, user search and
org metadata - rendered as Rich dashboards in the terminal and exported in the
format your workflow needs.

## 🚀 Installation

### From PyPI (recommended)

```bash
pip install gitspyx
gitspyx --help
```

### From source (this checkout)

```bash
git clone https://github.com/MrHacker-X/GitSpyX.git
cd GitSpyX
pip install .
gitspyx --help
```

### Classic invocation (no install)

```bash
pip install -r requirements.txt
python3 gitspyx.py -u <username>     # legacy shim, still works
python3 -m gitspyx -u <username>     # canonical form
```

> Upgrading from an old PyPI release? Uninstall first to avoid a stale
> shadow copy: `pip uninstall gitspyx && pip install gitspyx`

## 🎯 Usage

```
gitspyx -u <username>                    profile + aggregate statistics
gitspyx -u <username> -r                 + full repository table
gitspyx -u <username> --deep             deep scan: contributor insight on top repos
gitspyx -u <username> --deep --deep-limit 5
gitspyx -i owner/repo                    full repository dossier
gitspyx -i owner/repo --activity         + commit stream & event timeline
gitspyx -s "search query"                user search (quote multi-word queries)
gitspyx -o <org>                         organization metadata
gitspyx -u <username> -f json md html    choose export formats
gitspyx -u <username> --max-items 200    cap repository pagination
gitspyx --rate-limit                     inspect your remaining API budget
gitspyx --clear-cache                    purge the local ETag cache
gitspyx --no-display -u <user>           fully silent automation mode
```

**Legacy syntax** from classic GitSpyX still works:

```
gitspyx -u OWNER -i REPO                 translated to: gitspyx -i OWNER/REPO
python3 gitspyx.py -u OWNER -i REPO      same via the shim file
```

### Flag semantics

- **`-r / --repos`** controls *terminal rendering only*: the full repository
  table prints only with `-r`. Aggregate statistics are always computed from
  the repository data (one paginated fetch), so plain `-u` still shows totals
  without dumping every repo.
- **`--deep`** renders a per-repository contributor panel in the terminal *and*
  includes the data in every export. `--deep-limit N` (default 3, max 20)
  bounds the number of extra contributor requests.
- **`--no-display`** is fully silent - no banner, no tables, no summary, no
  save messages. Export files are still written; errors go to stderr with a
  non-zero exit code. Ideal for cron/CI: `gitspyx -u X --no-display -f json`.
- **`--max-pages` / `--max-items`** cap pagination on large accounts. Truncation
  is reported in the output and exports (`repositories_truncated: true`).

## 🕵️ Intelligence Modes

- **User mode (`-u`)** - profile fields plus computed aggregates: total
  stars/forks/watchers/issues, language distribution with bars, top starred &
  forked repositories, fork share, averages.
- **Repo mode (`-i owner/repo`)** - full dossier: metrics, license, topics,
  homepage, per-language byte breakdown, top contributors and branch list.
- **Activity mode (`-i owner/repo --activity`)** - recent commit stream with
  authors, top-committer share bars, and public event timeline summary.
- **Search mode (`-s`)** - URL-encoded user search with total-match count.
- **Org mode (`-o`)** - public organization metadata.

## 📤 Exports

Successful runs write timestamped, path-safe files under `output-gitspyx/`:

| Format | Flag | Contents |
|---|---|---|
| JSON | `-f json` | Complete raw report, API-faithful |
| Markdown | `-f md` | GitHub-flavoured tables, ready to paste into issues/PRs |
| CSV | `-f csv` | Repo or search-result rows for spreadsheets, formula-injection safe |
| HTML | `-f html` | Self-contained dark-mode dashboard - zero external assets |

```bash
gitspyx -u torvalds -f json md html
# Saved: output-gitspyx/gitspyx_user-torvalds_2026-09-26_101741.json
# Saved: output-gitspyx/gitspyx_user-torvalds_2026-09-26_101741.md
# Saved: output-gitspyx/gitspyx_user-torvalds_2026-09-26_101741.html
```

## 🔑 API Tokens & Rate Limits

Unauthenticated GitHub API access is capped at **60 requests/hour**. Set a
token to raise this to **5,000/hour**. Token precedence (first match wins):

1. `--token` flag
2. `GITHUB_TOKEN` environment variable
3. `GH_TOKEN` environment variable
4. unauthenticated

Tokens are never written to cache files, exports, or error messages.

```bash
export GITHUB_TOKEN=ghp_yourtokenhere   # recommended
gitspyx -u torvalds                     # picked up automatically
gitspyx --rate-limit                    # live budget from response headers
```

The client tracks `X-RateLimit-Limit/Remaining/Used/Reset` from every response
and surfaces the remaining budget in the session footer. Primary exhaustion
(403 + `X-RateLimit-Remaining: 0`), secondary throttling (403/429 with an
exact `Retry-After` wait), and plain 403s (private/blocked) are distinguished;
only transient failures (network, 5xx, 429) are retried.

## 💾 Caching

v3 stores API responses under `~/.cache/gitspyx` and revalidates them with
`ETag`/`If-None-Match`. Unchanged data is served from disk, so re-running the
same scan costs **zero** rate-limit credits. Disable with `--no-cache`, purge
with `--clear-cache`.

## 🚦 Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic failure (bad arguments, invalid identifiers) |
| 2 | Network error (DNS, timeout, connection) |
| 3 | Authentication error (invalid token) |
| 4 | Not found (user/repo/org) |
| 5 | Rate limit exhausted (primary or secondary) |
| 6 | Other GitHub API error |
| 7 | Export/write failure |
| 130 | Interrupted (Ctrl+C) |

## 🛠 Development & Testing

```bash
pip install -e ".[dev]"
pytest                      # offline unit suite, no network needed
RUN_INTEGRATION=1 pytest tests/test_integration.py   # optional live-API tests
python -m compileall gitspyx
```

### End-to-end test runner

Exercises the real CLI against the live GitHub API using stable public
targets (`octocat`, `octocat/Hello-World`, `github/.github`). Strictly
read-only - it performs GET requests only and writes nothing to the repo.

```bash
# Fast essentials (user scan, repo scan, CLI smoke, error handling):
python scripts/e2e_test.py --smoke

# Everything, plus JSON/CSV/HTML export inspection, cache behaviour,
# pagination bounds and org scan:
python scripts/e2e_test.py --full

# Optional: better API limits during E2E runs
GITHUB_TOKEN=ghp_yourtoken python scripts/e2e_test.py --full
```

The runner never hardcodes or prints tokens. Checks that hit the hourly
rate limit are reported as `SKIP` (not failures); all other failures count
toward a non-zero exit code. Reports and temp files are created in a
TemporaryDirectory and cleaned up automatically.

CI (`.github/workflows/ci.yml`) runs the tests on Python 3.9–3.13 plus CLI
smoke checks on every push and PR.

### Project Structure

```
GitSpyX/
├── gitspyx/                 # Installable package
│   ├── __init__.py          # Public API surface
│   ├── __main__.py          # CLI entry point
│   ├── banner.py            # Gradient terminal banner
│   ├── client.py            # Resilient API client (retries, cache, tokens)
│   ├── collectors.py        # Intelligence collectors & aggregates
│   ├── ui.py                # Rich dashboards & section headings
│   ├── exporters.py         # JSON / Markdown / CSV / HTML writers
│   ├── cache.py             # Persistent ETag cache
│   ├── exceptions.py        # Typed error hierarchy + exit codes
│   └── utils.py             # Validation & sanitising helpers
├── gitspyx.py               # Legacy shim (python3 gitspyx.py still works)
├── scripts/e2e_test.py      # Live E2E runner (--smoke / --full)
├── checks/version_check.py  # Version consistency guard
├── tests/                   # Offline pytest suite
├── pyproject.toml           # Packaging & entry points
└── .github/workflows/ci.yml # CI matrix
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👨‍💻 Developer

<div align="center">

### Alex Butler
**Vritra Security Organization**

[![GitHub](https://img.shields.io/badge/GitHub-MrHacker--X-181717?style=for-the-badge&logo=github)](https://github.com/MrHacker-X)
[![Website](https://img.shields.io/badge/Website-vritrasec.com-FF6B6B?style=for-the-badge&logo=firefox)](https://vritrasec.com)
[![Instagram](https://img.shields.io/badge/Instagram-vritrasec-E4405F?style=for-the-badge&logo=instagram)](https://instagram.com/vritrasec)
[![YouTube](https://img.shields.io/badge/YouTube-Technolex-FF0000?style=for-the-badge&logo=youtube)](https://youtube.com/@Technolex)

### 📱 Telegram Channels

[![Main Channel](https://img.shields.io/badge/Main--Channel-MrHacker--X-0088CC?style=for-the-badge&logo=telegram)](https://t.me/MrHackerX)
[![Central](https://img.shields.io/badge/Central-LinkCentralX-0088CC?style=for-the-badge&logo=telegram)](https://t.me/LinkCentralX)
[![VritraSec](https://img.shields.io/badge/Channel-VritraSec-0088CC?style=for-the-badge&logo=telegram)](https://t.me/VritraSec)
[![Support Bot](https://img.shields.io/badge/Support-ethicxbot-0088CC?style=for-the-badge&logo=telegram)](https://t.me/ethicxbot)

</div>
