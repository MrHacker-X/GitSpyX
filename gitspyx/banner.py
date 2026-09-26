#!/usr/bin/env python3
"""GitSpyX terminal banner: gradient ASCII wordmark + info panel."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__

# Large ANSI-shadow wordmark (fits standard 80-120 col terminals).
_WORDMARK = r"""
 ██████╗ ██╗████████╗███████╗██████╗ ██╗   ██╗██╗  ██╗
██╔════╝ ██║╚══██╔══╝██╔════╝██╔══██╗╚██╗ ██╔╝╚██╗██╔╝
██║  ███╗██║   ██║   ███████╗██████╔╝ ╚████╔╝  ╚███╔╝
██║   ██║██║   ██║   ╚════██║██╔═══╝   ╚██╔╝   ██╔██╗
╚██████╔╝██║   ██║   ███████║██║        ██║   ██╔╝ ██╗
 ╚═════╝ ╚═╝   ╚═╝   ╚══════╝╚═╝        ╚═╝   ╚═╝  ╚═╝
"""

_TAGLINE = "ADVANCED GITHUB INTELLIGENCE  ·  OSINT RECONNAISSANCE SUITE"

# Vertical cyberpunk-style gradient: cyan -> blue -> violet -> magenta.
_GRADIENT = (
    "#00E5FF", "#00C6FF", "#2E9BFF", "#4A7DFF", "#7A5CFF",
    "#9B4DFF", "#BD3EFF", "#DD2BFF", "#FF2BD6", "#FF3D9E",
    "#FF5070", "#FF6650",
)


def _gradient_wordmark() -> Text:
    """Apply the vertical gradient across the wordmark lines."""
    lines = [ln for ln in _WORDMARK.splitlines() if ln.strip()]
    text = Text()
    n = len(lines)
    for i, line in enumerate(lines):
        # Pick a gradient colour per line, then per character half-step so
        # adjacent glyphs blend smoothly.
        color = _GRADIENT[min(int(i / max(n - 1, 1) * (len(_GRADIENT) - 1)), len(_GRADIENT) - 1)]
        text.append(line + "\n", style=f"bold {color}")
    return text


def print_banner(console: Console, tagline: str = _TAGLINE) -> None:
    """Render the full startup banner to ``console``."""
    # Wordmark panel: double border, gradient art.
    console.print(
        Panel(
            _gradient_wordmark(),
            border_style="#7A5CFF",
            padding=(0, 1),
            expand=False,
        )
    )

    # Info rows: name/version + repo left, org right, tagline full-width
    # (own line so it never gets squeezed on narrow terminals).
    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold #00E5FF", justify="left")
    info.add_column(style="dim", justify="right")
    info.add_row(
        f"[bold #FF6650]GitSpyX[/bold #FF6650] [dim]v{__version__}[/dim]",
        "[dim]github.com/MrHacker-X · Vritra Security Organization[/dim]",
    )
    console.print(info)
    console.print(f"[bold {_GRADIENT[4]}]{tagline}[/bold {_GRADIENT[4]}]")

    # Divider: gradient-faded rule.
    rule = Text()
    colors = list(reversed(_GRADIENT))
    for i in range(66):
        rule.append("─", style=colors[min(i * len(colors) // 66, len(colors) - 1)])
    console.print(rule)
