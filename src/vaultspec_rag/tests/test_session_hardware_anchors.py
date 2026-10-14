"""A fixture above function scope never resolves the machine's hardware anchors.

pytest builds a module-, class- or session-scoped fixture before any
function-scoped one, so the per-test redirect of the anchors cannot cover what
such a fixture does. A fixture that indexes a corpus or loads a model asks for
the GPU owner anchor and the model-load window while it is built. Left to the
machine's own anchors, the ask is answered only by whichever process happens to
hold them: a loan, a refusal, or - when the anchor is free - a claim that the
test process then holds for the rest of its life. These tests resolve the
anchors from fixtures of each scope, with nothing claimed, and require every
answer to land outside the machine's anchor directory.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _anchors_resolved_now() -> tuple[Path, Path]:
    """Return where this process would claim the owner anchor and the window."""
    from .. import _gpu_admission, _gpu_owner

    return _gpu_owner.gpu_owner_anchor_path(), _gpu_admission.load_window_lock_path()


@pytest.fixture(scope="module")
def anchors_a_module_fixture_resolves() -> tuple[Path, Path]:
    return _anchors_resolved_now()


@pytest.fixture(scope="session")
def anchors_a_session_fixture_resolves() -> tuple[Path, Path]:
    return _anchors_resolved_now()


def _require_outside_the_machine_directory(
    scope: str, anchors: tuple[Path, Path]
) -> None:
    from .._anchor_claim import hardware_anchor_path

    machine = os.path.normcase(hardware_anchor_path("probe.lock").parent)
    for anchor in anchors:
        assert os.path.normcase(anchor.parent) != machine, (
            f"a {scope}-scoped fixture resolved the machine's own anchor "
            f"{anchor}. Every anchor a fixture reaches must resolve inside the "
            "suite's private tree."
        )


def test_a_module_scoped_fixture_resolves_no_machine_anchor(
    anchors_a_module_fixture_resolves: tuple[Path, Path],
) -> None:
    # Catches the redirect existing only per test: a module-scoped fixture is
    # built before that redirect, so it resolves the machine's own anchors.
    # Mutation: removed the session-wide redirect. Observed this assertion fail
    # naming the module-scoped fixture and the machine's owner anchor; restoring
    # it passed.
    _require_outside_the_machine_directory("module", anchors_a_module_fixture_resolves)


def test_a_session_scoped_fixture_resolves_no_machine_anchor(
    anchors_a_session_fixture_resolves: tuple[Path, Path],
) -> None:
    # Catches the same gap one scope up, where the shared model fixtures live.
    # Mutation: removed the session-wide redirect. Observed this assertion fail
    # naming the session-scoped fixture and the machine's owner anchor;
    # restoring it passed.
    _require_outside_the_machine_directory(
        "session", anchors_a_session_fixture_resolves
    )
