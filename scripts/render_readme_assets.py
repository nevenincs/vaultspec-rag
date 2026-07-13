#!/usr/bin/env python
"""Regenerate the README terminal renders under ``assets/``.

Runs real ``vaultspec-rag`` commands against this repository's own live
index and exports each capture as a rich terminal-window SVG themed on
the vaultspec brand palette, light variant (the same visual system as
the vaultspec-core README). Output is genuine command output; rendering
only trims length (a dim ellipsis marks truncation) and applies the
brand terminal theme.

Usage::

    uv run --no-sync python scripts/render_readme_assets.py [OUT_DIR]

``OUT_DIR`` defaults to ``assets``. Requires the managed search server
to be running (``vaultspec-rag server start``) and the index to be
current.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

# Palette derived from the vaultspec logo, light variant: warm charcoal
# foreground on cream paper, with the sage / teal / sand / dusty-rose /
# lavender accents darkened to keep contrast on the light ground.
VAULTSPEC_THEME = TerminalTheme(
    background=(250, 247, 242),
    foreground=(30, 27, 24),
    normal=[
        (30, 27, 24),
        (166, 92, 92),
        (106, 122, 77),
        (163, 122, 58),
        (86, 108, 158),
        (124, 106, 156),
        (74, 124, 116),
        (94, 86, 78),
    ],
    bright=[
        (145, 137, 129),
        (146, 72, 72),
        (88, 104, 60),
        (140, 102, 42),
        (66, 88, 140),
        (104, 86, 138),
        (56, 106, 98),
        (30, 27, 24),
    ],
)

WIDTH = 100

# Rich hardcodes a white window border, invisible around a light terminal
# on a light page; render_svg swaps it for a soft warm-charcoal line. The
# literal lives inside rich's export_svg, so a rich upgrade can change it.
RICH_STROKE = 'stroke="rgba(255,255,255,0.35)"'
LIGHT_STROKE = 'stroke="rgba(30,27,24,0.22)"'


def run_rag(args: list[str]) -> str:
    env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    env["FORCE_COLOR"] = "1"
    env["COLUMNS"] = str(WIDTH)
    proc = subprocess.run(
        ["uv", "run", "--no-sync", "vaultspec-rag", *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=env,
    )
    if proc.returncode != 0:
        print(
            f"warning: exit {proc.returncode} for {args}\n{proc.stderr}",
            file=sys.stderr,
        )
    return proc.stdout


def render_svg(
    text: str, out_path: str, title: str, max_lines: int | None = None
) -> None:
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    truncated = max_lines is not None and len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        while lines and not lines[-1].strip():
            lines.pop()
    out = Console(
        record=True,
        width=WIDTH,
        force_terminal=True,
        legacy_windows=False,
        highlight=False,
        soft_wrap=True,
        file=io.StringIO(),
    )
    for line in lines:
        out.print(Text.from_ansi(line), no_wrap=True, overflow="ellipsis")
    if truncated:
        out.print(Text("  …", style="bright_black"))
    svg = out.export_svg(title=title, theme=VAULTSPEC_THEME)
    if RICH_STROKE not in svg:
        raise RuntimeError(
            "rich's window-border stroke literal changed; update RICH_STROKE"
        )
    svg = svg.replace(RICH_STROKE, LIGHT_STROKE)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"wrote {out_path} ({len(lines)} lines)")


VAULT_QUERY = "store-layer locking reentrant lock per collection local mode"
CODE_QUERY = "gpu section wrapping the reranker predict forward pass"


def main() -> None:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "assets"

    render_svg(
        run_rag(["search", VAULT_QUERY, "--type", "vault", "--limit", "2"]),
        f"{outdir}/term-search-vault.svg",
        f'vaultspec-rag search "{VAULT_QUERY}" --type vault',
        max_lines=22,
    )
    render_svg(
        run_rag(
            [
                "search",
                CODE_QUERY,
                "--type",
                "code",
                "--language",
                "python",
                "--scores",
                "--limit",
                "2",
            ]
        ),
        f"{outdir}/term-search-code.svg",
        f'vaultspec-rag search "{CODE_QUERY}" --type code --scores',
        max_lines=20,
    )
    render_svg(
        run_rag(["server", "doctor"]),
        f"{outdir}/term-doctor.svg",
        "vaultspec-rag server doctor",
        max_lines=16,
    )


if __name__ == "__main__":
    main()
