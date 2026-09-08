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
