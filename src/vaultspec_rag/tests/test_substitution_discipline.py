"""Guard: the runtime-substitution surface may not grow unnoticed.

A substitute that replaces production behaviour makes an assertion true by its
own programming rather than by the code under test, so it can pass over a
regressed path. The surface was driven down to the sites below, each of which
was examined individually and kept for a reason recorded in its own docstring
at the call site.

This does not forbid substitution. It forbids adding one silently: a new site
fails here, and clearing the failure means either removing it or adding it to
the table with the reason it could not be driven for real. That is the review
step the count exists to force.

The scan is deliberately textual and counts per file rather than per line, so
it survives edits that move code around and only reacts to a site appearing or
disappearing.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = [pytest.mark.unit]

# Assembled rather than written literally, so this guard does not match itself.
_NEEDLES = ("monkeypatch." + "setattr", "monkeypatch." + "delattr")

# Path relative to the tests package -> (count, why it could not be driven for
# real). The reason belongs at the call site too; it is repeated here so a
# reader hitting a failure learns what bar a new entry has to clear.
_ALLOWED: dict[str, tuple[int, str]] = {
    "test_cli_index.py": (
        1,
        "the disk floor is a per-profile compile-time constant with no config "
        "override, so a real run cannot be driven under it; production's own "
        "ensure_disk_headroom raises, classifies and words the refusal",
    ),
    "test_cli_progress_surfaces.py": (
        1,
        "no substitute source can be staged - the provisioner requires https "
        "on a pinned host and an archive matching a committed digest - and "
        "the only real alternative is re-downloading the pinned release on "
        "every run, which the suite's mirror-the-installed-binary design "
        "exists to avoid",
    ),
    "test_cli_server.py": (
        1,
        "the substituted entry point's whole contract is to seize the terminal "
        "and not return until the operator leaves, so calling it for real "
        "hangs the run and no argument makes it terminate; the interface "
        "itself is driven for real elsewhere through the framework's pilot, "
        "and only the handoff is substituted",
    ),
}


def _substitution_counts() -> dict[str, int]:
    """Count substitution call sites per file across the test package."""
    tests_root = pathlib.Path(__file__).parent
    counts: dict[str, int] = {}
    for path in sorted(tests_root.rglob("*.py")):
        if path == pathlib.Path(__file__):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = sum(
            1
            for line in text.splitlines()
            if any(needle in line for needle in _NEEDLES)
        )
        if hits:
            counts[path.relative_to(tests_root).as_posix()] = hits
    return counts


def test_no_test_substitutes_production_behaviour_undeclared() -> None:
    """Every substitution site is one of the examined, documented keeps.

    Proven able to fail: adding a ``monkeypatch.setattr`` anywhere under the
    tests package fails on the unexpected-site assertion naming that file;
    removing it restores the pass. Raising a declared count has the same
    effect through the count comparison.
    """
    found = _substitution_counts()
    expected = {name: count for name, (count, _reason) in _ALLOWED.items()}

    unexpected = {name: n for name, n in found.items() if name not in expected}
    assert not unexpected, (
        "new runtime substitution(s) added without a recorded justification: "
        f"{unexpected}. Drive the behaviour for real, or add the file here "
        "with the reason it cannot be."
    )

    grown = {
        name: (found[name], expected[name])
        for name in expected
        if name in found and found[name] > expected[name]
    }
    assert not grown, (
        f"substitution count grew in {grown} (found, allowed). Each new site "
        "needs its own recorded reason."
    )


def test_the_declared_sites_all_still_exist() -> None:
    """A keep that disappeared must be removed from the table, not left.

    Without this the allowance outlives the site it was written for, and the
    next substitution added to that file inherits a justification nobody wrote
    for it.
    """
    found = _substitution_counts()
    stale = {
        name: count
        for name, (count, _reason) in _ALLOWED.items()
        if found.get(name, 0) < count
    }
    assert not stale, (
        f"declared substitution sites no longer present: {stale}. Lower or "
        "delete the entry so the allowance cannot be inherited."
    )
