"""Guards on the audit gates' exit-code contracts.

Both runners exist because an exit code was being derived from the wrong thing:
`uv audit` was trusted to fail on findings, and advisory scanners were given a
literal `; exit 0` that also swallowed their own breakage. These tests pin both
contracts as pure functions so a regression is caught without a network call or
a real scanner run.
"""

from __future__ import annotations

import pytest

from . import advisory, dependency_audit

CLEAN = "Found no known vulnerabilities and no adverse project statuses in 155 packages\n"
FINDINGS = (
    "vaultspec-rag v0.1.0\n"
    "- GHSA-q2x7-8rv6-6q7h: Jinja has a sandbox breakout\n"
    "  Fixed in: 3.1.5\n"
)


@pytest.mark.unit
def test_clean_tree_and_clean_exit_passes() -> None:
    assert dependency_audit.verdict(CLEAN, 0) == 0


@pytest.mark.unit
def test_findings_fail_even_when_uv_exits_zero() -> None:
    """The defect this gate exists for: findings reported, process exit 0."""
    assert dependency_audit.verdict(FINDINGS, 0) == 1
    assert "exited 0" in dependency_audit.explain(FINDINGS, 0)


@pytest.mark.unit
def test_findings_fail_when_uv_exits_nonzero() -> None:
    assert dependency_audit.verdict(FINDINGS, 1) == 1


@pytest.mark.unit
def test_audit_that_could_not_complete_fails() -> None:
    """A clean summary with a non-zero exit is a broken audit, not a pass."""
    assert dependency_audit.verdict(CLEAN, 2) == 1


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
