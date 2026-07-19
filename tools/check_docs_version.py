"""Guard against stale ``vaultspec-rag v0.x.y`` version strings in docs.

``docs/getting-started.md`` and ``docs/installation.md`` show literal
``vaultspec-rag --version`` output as part of their walkthrough. Those
literals drift silently whenever a release bumps ``pyproject.toml`` without
a matching docs edit. This scans ``README.md`` and ``docs/`` for the
``vaultspec-rag v0.x.y`` output-literal pattern and fails on any value that
does not match the current package version.

CHANGELOG.md and RELEASING.md use a different, deliberately excluded
literal shape (``vaultspec-rag-v0.x.y``, hyphenated) for historical compare
links and an illustrative example, so they are not scanned.

Usage:
    uv run python tools/check_docs_version.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_PATHS = [REPO_ROOT / "README.md", REPO_ROOT / "docs"]
VERSION_LITERAL = re.compile(r"vaultspec-rag v(0\.\d+\.\d+)")


def current_version() -> str:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return str(pyproject["project"]["version"])


def iter_markdown_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    return files


def main() -> int:
    version = current_version()
    stale: list[tuple[Path, int, str]] = []
    for path in iter_markdown_files(SCAN_PATHS):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in VERSION_LITERAL.finditer(line):
                if match.group(1) != version:
                    stale.append((path, lineno, match.group(0)))

    if stale:
        print(
            f"[docs-version] pyproject.toml declares v{version}; found stale literals:"
        )
        for path, lineno, literal in stale:
            rel = path.relative_to(REPO_ROOT).as_posix()
            print(f"  {rel}:{lineno}: {literal}")
        return 1

    print(
        f"[docs-version] all `vaultspec-rag v{version}` literals match pyproject.toml"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
