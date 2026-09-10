"""Guard three drift-prone shapes across the user-facing manuals.

Three separate defects were filed against ``docs/`` in the same batch, and each
asked for a documentation assertion so the defect could not silently return.
They share one mechanism because all three are the same failure mode at
different granularities: a page states one thing in prose and shows another in
its examples.

1. Invocation-lane drift. A manual mixes bare ``vaultspec-rag ...``,
   project-local ``uv run vaultspec-rag ...``, and ``uvx`` examples without
   declaring which lane its examples assume. This scans every fenced code
   block in the pages listed in :data:`MANUAL_PAGES` for the lane each
   ``vaultspec-rag`` invocation uses, fails when a page's examples mix more
   than one lane, and separately fails when a page invoking the CLI at all
   does not declare its assumed lane and point to the installation guide for
   the others.

2. A version-mismatch example whose narrative and captured version numbers
   disagree. ``docs/service-mode.md`` shows a captured error where an older
   daemon is still running after the client upgraded; the check parses the
   two captured version literals and fails unless the client reads newer than
   the service, which is the only ordering the surrounding remedy supports.

3. Platform-specific command spellings going missing from PATH
   troubleshooting. ``which`` alone strands PowerShell (no ``which``) and
   Command Prompt (``where`` resolves to ``Where-Object`` first). This checks
   that a POSIX form, ``Get-Command``, and ``where.exe`` are all present.

A fourth, general shape rides along because it is the same "prose disagrees
with example" failure: a fenced code block that is nothing but an environment
variable assignment, offered as if it were a runnable command, without any
nearby prose calling it out as an environment variable.

Usage:
    uv run python tools/check_docs_conventions.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

#: The manuals issue #478 named, plus the page that already gets the pattern
#: right - keeping it in scope is what proves the check does not just fail on
#: the broken pages, it also has to stay quiet on the reference page.
MANUAL_PAGES: tuple[str, ...] = (
    "verification.md",
    "configuration.md",
    "automation.md",
    "mcp.md",
    "service-mode.md",
    "backends.md",
    "storage-maintenance.md",
    "getting-started.md",
    "search-and-index.md",
    "preprocessing-hooks.md",
    "query-craft.md",
)

#: ``installation.md`` is the one page that legitimately documents every lane
#: side by side - it is the target the others link to for lane selection, not
#: another manual that must pick one.
#:
#: Captures the fence's language tag separately from its body: a ``text``
#: fence is a captured terminal render of what the *program* printed (a
#: status report's "Next action:" line, for example), not an instruction for
#: the reader to type, and a line inside one is not an invocation-lane
#: example even when it happens to spell a ``vaultspec-rag`` command.
FENCE_RE = re.compile(r"```([a-zA-Z]*)\n(.*?)```", re.DOTALL)

#: Fence languages whose content is captured output, not typed commands.
OUTPUT_FENCE_LANGUAGES = frozenset({"text"})

#: Matches a leading run of ``VAR=value`` environment assignments so a line
#: like ``VAULTSPEC_RAG_PORT=9100 vaultspec-rag server start`` still
#: classifies by the command that follows.
ENV_PREFIX_RE = re.compile(r"^(?:[A-Z][A-Z0-9_]*=\S+\s+)+")

#: Ordered so ``uv run`` is tried before the bare form; a bare-form match on
#: the whole line after :data:`ENV_PREFIX_RE` strips any leading assignment
#: could never accidentally match a ``uv run`` or ``uvx`` line, but keeping
#: the more specific patterns first is the cheaper invariant to keep true.
LANE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("uvx", re.compile(r"^uvx\s+.*\bvaultspec-rag\b")),
    ("uv-run", re.compile(r"^uv run(?:\s+--no-sync)?\s+vaultspec-rag\b")),
    ("bare", re.compile(r"^vaultspec-rag\b")),
)

#: The three prose fragments a page must carry, together, to have declared its
#: assumed invocation lane and pointed elsewhere for the others. Every callout
#: this change adds - and the pre-existing one in query-craft.md - carries all
#: three; a page missing any one of them has not actually stated the
#: convention, whatever else it says about installation.
LANE_DECLARATION_MARKERS: tuple[str, ...] = (
    "uv run",
    "standalone tool",
    "installation guide](installation.md",
)

#: A fenced-code line that is only an environment-variable assignment - no
#: command follows it on the same line.
ENV_ONLY_LINE_RE = re.compile(r"^(?:export\s+)?[A-Z][A-Z0-9_]*=\S+$")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _normalize_prose(text: str) -> str:
    """Collapse whitespace so a marker phrase survives markdown line-wrapping.

    A prose marker checked against raw text breaks the moment an editor
    reflows the paragraph it lives in - a wrap lands mid-phrase and the
    literal substring is gone even though the sentence still said exactly
    what it said before. Strips each line's leading blockquote marker first,
    because ``>`` is not whitespace and survives a naive collapse as a
    literal character sitting between the two wrapped halves of the phrase.
    Markers that must survive a hard-wrapped paragraph are checked against
    this normalized form instead of the raw text.
    """
    unquoted = re.sub(r"(?m)^>+[ \t]*", "", text)
    return re.sub(r"\s+", " ", unquoted)


def classify_lane(line: str) -> str | None:
    """Return which invocation lane *line* uses, or ``None`` if it is not one."""
    stripped = ENV_PREFIX_RE.sub("", line.strip())
    for lane, pattern in LANE_PATTERNS:
        if pattern.match(stripped):
            return lane
    return None


def scan_lane_usage(text: str) -> list[tuple[int, str, str]]:
    """Return ``(line, lane, line_text)`` for every CLI invocation in fenced code."""
    findings: list[tuple[int, str, str]] = []
    for block in FENCE_RE.finditer(text):
        if block.group(1) in OUTPUT_FENCE_LANGUAGES:
            continue
        body = block.group(2)
        body_start = block.start(2)
        for line_match in re.finditer(r"^[ \t]*(\S.*)$", body, re.MULTILINE):
            lane = classify_lane(line_match.group(1))
            if lane is not None:
                offset = body_start + line_match.start(1)
                findings.append(
                    (_line_number(text, offset), lane, line_match.group(1).strip())
                )
    return findings


def check_lane_mixing(path: Path, text: str) -> list[str]:
    findings = scan_lane_usage(text)
    lanes_used = {lane for _line, lane, _src in findings}
    if len(lanes_used) <= 1:
        return []
    rel = path.relative_to(REPO_ROOT).as_posix()
    detail = ", ".join(
        f"{lane} at line {line} ({src!r})" for line, lane, src in findings
    )
    return [f"{rel}: mixes invocation lanes without declaring one - {detail}"]


def check_lane_declaration(path: Path, text: str) -> list[str]:
    findings = scan_lane_usage(text)
    if not findings:
        return []
    normalized = _normalize_prose(text)
    missing = [
        marker for marker in LANE_DECLARATION_MARKERS if marker not in normalized
    ]
    if not missing:
        return []
    rel = path.relative_to(REPO_ROOT).as_posix()
    return [
        f"{rel}: invokes vaultspec-rag but does not declare its invocation lane "
        f"(missing: {', '.join(missing)})"
    ]


def check_env_only_examples(path: Path, text: str) -> list[str]:
    problems: list[str] = []
    rel = path.relative_to(REPO_ROOT).as_posix()
    for block in FENCE_RE.finditer(text):
        if block.group(1) in OUTPUT_FENCE_LANGUAGES:
            continue
        body = block.group(2)
        body_start = block.start(2)
        lines = body.splitlines()
        if len(lines) != 1 or not ENV_ONLY_LINE_RE.match(lines[0].strip()):
            continue
        window_start = max(0, block.start() - 400)
        context = text[window_start : block.start()]
        if "environment variable" not in context.lower():
            offset = body_start
            problems.append(
                f"{rel}:{_line_number(text, offset)}: environment-variable-only "
                f"example ({lines[0].strip()!r}) is not called out as an "
                "environment variable in the surrounding prose"
            )
    return problems


#: The captured mismatch narrative only supports one ordering: an upgraded
#: client refusing to talk to an older daemon still running the previous
#: release.
VERSION_MISMATCH_RE = re.compile(
    r"client is (\d+\.\d+\.\d+) but the running service is (\d+\.\d+\.\d+)"
)
MATCHING_RELEASE_RE = re.compile(r"release: (\d+\.\d+\.\d+) \(matches this client\)")


def _version_tuple(literal: str) -> tuple[int, ...]:
    return tuple(int(part) for part in literal.split("."))


def check_version_mismatch_example(path: Path, text: str) -> list[str]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    match = VERSION_MISMATCH_RE.search(text)
    if match is None:
        return [
            f"{rel}: expected a client/service version-mismatch example, found none"
        ]
    client_literal, service_literal = match.group(1), match.group(2)
    problems: list[str] = []
    if _version_tuple(client_literal) <= _version_tuple(service_literal):
        problems.append(
            f"{rel}: version-mismatch example has client {client_literal} <= "
            f"service {service_literal}; the remedy below it (restart an older "
            "daemon) requires a newer client"
        )
    healthy = MATCHING_RELEASE_RE.search(text)
    if healthy is not None and healthy.group(1) != service_literal:
        problems.append(
            f"{rel}: the healthy example reports release {healthy.group(1)!r} "
            f"(matches this client) but the mismatch example's older service "
            f"reads {service_literal!r}; the page is not internally consistent"
        )
    return problems


#: The PATH-lookup spellings a reader on each platform needs; ``which`` alone
#: strands PowerShell (no ``which``) and Command Prompt (``where`` resolves to
#: ``Where-Object`` first in a PowerShell-first search).
POSIX_PATH_RE = re.compile(r"\b(?:command -v|which) vaultspec-search-mcp\b")
POWERSHELL_PATH_MARKER = "Get-Command vaultspec-search-mcp"
CMD_PATH_MARKER = "where.exe vaultspec-search-mcp"

#: The read-only persistence caveat must stay legible as conditional on an
#: affected Core release, with the tracking issue and its fix linked, rather
#: than reading as a permanent limitation.
CORE_ISSUE_MARKER = "vaultspec-core#404"
CORE_FIX_MARKER = "vaultspec-core#428"
CORE_SCOPE_MARKER = "no longer applies"


def check_mcp_path_and_version_scope(path: Path, text: str) -> list[str]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    normalized = _normalize_prose(text)
    problems: list[str] = []
    if POSIX_PATH_RE.search(text) is None:
        problems.append(f"{rel}: missing a POSIX PATH check (`command -v`/`which`)")
    if POWERSHELL_PATH_MARKER not in text:
        problems.append(
            f"{rel}: missing the PowerShell PATH check (`{POWERSHELL_PATH_MARKER}`)"
        )
    if CMD_PATH_MARKER not in text:
        problems.append(
            f"{rel}: missing the Command Prompt PATH check (`{CMD_PATH_MARKER}`)"
        )
    if CORE_ISSUE_MARKER not in normalized or CORE_FIX_MARKER not in normalized:
        problems.append(
            f"{rel}: the read-only persistence caveat must cite both "
            f"{CORE_ISSUE_MARKER} and its fix {CORE_FIX_MARKER}"
        )
    if CORE_SCOPE_MARKER not in normalized:
        problems.append(
            f"{rel}: the read-only persistence caveat must state the condition "
            f"under which it stops applying (expected {CORE_SCOPE_MARKER!r})"
        )
    return problems


def main() -> int:
    problems: list[str] = []

    for name in MANUAL_PAGES:
        path = DOCS_DIR / name
        text = path.read_text(encoding="utf-8")
        problems.extend(check_lane_mixing(path, text))
        problems.extend(check_lane_declaration(path, text))

    for path in sorted(DOCS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        problems.extend(check_env_only_examples(path, text))

    service_mode = DOCS_DIR / "service-mode.md"
    problems.extend(
        check_version_mismatch_example(
            service_mode, service_mode.read_text(encoding="utf-8")
        )
    )

    mcp = DOCS_DIR / "mcp.md"
    problems.extend(
        check_mcp_path_and_version_scope(mcp, mcp.read_text(encoding="utf-8"))
    )

    if problems:
        print("[docs-conventions] found issues:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print(
        "[docs-conventions] invocation lanes, version examples, and PATH "
        "checks are consistent"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
