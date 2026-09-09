"""Production states how it decodes a child process, or reads bytes.

THE FAILURE THIS PREVENTS, WHICH COST A SISTER REPOSITORY HOURS. A harness
exports ``PYTHONIOENCODING=utf-8`` so its own output survives a Windows
console. Every child it spawns inherits that, so a CLI reading its input as
text became UTF-8 STRICT - and died on a legacy byte, uncaught, emitting a
traceback where the contract promised a structured envelope. The bug was in
neither the harness nor the CLI on its own; it was in the CLI depending on an
encoding somebody else chose.

Two properties follow, and this guard holds the second:

- Nothing in the shipped package reads standard input as text. There is no
  ``sys.stdin.read()`` on any command path, which is what makes the inbound
  half of that failure unreachable here.

- Nothing in the shipped package decodes a CHILD's output under the ambient
  encoding. ``text=True`` with no ``encoding=`` decodes under whatever the
  process happens to have, strictly, so one byte outside ASCII raises
  ``UnicodeDecodeError`` - and it raises inside functions whose whole purpose
  is to report rather than to throw: a process probe that must return a
  verdict, and an installer step that exists to surface a tool's stderr
  WITHOUT a traceback. Both were doing it.

A SECOND REASON THE AMBIENT ENCODING IS THE WRONG ONE HERE. It differs
between a recipe and a bare invocation, because the harness sets it and a bare
``pytest`` does not. So a subprocess test that decodes ambiently passes under
``just`` and fails under ``pytest`` - or the reverse - and a reproduction run
the other way measures the shell rather than the code. Bisect through the
recipe; better, do not depend on it at all.

SCOPE. The shipped package only. The suite has its own sites, and they are a
smaller problem: a test that dies decoding is a test that FAILS, which is
visible. Production dying decoding is an operator seeing a traceback where the
contract promised an answer.
"""

from __future__ import annotations

import ast

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The shipped package. The suite inside it is out of scope - see above.
PACKAGE = "src/vaultspec_rag"
TESTS = "tests"

#: Calls that can spawn a child and hand back its output.
_SPAWNS = frozenset({"run", "Popen", "check_output"})

#: Kwargs that ask for DECODED output. Either one without ``encoding`` beside
#: it is the finding; ``text=False`` is bytes and is exactly right.
_DECODES = ("text", "universal_newlines")


def _asks_for_text(call: ast.Call) -> bool:
    """Whether *call* requests decoded output rather than bytes."""
    for keyword in call.keywords:
        if keyword.arg in _DECODES:
            value = keyword.value
            # `text=False` is the byte-reading form this guard wants.
            return not (isinstance(value, ast.Constant) and value.value is False)
    return False


def _states_the_encoding(call: ast.Call) -> bool:
    """Whether *call* names the encoding it decodes under."""
    return any(keyword.arg == "encoding" for keyword in call.keywords)


def _called_name(call: ast.Call) -> str:
    """Return the bare name a call invokes."""
    return getattr(call.func, "attr", getattr(call.func, "id", ""))


def test_no_shipped_module_decodes_a_child_ambiently() -> None:
    """Every production spawn that decodes output names its encoding.

    Guard assertion: dropping ``encoding=`` from either repaired site - or
    adding a third spawn with a bare ``text=True`` - fails here, at the file
    and line, before the byte that would have raised ever appears.
    """
    root = workflows.repository_root()
    package = root / PACKAGE
    findings: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if TESTS in path.relative_to(package).parts:
            continue
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), relative)
        findings.extend(
            f"{relative}:{node.lineno}: `{_called_name(node)}` decodes the "
            "child's output with no stated encoding"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _called_name(node) in _SPAWNS
            and _asks_for_text(node)
            and not _states_the_encoding(node)
        )
    assert not findings, (
        "A shipped module decodes a child process under the ambient "
        "encoding.\n"
        'State it - `encoding="utf-8", errors="replace"` - or read bytes '
        "with `text=False`. The ambient encoding is chosen by whoever spawned "
        "this process, differs between a recipe and a bare invocation, and "
        "raises rather than degrading.\n\n" + "\n".join(findings)
    )


def test_no_shipped_module_reads_standard_input_as_text() -> None:
    """No command path decodes standard input under the ambient encoding.

    Guard assertion: this is the inbound half of the same failure. A CLI that
    reads ``sys.stdin`` as text inherits its strictness from the parent, so
    the byte that kills it is one the caller chose and the CLI never sees
    coming - and the death is a traceback where a structured envelope was
    promised.
    """
    root = workflows.repository_root()
    package = root / PACKAGE
    findings: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if TESTS in path.relative_to(package).parts:
            continue
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if not isinstance(target, ast.Attribute) or target.attr not in {
                "read",
                "readline",
                "readlines",
            }:
                continue
            owner = target.value
            if (
                isinstance(owner, ast.Attribute)
                and owner.attr == "stdin"
                and isinstance(owner.value, ast.Name)
                and owner.value.id in {"sys", "_sys"}
            ):
                findings.append(f"{relative}:{node.lineno}: reads `sys.stdin` as text")
    assert not findings, (
        "A shipped module reads standard input as text, so its decoding is "
        "whatever the parent process set.\n"
        "Read `sys.stdin.buffer` and decode explicitly, with a non-raising "
        "error handler.\n\n" + "\n".join(findings)
    )
