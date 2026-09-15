"""Guards on the audit gates' exit-code contracts.

This runner exists because an exit code was being derived from the wrong thing:
advisory scanners were given a literal `; exit 0`, which also swallowed their
own breakage. These tests pin that contract as a pure function so a regression
is caught without a real scanner run. The dependency gate's own contract lives
with the gate, in dev/audit/tests/test_dependency_audit_gate.py.
"""

from __future__ import annotations

import pytest

from . import advisory

CLEAN = (
    "Found no known vulnerabilities and no adverse project statuses in 155 packages\n"
)
FINDINGS = (
    "vaultspec-rag v0.1.0\n"
    "- GHSA-q2x7-8rv6-6q7h: Jinja has a sandbox breakout\n"
    "  Fixed in: 3.1.5\n"
)


@pytest.mark.unit
def test_advisory_maps_findings_onto_success() -> None:
    assert advisory.verdict(1, frozenset({1})) == 0
    assert advisory.verdict(3, frozenset({3})) == 0
    assert advisory.verdict(0, frozenset({1})) == 0


@pytest.mark.unit
def test_advisory_propagates_a_broken_scanner() -> None:
    """A scanner that crashed is not a scanner that found nothing."""
    assert advisory.verdict(2, frozenset({1})) == 2
    assert advisory.verdict(127, frozenset({1})) == 127


@pytest.mark.unit
def test_advisory_argument_parsing() -> None:
    findings, command = advisory.parse_args(
        ["--finding-exit", "3", "--", "vulture", "src"]
    )
    assert findings == frozenset({3})
    assert command == ["vulture", "src"]

    findings, command = advisory.parse_args(["--", "deptry", "src"])
    assert findings == frozenset({1}), "the default finding code is 1"

    with pytest.raises(ValueError):
        advisory.parse_args(["bandit", "-r", "src"])
    with pytest.raises(ValueError):
        advisory.parse_args(["--finding-exit", "1", "--"])


@pytest.mark.unit
def test_advisory_resolves_windows_batch_shim_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve ``npx.cmd`` while keeping argv opaque to a shell."""

    def fake_which(executable: str) -> str | None:
        return r"C:\Program Files\nodejs\npx.CMD" if executable == "npx" else None

    monkeypatch.setattr(
        advisory.shutil,
        "which",
        fake_which,
    )

    command = ["npx", "--yes", "jscpd", "src", "folder with spaces"]

    assert advisory.resolve_command(command) == [
        r"C:\Program Files\nodejs\npx.CMD",
        "--yes",
        "jscpd",
        "src",
        "folder with spaces",
    ]


@pytest.mark.unit
def test_advisory_launches_resolved_command_with_original_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner passes the resolved executable and no shell command string."""
    calls: list[tuple[list[str], bool, bool]] = []

    def fake_which(executable: str) -> str | None:
        return r"C:\Node\npx.cmd" if executable == "npx" else None

    class Completed:
        returncode = 1

    def fake_run(command: list[str], *, check: bool, shell: bool) -> Completed:
        calls.append((command, check, shell))
        return Completed()

    monkeypatch.setattr(
        advisory.shutil,
        "which",
        fake_which,
    )
    monkeypatch.setattr(advisory.subprocess, "run", fake_run)

    assert (
        advisory.main(
            ["--finding-exit", "1", "--", "npx", "--yes", "jscpd", "folder with spaces"]
        )
        == 0
    )
    assert calls == [
        (
            [r"C:\Node\npx.cmd", "--yes", "jscpd", "folder with spaces"],
            False,
            False,
        )
    ]


@pytest.mark.unit
def test_advisory_keeps_missing_scanner_as_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolution must not turn an absent scanner into an advisory pass."""

    def fake_which(_executable: str) -> str | None:
        return None

    monkeypatch.setattr(advisory.shutil, "which", fake_which)

    assert advisory.main(["--", "missing-scanner"]) == 127
