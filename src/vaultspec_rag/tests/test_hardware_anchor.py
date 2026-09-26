"""Hardware anchors: one machine-wide location every account contends for.

An anchor guarding the GPU only excludes anything if every process on the
machine resolves the same file, and if every account can lock it. Both are
proved here against the real resolver and real locks: relocating every variable
a process could change leaves the location where it was, and an anchor this
process may read but not write - the shape another account's anchor has - is
still claimed and still contended.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from .. import _gpu_admission
from .._anchor_claim import (
    AnchorOutcome,
    claim_anchor,
    observe_existing_anchor,
    release_anchor_claim,
)
from .._gpu_admission import _claim_load_window

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# The real resolvers are the subject here, so this module opts out of the
# per-test anchor redirect. Nothing in it claims a machine anchor: the
# locations are read, and every lock it takes is on a temporary file.
pytestmark = [pytest.mark.unit, pytest.mark.real_hardware_anchor]

# Every variable a process can set to move a path it resolves: the Windows
# ProgramData and temporary variables, their POSIX counterparts, both homes,
# and both of this project's configured directories.
_RELOCATING_VARIABLES = (
    "ProgramData",
    "PROGRAMDATA",
    "ALLUSERSPROFILE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "VAULTSPEC_RAG_QDRANT_STORAGE_DIR",
    "VAULTSPEC_RAG_STATUS_DIR",
)


# Each location is resolved in a fresh interpreter, so nothing this process has
# cached - ``gettempdir`` memoises its answer - can hide a resolver that reads
# the environment.
_RESOLVE = (
    "from vaultspec_rag._anchor_claim import hardware_anchor_path; "
    "from vaultspec_rag._gpu_admission import load_window_lock_path; "
    "print(hardware_anchor_path('probe.lock')); print(load_window_lock_path())"
)


def _resolved_under(environment: dict[str, str]) -> list[str]:
    return subprocess.run(
        [sys.executable, "-c", _RESOLVE],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.splitlines()


def test_anchor_locations_ignore_every_variable_a_process_can_change(
    tmp_path: Path,
) -> None:
    relocated = dict(os.environ)
    for index, name in enumerate(_RELOCATING_VARIABLES):
        # Created, so a resolver consulting one of them would really use it
        # rather than skip a missing directory and land back where it was.
        # Numbered, because Windows folds the spellings of one variable - and
        # of one directory - together.
        elsewhere = tmp_path / f"relocated-{index}"
        elsewhere.mkdir()
        relocated[name] = str(elsewhere)

    unchanged = _resolved_under(dict(os.environ))

    # Catches a resolver reading any of these variables - such as
    # ``os.environ["ProgramData"]``, or the load window moving back under
    # ``tempfile.gettempdir()`` - where a different TEMP, account or
    # configuration gives a second process an anchor of its own.
    assert _resolved_under(relocated) == unchanged
    assert len(unchanged) == 2


@pytest.fixture
def foreign_anchor(tmp_path: Path) -> Iterator[Path]:
    """An anchor this process may read but not write, as another account's is."""
    anchor = tmp_path / "foreign.lock"
    anchor.write_bytes(b"")
    anchor.chmod(stat.S_IREAD)
    try:
        writable = os.open(anchor, os.O_RDWR)
    except PermissionError:
        pass
    else:
        os.close(writable)
        anchor.chmod(stat.S_IREAD | stat.S_IWRITE)
        pytest.skip("this process's privileges ignore file permissions")
    try:
        yield anchor
    finally:
        anchor.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_shared_anchor_another_account_created_is_still_claimed_and_contended(
    foreign_anchor: Path,
) -> None:
    first = claim_anchor(foreign_anchor, shared=True)
    # Catches the read-only fallback being removed: the claim then fails to
    # open the anchor and reports it unavailable instead of held.
    assert first.outcome is AnchorOutcome.HELD, first
    assert first.descriptor is not None
    try:
        assert claim_anchor(foreign_anchor, shared=True).outcome is (
            AnchorOutcome.CONTENDED
        )
        assert observe_existing_anchor(foreign_anchor, shared=True).outcome is (
            AnchorOutcome.CONTENDED
        )
    finally:
        release_anchor_claim(first.descriptor)
    assert observe_existing_anchor(foreign_anchor, shared=True).outcome is (
        AnchorOutcome.FREE
    )


def test_an_unshared_anchor_this_process_cannot_write_is_unavailable(
    foreign_anchor: Path,
) -> None:
    claim = claim_anchor(foreign_anchor)

    # The read-only fallback belongs to shared anchors only: an identity anchor
    # whose owner record must be written is refused rather than half-claimed.
    assert claim.outcome is AnchorOutcome.UNAVAILABLE
    assert isinstance(claim.fault, PermissionError)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_observing_a_private_anchor_through_the_shared_path_keeps_its_mode(
    tmp_path: Path,
) -> None:
    private = tmp_path / "service.lock"
    private.write_bytes(b"")
    private.chmod(0o600)

    observe_existing_anchor(private, pid_record=True, shared=True)
    held = claim_anchor(private, pid_record=True, shared=True)
    if held.descriptor is not None:
        release_anchor_claim(held.descriptor, pid_record=True)

    # Catches the shared path widening a file it did not create: a service's
    # own lock, observed by a peer, would become writable by every account.
    assert stat.S_IMODE(private.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_a_shared_anchor_this_process_creates_is_writable_by_every_account(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "gpu-owner.lock"

    held = claim_anchor(anchor, pid_record=True, create_parent=True, shared=True)
    assert held.descriptor is not None
    release_anchor_claim(held.descriptor, pid_record=True)

    # Catches creation losing the widening past the umask: a second account
    # could then lock the anchor only read-only and never publish its pid.
    assert stat.S_IMODE(anchor.stat().st_mode) == 0o666


def test_an_unresolvable_load_window_degrades_rather_than_refusing_every_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Substituted because a host with no directory every account shares cannot
    # be staged here: the suite can neither remove the machine's shared
    # directories nor make the Windows known-folder API fail.
    def unresolvable() -> Path:
        raise OSError("no machine-wide anchor directory")

    monkeypatch.setattr(_gpu_admission, "load_window_lock_path", unresolvable)

    claim = _claim_load_window(None)

    assert claim.outcome is AnchorOutcome.UNAVAILABLE
    assert isinstance(claim.fault, OSError)
