#!/usr/bin/env python
"""Regenerate the README terminal renders under ``assets/``.

Runs real ``vaultspec-rag`` commands against this repository's own live
index and exports each capture as a terminal SVG in the vaultspec
documentation frame, the same frame the vaultspec-core README uses. Output
is genuine command output, colours included: rendering only trims length
(a dim ellipsis marks truncation) and draws the frame.

Usage::

    uv run --no-sync python scripts/render_readme_assets.py [OUT_DIR]

``OUT_DIR`` defaults to ``assets``. Requires the managed search server
to be running (``vaultspec-rag server start``) and the index to be
current.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from html import escape
from string import Template

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

# The brand's documentation terminal, dark in both page themes so one render
# serves both: grey-green ink on the dark mat, the brand green for success,
# ochre for warnings, and chalk blue for commands.
VAULTSPEC_THEME = TerminalTheme(
    background=(20, 24, 22),
    foreground=(216, 223, 218),
    normal=[
        (15, 18, 17),
        (229, 122, 134),
        (111, 190, 139),
        (220, 160, 90),
        (132, 182, 214),
        (180, 166, 212),
        (114, 194, 196),
        (216, 223, 218),
    ],
    bright=[
        (141, 153, 145),
        (240, 154, 163),
        (138, 207, 162),
        (232, 183, 117),
        (163, 201, 227),
        (201, 189, 227),
        (147, 211, 211),
        (241, 244, 241),
    ],
)

WIDTH = 112
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# The working directory the title bar names. A capture otherwise embeds the
# session that produced it, drive and account included.
CAPTURE_CWD = "~/code/vaultspec-rag"

TERM_BAR = "#1e2321"
TERM_FAINT = "#8d9991"
TERM_RULE = "#3c4541"
FONT_STACK = (
    "'IBM Plex Mono', 'Cascadia Mono', 'Cascadia Code', ui-monospace, Menlo, "
    "Consolas, 'DejaVu Sans Mono', monospace"
)

# Frame geometry in SVG units. Rich fixes a 20-unit character height and a
# 1.22 line pitch; the aspect ratio is passed to it so both sides share it.
FONT_ASPECT = 0.61
CHAR_WIDTH = 20 * FONT_ASPECT
LINE_HEIGHT = 20 * 1.22
PAD_X = 28
BAR_HEIGHT = 50
PAD_TOP = 26
PAD_BOTTOM = 30
RADIUS = 14

# Replaces rich's default template, whose chrome draws a macOS window with
# three traffic-light buttons. `$` fields are filled here; `{}` fields are
# rich's own, filled by export_svg.
SVG_FRAME = Template("""\
<svg class="rich-terminal" viewBox="0 0 $width $height" xmlns="http://www.w3.org/2000/svg">
    <style>
    .{unique_id}-matrix {{
        font-family: $font;
        font-size: {char_height}px;
        line-height: {line_height}px;
        font-variant-east-asian: full-width;
    }}
    .{unique_id}-bar {{
        font-family: $font;
        font-size: 17px;
        fill: $faint;
    }}
    {styles}
    </style>
    <defs>
    <clipPath id="{unique_id}-clip-frame">
      <rect x="0" y="0" width="$width" height="$height" rx="$radius"/>
    </clipPath>
    <clipPath id="{unique_id}-clip-terminal">
      <rect x="0" y="0" width="{terminal_width}" height="{terminal_height}"/>
    </clipPath>
    {lines}
    </defs>
    <g clip-path="url(#{unique_id}-clip-frame)">
    <rect width="$width" height="$height" fill="$background"/>
    <rect width="$width" height="$bar_height" fill="$bar"/>
    </g>
    <rect x="0.5" y="0.5" width="$outline_width" height="$outline_height"
        rx="$radius" fill="none" stroke="$rule"/>
    <text class="{unique_id}-bar" x="$pad_x" y="$bar_text_y">$left</text>
    <text class="{unique_id}-bar" x="$right_x" y="$bar_text_y"
        text-anchor="end">$right</text>
    <g transform="translate($pad_x, $body_y)"
        clip-path="url(#{unique_id}-clip-terminal)">
    {backgrounds}
    <g class="{unique_id}-matrix">
    {matrix}
    </g>
    </g>
</svg>
""")


def run_rag(args: list[str]) -> str:
    """Run one real command and return its coloured output."""
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
    ansi: str,
    out_path: str,
    title: str,
    max_lines: int | None = None,
) -> None:
    """Export captured ANSI text as a terminal SVG in the documentation frame.

    The title bar names the working directory on the left and the command,
    *title*, on the right.
    """
    lines = ansi.splitlines()
    while lines and not ANSI_RE.sub("", lines[-1]).strip():
        lines.pop()
    truncated = max_lines is not None and len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        while lines and not ANSI_RE.sub("", lines[-1]).strip():
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
    rows = len(lines) + int(truncated)
    svg = out.export_svg(
        title=title,
        theme=VAULTSPEC_THEME,
        font_aspect_ratio=FONT_ASPECT,
        code_format=svg_frame(rows, WIDTH, left=CAPTURE_CWD, right=title),
    )
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    print(f"wrote {out_path} ({len(lines)} lines)")


def svg_frame(rows: int, columns: int, *, left: str, right: str) -> str:
    """Return the rich ``code_format`` for a *rows* by *columns* terminal."""
    width = PAD_X * 2 + CHAR_WIDTH * columns
    height = BAR_HEIGHT + PAD_TOP + LINE_HEIGHT * rows + PAD_BOTTOM

    def bar_text(text: str) -> str:
        # Rich formats the result with str.format, so literal braces double.
        return escape(text).replace("{", "{{").replace("}", "}}")

    return SVG_FRAME.substitute(
        width=f"{width:g}",
        height=f"{height:g}",
        outline_width=f"{width - 1:g}",
        outline_height=f"{height - 1:g}",
        radius=RADIUS,
        font=FONT_STACK,
        faint=TERM_FAINT,
        background=VAULTSPEC_THEME.background_color.hex,
        bar=TERM_BAR,
        bar_height=BAR_HEIGHT,
        rule=TERM_RULE,
        pad_x=PAD_X,
        right_x=f"{width - PAD_X:g}",
        bar_text_y=BAR_HEIGHT // 2 + 6,
        body_y=BAR_HEIGHT + PAD_TOP,
        left=bar_text(left),
        right=bar_text(right),
    )


VAULT_QUERY = "why one GPU consumer thread instead of CUDA streams"
CODE_QUERY = "pick CUDA before Apple MPS and never fall back to the CPU"


def main() -> None:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "assets"

    vault_args = ["--type", "vault", "--doc-type", "adr", "--max-results", "2"]
    render_svg(
        run_rag(["search", VAULT_QUERY, *vault_args]),
        f"{outdir}/term-search-vault.svg",
        f'vaultspec-rag search "{VAULT_QUERY}" {" ".join(vault_args)}',
        max_lines=17,
    )
    code_args = ["--type", "code", "--max-results", "1"]
    render_svg(
        run_rag(["search", CODE_QUERY, *code_args]),
        f"{outdir}/term-search-code.svg",
        f'vaultspec-rag search "{CODE_QUERY}" {" ".join(code_args)}',
        max_lines=25,
    )
    render_svg(
        run_rag(["server", "doctor"]),
        f"{outdir}/term-doctor.svg",
        "vaultspec-rag server doctor",
        max_lines=13,
    )


if __name__ == "__main__":
    main()
