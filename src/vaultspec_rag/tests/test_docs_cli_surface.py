"""Guards that the shipped docs cannot name a CLI surface that does not exist.

A command either exists or it does not, and a flag either belongs to a command
or it does not. That makes documented CLI usage machine-checkable, so it should
not depend on someone reading a page carefully. This module walks every
``vaultspec-rag`` invocation in ``docs/`` and ``README.md``, resolves it against
the live Typer application, and fails on anything the application would reject.

It is the CLI counterpart to :mod:`test_configuration_doc`, which guards the
configuration reference against the settings object.

Two failure modes are covered:

* a documented command path the application does not define, and
* a documented option the resolved command does not accept.

The reverse direction is asserted at command granularity: every command the
application defines must be named somewhere in the docs. Flags are exempt from
that, because prose is allowed to be selective about which options it teaches.
A whole command going unmentioned is a gap; an unmentioned flag is an editorial
choice.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import typer.main
from typer.core import TyperOption

if TYPE_CHECKING:
    # Typer vendors its own copy of Click, so the command tree this module
    # walks is built from ``typer._click``, not the top-level ``click``. Naming
    # the vendored class is what keeps the annotations true to what
    # ``typer.main.get_command`` actually returns.
    from typer._click.core import Command

from dev.generate_cli_reference import OUTPUT, render

from ..cli._app import app

pytestmark = [pytest.mark.unit]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOCS = PROJECT_ROOT / "docs"
_README = PROJECT_ROOT / "README.md"

#: Invocation prefixes that may precede the executable in a documented command.
#: ``uv run --no-sync vaultspec-rag ...`` and ``uvx --from x vaultspec-rag ...``
#: both address the same application.
_EXECUTABLE = "vaultspec-rag"

#: Tokens that end the command path: everything after one is an argument value,
#: a placeholder, or shell noise rather than a subcommand name.
_ARG_START = re.compile(r"""^(["'<{$-]|\.|/|~|[A-Za-z]:\\)""")

#: Options the root application accepts on any subcommand invocation.
_ALWAYS_ALLOWED = {"--help"}

#: A version literal. ``vaultspec-rag v0.4.21`` in a fenced block is the output
#: of ``--version``, not a command, and the two are indistinguishable by shape
#: alone.
_VERSION_LITERAL = re.compile(r"^v?\d+\.\d+")

pytestmark.append(
    pytest.mark.skipif(
        not _DOCS.is_dir(),
        reason="docs are not shipped in the installed package",
    )
)


def test_cli_reference_is_generated_from_live_surface() -> None:
    """The committed standalone reference matches the live command tree."""
    assert OUTPUT.read_text(encoding="utf-8") == render()


def _command_tree() -> Command:
    """Return the root Click command for the Typer application."""
    return typer.main.get_command(app)


def _resolve(root: Command, words: list[str]) -> tuple[Command | None, int]:
    """Resolve the longest command path in *words*.

    Returns the resolved command and how many words it consumed. A ``None``
    command means the first word named no subcommand of *root*.
    """
    current = root
    consumed = 0
    for word in words:
        children = _subcommands(current)
        if not children:
            break
        candidate = children.get(word)
        if candidate is None:
            if consumed == 0:
                return None, 0
            break
        current = candidate
        consumed += 1
    return current, consumed


def _subcommands(command: Command) -> dict[str, Command]:
    """Return *command*'s subcommands, empty for a leaf.

    Only a Group carries ``commands``, and the attribute is untyped where it
    exists, so both walks below read it through this one typed accessor rather
    than each repeating the lookup and inheriting an unknown element type.
    """
    return cast("dict[str, Command]", getattr(command, "commands", None) or {})


def _option_names(command: Command) -> set[str]:
    """Return every long option string the *command* accepts."""
    names: set[str] = set(_ALWAYS_ALLOWED)
    for param in command.params:
        for opt in getattr(param, "opts", []) + getattr(param, "secondary_opts", []):
            if opt.startswith("--"):
                names.add(opt)
    return names


#: Fence languages whose contents are a transcript of what the application
#: PRINTED, not usage the docs prescribe. A captured run quotes prompts,
#: error messages and remediation prose, so the executable turns up inside
#: English sentences - "This vaultspec-rag client is 0.4.21" - where the
#: following word is not a subcommand and never was. Checking those as
#: invocations asks the docs to misreport what the tool actually says.
_OUTPUT_FENCES = {"text"}


def _code_spans(text: str) -> list[str]:
    """Return fenced-block lines and inline code spans holding an invocation."""
    spans: list[str] = []
    fenced = re.findall(r"```([a-zA-Z]*)\n(.*?)```", text, re.S)
    for language, block in fenced:
        if language.lower() in _OUTPUT_FENCES:
            continue
        spans.extend(block.splitlines())
    spans.extend(re.findall(r"`([^`\n]+)`", text))
    return [s for s in spans if _EXECUTABLE in s]


#: The executable as a standalone token. A package spec such as
#: ``"vaultspec-rag[gpu]"`` names the distribution for uv or pip, not an
#: invocation of the application, so it must not be read as one.
_INVOCATION = re.compile(rf"(?:^|\s){re.escape(_EXECUTABLE)}(?=\s|$)")


def _parse_invocation_tail(tail: str) -> tuple[list[str], list[str]]:
    """Split an invocation tail into command words and long options."""
    words: list[str] = []
    options: list[str] = []
    root_options = {
        option: param
        for param in _command_tree().params
        if isinstance(param, TyperOption)
        for option in (*param.opts, *param.secondary_opts)
    }
    lexer = shlex.shlex(tail, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""  # Documented Windows paths retain their backslashes.
    tokens = iter(lexer)
    past_arguments = False
    for token in tokens:
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            options.append(option)
            root_option = root_options.get(option) if not words else None
            if root_option is not None:
                if not root_option.is_flag and "=" not in token:
                    for _ in range(root_option.nargs):
                        next(tokens, None)
                continue
            past_arguments = True
            continue
        if past_arguments or _ARG_START.match(token):
            past_arguments = True
            continue
        words.append(token)
    return words, options


@pytest.mark.parametrize(
    "tail",
    [
        "--target <project> index --rebuild --type all",
        '--target "C:\\project with spaces" index --rebuild --type all',
        '--target="C:\\project with spaces" index --rebuild --type all',
        '--target="/project with spaces" index --rebuild --type all',
        "--target=<project> index --rebuild --type all",
        "--verbose --target <project> index --rebuild --type all",
    ],
)
def test_root_options_preserve_documented_command_path(tail: str) -> None:
    words, options = _parse_invocation_tail(tail)
    root = _command_tree()
    command, consumed = _resolve(root, words)
    assert words == ["index"]
    assert command is not None
    assert consumed == 1
    assert "--target" in options
    assert "--rebuild" in options
    assert "--type" in options
    assert set(options) <= _option_names(command) | _option_names(root)


def test_root_options_do_not_hide_invalid_command_or_option() -> None:
    root = _command_tree()
    words, _ = _parse_invocation_tail("--target <project> nonexistent --rebuild")
    assert _resolve(root, words) == (None, 0)
    words, options = _parse_invocation_tail("--target <project> index --nonexistent")
    command, _ = _resolve(root, words)
    assert command is not None
    assert "--nonexistent" in options
    assert "--nonexistent" not in _option_names(command) | _option_names(root)


def _invocations(text: str) -> list[tuple[list[str], list[str]]]:
    """Return ``(command words, long options)`` for each documented invocation."""
    found: list[tuple[list[str], list[str]]] = []
    for span in _code_spans(text):
        line = span.strip().lstrip("$ ").strip()
        match = _INVOCATION.search(line)
        if match is None:
            continue
        remainder = line[match.end() :].strip()
        if _VERSION_LITERAL.match(remainder):
            continue
        # Everything before the executable belongs to uv, uvx, or a shell.
        words, options = _parse_invocation_tail(line[match.end() :])
        if words or options:
            found.append((words, options))
    return found


def _doc_files() -> list[Path]:
    files = sorted(_DOCS.glob("*.md"))
    if _README.is_file():
        files.append(_README)
    return files


def _pairs() -> list[tuple[Path, list[str], list[str]]]:
    out: list[tuple[Path, list[str], list[str]]] = []
    for path in _doc_files():
        text = path.read_text(encoding="utf-8")
        for words, options in _invocations(text):
            out.append((path, words, options))
    return out


def test_documented_commands_exist() -> None:
    """No document may name a command the application does not define."""
    root = _command_tree()
    failures: list[str] = []
    for path, words, _ in _pairs():
        if not words:
            continue
        command, consumed = _resolve(root, words)
        if command is None or consumed == 0:
            failures.append(f"{path.name}: unknown command 'vaultspec-rag {words[0]}'")
            continue
        if consumed < len(words) and _subcommands(command):
            unknown = words[consumed]
            failures.append(
                f"{path.name}: 'vaultspec-rag {' '.join(words[:consumed])}' "
                f"has no subcommand {unknown!r}"
            )
    assert not failures, "documented commands the CLI does not define:\n" + "\n".join(
        sorted(set(failures))
    )


def test_documented_options_exist() -> None:
    """No document may pass an option the resolved command does not accept."""
    root = _command_tree()
    failures: list[str] = []
    for path, words, options in _pairs():
        if not options:
            continue
        command, consumed = _resolve(root, words) if words else (root, 0)
        if command is None:
            continue  # the command test owns this failure
        accepted = _option_names(command)
        if not _subcommands(command):
            accepted |= _option_names(root)
        for option in options:
            if option not in accepted:
                shown = " ".join(words[:consumed]) if words else ""
                failures.append(
                    f"{path.name}: 'vaultspec-rag {shown}'".rstrip()
                    + f" does not accept {option}"
                )
    assert not failures, "documented options the CLI does not accept:\n" + "\n".join(
        sorted(set(failures))
    )


#: Long options belonging to other tools that the docs legitimately mention:
#: uv, uvx, scoop, brew, and git all appear in installation and packaging
#: instructions. They are named here so a bare-flag reference to one of them is
#: not read as a claim about this application's surface.
_FOREIGN_OPTIONS = frozenset(
    {
        "--from",
        "--with",
        "--python",
        "--index",
        "--reinstall",
        "--torch-backend",
        "--no-sync",
        "--locked",
        "--upgrade-package",
        "--group",
        "--dev",
        "--directory",
    }
)

#: Options of ``vaultspec-search-mcp``, the second console script this project
#: ships. The docs cover it alongside the main application, so its flags are part
#: of the documented surface even though they are not Typer commands.
_MCP_OPTIONS = frozenset({"--port", "--parent-pid", "--read-only"})

#: Flags the docs deliberately name as removed, so a reader upgrading finds out
#: what happened to them. Documenting a retired flag is correct; the checker
#: must not read it as a claim that the flag still works.
_RETIRED_OPTIONS = frozenset({"--raw"})


def _bare_flags(text: str) -> set[str]:
    """Return long options written as a standalone inline code span.

    Reference tables list a flag on its own, with no invocation on the line, so
    the invocation walker never sees them. That is exactly where a fabricated
    flag name hides.
    """
    found: set[str] = set()
    for span in re.findall(r"`(--[A-Za-z0-9][A-Za-z0-9-]*)`", text):
        found.add(span)
    return found


def _every_option() -> set[str]:
    """Every long option the application accepts on any command."""
    names: set[str] = set()

    def walk(command: Command) -> None:
        names.update(_option_names(command))
        for child in _subcommands(command).values():
            walk(child)

    walk(_command_tree())
    return names


def test_documented_bare_flags_exist() -> None:
    """A flag named in prose or a table must exist somewhere in the CLI."""
    known = _every_option() | _FOREIGN_OPTIONS | _MCP_OPTIONS | _RETIRED_OPTIONS
    failures: list[str] = []
    for path in _doc_files():
        for flag in sorted(_bare_flags(path.read_text(encoding="utf-8"))):
            if flag not in known:
                failures.append(f"{path.name}: {flag} is not a flag of any command")
    joined = chr(10).join(failures)
    assert not failures, "documented flags the CLI does not define: " + joined


def _leaf_paths(
    command: Command, prefix: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    """Return every leaf command path in the application."""
    children = _subcommands(command)
    if not children:
        return [prefix]
    out: list[tuple[str, ...]] = []
    for name, child in children.items():
        out += _leaf_paths(child, (*prefix, name))
    return out


def test_every_command_is_documented() -> None:
    """Every command the application defines must appear somewhere in docs."""
    corpus = " ".join(p.read_text(encoding="utf-8") for p in _doc_files())
    missing = [
        " ".join(path)
        for path in _leaf_paths(_command_tree())
        if path and " ".join(path) not in corpus
    ]
    joined = chr(10).join(sorted(missing))
    assert not missing, "commands the docs never mention: " + joined
