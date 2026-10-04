"""Materialize a worktree's `.env` in the structure of its committed example.

The example owns the STRUCTURE and the operator owns the VALUES. Every line of
a provisioned `.env` - the banners, the prose under each variable, the order -
is the example's, and the only thing that differs is which assignments are
live and what they hold. That split is what keeps a `.env` readable for as
long as the checkout lives: a variable the example gains appears in the local
file on the next run, documented, instead of the two drifting apart from the
day the file was copied.

Where the values come from depends on whether the file exists:

- An absent `.env` is seeded from the `.env` of the worktree checked out on
  the default branch. A new worktree is a second view of a project the
  operator has already configured once; starting it on defaults leaves its
  credential-scoped commands silently under-configured. Only the names the
  example declares are taken: a name it does not declare is one nothing in
  this repository reads, and copying it would spread a setting that
  configures nothing into every new worktree.
- A present `.env` keeps its own values and is only restructured. Nothing is
  pulled over it, so a value deliberately changed or removed in one worktree
  stays that way.

No value an operator's own file holds is ever dropped. An assignment the
example does not declare stays in that file, in a trailing block, rather than
being deleted on the operator's behalf, and a file holding a line
this module cannot read as a comment or an assignment is refused and left
byte-for-byte alone, because rewriting around a line it does not understand is
how a multi-line secret gets truncated. A rewrite goes through a sibling
temporary file and one rename, so an interrupted run leaves the old file.

It is a preflight rather than a step of ``init-tools`` because the file is a
precondition for other recipes, not a product of initialization. Invoked as a
subprocess so it is an ordinary declared step in :mod:`dev.init.plan`, visible
in the report like any other, rather than a special case hidden inside the
runner.

Stdlib-only, by the constraint stated in :mod:`dev.init`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The branch whose worktree seeds a new one.
DEFAULT_BRANCH: Final = "main"

#: An assignment the example offers: live, or commented out with its default.
#: The name is anchored against the ``=`` so a longer variable that merely
#: starts with a shorter one's name cannot stand in for it, and a prose
#: comment that mentions a variable is not mistaken for its declaration.
TEMPLATE_ASSIGNMENT: Final = re.compile(r"^\s*#?\s*([A-Z_][A-Z0-9_]*)=(.*)$")

#: An assignment that is in force in an operator's file.
_LIVE_ASSIGNMENT: Final = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

_UNDECLARED_BANNER: Final = (
    "# ---------------------------------------------------------------------------",
    "# Not declared in .env.example",
    "# ---------------------------------------------------------------------------",
    "# Kept so that no value is lost. Nothing in this repository reads these",
    "# names, and they are not copied into new worktrees. Delete them.",
)


class UnreadableLineError(ValueError):
    """A line of an operator's file is neither a comment nor an assignment."""

    def __init__(self, path: Path, number: int) -> None:
        self.path = path
        self.number = number
        # The line itself is withheld: it may be the tail of a credential.
        super().__init__(
            f"{path}:{number} is neither a comment nor a NAME=value assignment"
        )


@dataclass(frozen=True)
class Rendering:
    """A `.env` rendered from the example.

    Attributes:
        text: The file content.
        placed: The names whose values went onto the example's own lines.
        undeclared: The names carried into the trailing block.
    """

    text: str
    placed: tuple[str, ...]
    undeclared: tuple[str, ...]


def read_values(path: Path) -> dict[str, str]:
    """Return the assignments in force in an operator's file.

    Args:
        path: The file to read.

    Returns:
        Each live name mapped to the text after its ``=``, verbatim. A name
        assigned twice keeps its last value, which is the one a loader reads.

    Raises:
        UnreadableLineError: When a line is neither blank, a comment, nor an
            assignment.
    """
    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LIVE_ASSIGNMENT.match(line)
        if match is None:
            raise UnreadableLineError(path, number)
        values[match.group(1)] = match.group(2)
    return values


def render(example_text: str, values: dict[str, str]) -> Rendering:
    """Lay *values* out in the structure of the example.

    Args:
        example_text: The content of the example file.
        values: The assignments to make live.

    Returns:
        The rendered file, and which names landed where.
    """
    pending = dict(values)
    placed: list[str] = []
    lines: list[str] = []
    for line in example_text.splitlines():
        match = TEMPLATE_ASSIGNMENT.match(line)
        if match is not None and match.group(1) in pending:
            name = match.group(1)
            lines.append(f"{name}={pending.pop(name)}")
            placed.append(name)
        else:
            lines.append(line)
    if pending:
        lines.extend(("", *_UNDECLARED_BANNER))
        lines.extend(f"{name}={value}" for name, value in pending.items())
    return Rendering(
        text="\n".join(lines) + "\n",
        placed=tuple(placed),
        undeclared=tuple(pending),
    )


def seed_source(worktree: Path, env_name: str) -> Path | None:
    """Return the default-branch worktree's environment file, if there is one.

    Args:
        worktree: The worktree being provisioned.
        env_name: The filename to look for beside that worktree's root.

    Returns:
        The file, or ``None`` when git is unavailable, no worktree has the
        default branch checked out, that worktree is this one, or it holds no
        such file. Every one of those means "nothing to seed from", which
        provisions on the example's defaults rather than failing.
    """
    try:
        listing = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return None
    if listing.returncode != 0:
        return None
    root = ""
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            root = line.removeprefix("worktree ")
        elif line == f"branch refs/heads/{DEFAULT_BRANCH}" and root:
            candidate = Path(root) / env_name
            if candidate.resolve() == (worktree / env_name).resolve():
                return None
            return candidate if candidate.is_file() else None
    return None


def _replace(target: Path, text: str) -> None:
    """Write *text* to *target* through a sibling file and one rename."""
    scratch = target.with_name(f"{target.name}.provisioning")
    scratch.write_text(text, encoding="utf-8", newline="\n")
    os.replace(scratch, target)


def provision(example: Path, target: Path, seed: Path | None = None) -> int:
    """Bring ``target`` into the example's structure, keeping every value.

    Args:
        example: The committed example file.
        target: The operator's local file.
        seed: The file a new ``target`` takes its declared values from, or
            ``None`` to start one on the example's defaults. Ignored when
            ``target`` exists.

    Returns:
        0 when the target is in the example's structure on return, 1 when the
        example is missing or a file whose values were needed could not be
        read. Nothing is written on a non-zero return.
    """
    if not example.is_file():
        print(
            f"{example} not found - cannot provision {target}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    existing = target.exists()
    source = target if existing else seed
    try:
        values = read_values(source) if source is not None else {}
    except UnreadableLineError as exc:
        print(
            f"{exc} - leaving {target.name} untouched. Put the value on one "
            "line, or remove the line, then run this again.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    template = example.read_text(encoding="utf-8")
    skipped: list[str] = []
    if not existing:
        declared = {
            match.group(1)
            for line in template.splitlines()
            if (match := TEMPLATE_ASSIGNMENT.match(line)) is not None
        }
        skipped = sorted(set(values) - declared)
        values = {name: value for name, value in values.items() if name in declared}
    rendering = render(template, values)
    if existing and target.read_bytes() == rendering.text.encode("utf-8"):
        print(f"{target.name} already matches {example.name}.", flush=True)
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    _replace(target, rendering.text)

    kept = len(rendering.placed) + len(rendering.undeclared)
    if existing:
        outcome = f"Restructured {target.name} to match {example.name}; {kept} kept"
    elif seed is not None:
        outcome = f"Created {target.name} from {example.name}; {kept} taken from {seed}"
    else:
        outcome = f"Created {target.name} from {example.name} on its defaults"
    print(f"{outcome}.", flush=True)
    unread = [*rendering.undeclared, *skipped]
    if unread:
        action = "kept, but nothing reads" if existing else "not copied"
        print(
            f"  {example.name} does not declare, so {action}: {', '.join(unread)}",
            flush=True,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Provision one environment file.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        The exit code of the provisioning.
    """
    parser = argparse.ArgumentParser(
        prog="python -m dev.init.dotenv",
        description=(
            "Write a local environment file in the structure of its committed "
            "example, keeping its values or seeding a new one from the "
            f"{DEFAULT_BRANCH} worktree."
        ),
    )
    parser.add_argument("example", type=Path, help="the committed example file")
    parser.add_argument("target", type=Path, help="the local file to provision")
    args = parser.parse_args(argv)
    target: Path = args.target
    seed = seed_source(target.resolve().parent, target.name)
    return provision(args.example, target, seed)


if __name__ == "__main__":
    sys.exit(main())
