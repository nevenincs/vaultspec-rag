#!/usr/bin/env python
"""Regenerate the README terminal renders under ``assets/``.

Runs real ``vaultspec-rag`` commands against this repository's own live
index and exports each capture as a rich terminal-window SVG themed on
the vaultspec brand palette (the same visual system as the
vaultspec-core README). Output is genuine command output; rendering only
trims length (a dim ellipsis marks truncation).

Usage::

    uv run --no-sync python scripts/render_readme_assets.py [OUT_DIR]

``OUT_DIR`` defaults to ``assets``. Requires the managed search server
to be running (``vaultspec-rag server start``) and the index to be
current.
"""

from __future__ import annotations

import io
import subprocess
import sys

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

# Palette derived from the vaultspec logo: cream foreground on warm
# charcoal, with sage / teal / sand / dusty-rose / lavender accents.
VAULTSPEC_THEME = TerminalTheme(
    background=(30, 27, 24),
    foreground=(242, 236, 228),
    normal=[
        (30, 27, 24),
        (201, 138, 138),
        (163, 177, 138),
        (217, 185, 138),
        (138, 159, 201),
        (181, 168, 201),
        (143, 188, 181),
        (242, 236, 228),
    ],
    bright=[
        (110, 102, 94),
        (222, 160, 160),
        (185, 199, 160),
        (233, 205, 160),
        (160, 181, 222),
        (203, 190, 222),
        (165, 210, 203),
        (250, 247, 242),
    ],
)

WIDTH = 100


def run_rag(args: list[str]) -> str:
    proc = subprocess.run(
        ["uv", "run", "--no-sync", "vaultspec-rag", *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
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
        file=io.StringIO(),
    )
    for line in lines:
        out.print(Text(line), no_wrap=True, overflow="ellipsis")
    if truncated:
        out.print(Text("  …", style="bright_black"))
    svg = out.export_svg(title=title, theme=VAULTSPEC_THEME)
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
