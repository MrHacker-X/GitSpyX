#!/usr/bin/env python3
"""Verify pyproject.toml version matches gitspyx.__version__.

Works on Python 3.9+ by using ``tomllib`` (3.11+) with a ``tomli`` fallback;
``tomli`` is declared as a dev dependency so every CI matrix leg has it.
This script exists as a file (rather than an inline heredoc) so it is covered
by the offline test-suite regression guard against tomllib-only imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.9/3.10 CI legs
    import tomli as tomllib

import gitspyx


def main() -> int:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)
    declared = pyproject["project"]["version"]
    actual = gitspyx.__version__
    if declared != actual:
        print(
            f"Version mismatch: pyproject={declared} package={actual}",
            file=sys.stderr,
        )
        return 1
    print(f"Version consistent: {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
