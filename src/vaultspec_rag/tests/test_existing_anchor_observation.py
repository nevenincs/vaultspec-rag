"""Real no-create observations of captured service identity anchors."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .._anchor_claim import (
    _OWNER_RECORD_WAIT_SECONDS,
    AnchorOutcome,
    claim_anchor,
    observe_existing_anchor,
    record_claim_owner,
    release_anchor_claim,
)
from .._machine_lock import (
    _probe_existing_machine_lock_holder,
    capture_pre_isolation_machine_lock,
    machine_lock_path,
)
from ..config._settings import reset_config
from ..config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_PROCESS_TIMEOUT_SECONDS = 10.0

# Observations taken against a holder that is republishing its owner record.
# The truncate-then-write order this guards against leaves the anchor empty for
# roughly one part in seventy of each publication, so a few hundred samples put
# several hits inside a reverted build and none inside a correct one.
_RACE_SAMPLES = 500
_HOLD_EXISTING_ANCHOR = """
import os
import sys
import time
from pathlib import Path

from vaultspec_rag._anchor_claim import (
    claim_anchor,
    record_claim_owner,
    release_anchor_claim,
)

anchor = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
claim = claim_anchor(anchor, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
try:
    record_claim_owner(claim.descriptor)
    ready_path.write_text(str(os.getpid()), encoding="ascii")
    while not stop_path.exists():
        time.sleep(0.01)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
"""


_REPUBLISH_OWNER_RECORD = """
import os
import sys
from pathlib import Path

from vaultspec_rag._anchor_claim import (
    claim_anchor,
    record_claim_owner,
    release_anchor_claim,
)

anchor = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
claim = claim_anchor(anchor, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
try:
    record_claim_owner(claim.descriptor)
    ready_path.write_text(str(os.getpid()), encoding="ascii")
    while not stop_path.exists():
        record_claim_owner(claim.descriptor)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
"""

_DELAYED_FIRST_PUBLICATION = """
import os
import sys
import time
from pathlib import Path

from vaultspec_rag._anchor_claim import (
    claim_anchor,
    record_claim_owner,
    release_anchor_claim,
)

anchor = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
delay = float(sys.argv[4])
claim = claim_anchor(anchor, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
try:
    # Locked and still zero length: exactly the state a holder is in between
    # creating its anchor and publishing its first owner record.
    assert anchor.stat().st_size == 0, anchor.stat().st_size
    ready_path.write_text(str(os.getpid()), encoding="ascii")
    time.sleep(delay)
    record_claim_owner(claim.descriptor)
    while not stop_path.exists():
        time.sleep(0.01)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
"""


_HOLD_FOREIGN_BODY = """
import os
import sys
import time
from pathlib import Path

from vaultspec_rag._anchor_claim import claim_anchor, release_anchor_claim

anchor = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
claim = claim_anchor(anchor, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
try:
    # A body no writer will ever turn into an owner record.
    os.lseek(claim.descriptor, 0, os.SEEK_SET)
    os.write(claim.descriptor, b"retired anchor")
    os.fsync(claim.descriptor)
    ready_path.write_text(str(os.getpid()), encoding="ascii")
    while not stop_path.exists():
        time.sleep(0.01)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
"""


@contextmanager
def _held_anchor(
    tmp_path: Path,
    script: str,
    *extra: str,
    name: str,
    anchor: Path | None = None,
) -> Generator[tuple[Path, int]]:
    """Run *script* holding a real anchor and yield its path and holder pid."""
    anchor = anchor if anchor is not None else tmp_path / f"{name}.lock"
    ready_path = tmp_path / f"{name}-ready"
    stop_path = tmp_path / f"{name}-stop"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(anchor),
            str(ready_path),
            str(stop_path),
            *extra,
        ],
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # The readiness file appears before its contents land, so poll for a
        # parseable pid rather than for the path: an empty read here is the
        # holder mid-write, not a holder that failed to start.
        holder_pid = 0
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while holder_pid == 0 and process.poll() is None:
            assert time.monotonic() < deadline, "real anchor holder did not start"
            with contextlib.suppress(OSError, ValueError):
                holder_pid = int(ready_path.read_text(encoding="ascii"))
            if holder_pid == 0:
                time.sleep(0.01)
        assert holder_pid > 0, "real anchor holder exited before readiness"
        yield anchor, holder_pid
    finally:
        if process.poll() is None:
            stop_path.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.stderr.close()
        assert process.returncode == 0, stderr


def test_republished_owner_record_is_never_observed_absent(tmp_path: Path) -> None:
    """A holder replacing its witness never exposes an anchor with no owner.

    The record is published in place - the OS lock is bound to this file, so it
    cannot be swapped in by rename - which makes write ORDER the whole
    guarantee. Mutation: restoring the truncate-then-write order in
    ``record_claim_owner`` empties the anchor between the two calls, and this
    assertion fires with a non-zero count of live-holder-no-owner reads.
    """
    with _held_anchor(tmp_path, _REPUBLISH_OWNER_RECORD, name="republish") as (
        anchor,
        holder_pid,
    ):
        # A fixed sample COUNT, not a fixed duration: the count is what carries
        # the statistical power, and a loaded machine must not be allowed to
        # quietly reduce it to a handful of reads that prove nothing.
        unreadable = 0
        samples = 0
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while samples < _RACE_SAMPLES:
            assert time.monotonic() < deadline, f"only reached {samples} samples"
            observation = observe_existing_anchor(anchor, pid_record=True)
            assert observation.outcome is AnchorOutcome.CONTENDED
            samples += 1
            if observation.holder_pid != holder_pid:
                unreadable += 1

        assert unreadable == 0, (
            f"{unreadable} of {samples} observations of a live holder could not "
            "name it while it republished its owner record"
        )


def test_owner_record_still_in_flight_is_waited_out_not_read_as_absent(
    tmp_path: Path,
) -> None:
    """A locked, zero-length anchor resolves to its holder rather than to none.

    A holder must create and lock its anchor before it can publish anything, so
    an empty file under a refused lock is a record in flight, not evidence that
    nobody owns the anchor. Mutation: returning 0 immediately for a zero-length
    anchor instead of waiting makes ``holder_pid`` 0 and fails this assertion.
    """
    with _held_anchor(
        tmp_path,
        _DELAYED_FIRST_PUBLICATION,
        "0.02",
        name="delayed",
    ) as (anchor, holder_pid):
        observation = observe_existing_anchor(anchor, pid_record=True)

        assert observation.outcome is AnchorOutcome.CONTENDED
        assert observation.holder_pid == holder_pid, (
            "a holder that had not yet published its first record was reported "
            "as an anchor with no owner"
        )
        assert _probe_existing_machine_lock_holder(anchor) == holder_pid


def test_unparseable_owner_record_is_refused_without_waiting(tmp_path: Path) -> None:
    """A body that is present but pid-less is a decided answer, not a wait.

    Only a zero-length anchor can still be published to; no writer turns a
    foreign body into an owner record, so waiting on one would stall every
    refused contender for the full bound. Mutation: dropping the emptiness
    condition from the wait makes this read take the whole bound and fails the
    elapsed-time assertion.
    """
    with _held_anchor(tmp_path, _HOLD_FOREIGN_BODY, name="foreign") as (
        anchor,
        _holder_pid,
    ):
        assert anchor.stat().st_size > 0

        # The fastest of several reads, because a single sample on a loaded
        # machine can exceed the bound without any wait having happened. A read
        # that does wait waits every time, so the minimum still exposes it.
        timings: list[float] = []
        for _ in range(5):
            started = time.monotonic()
            observation = observe_existing_anchor(anchor, pid_record=True)
            timings.append(time.monotonic() - started)
            assert observation.outcome is AnchorOutcome.CONTENDED
            assert observation.holder_pid == 0

        assert min(timings) < _OWNER_RECORD_WAIT_SECONDS, (
            f"an unparseable body was waited on for {min(timings):.3f}s"
        )


def test_published_owner_record_stays_readable_as_plain_json(tmp_path: Path) -> None:
    """The record a build with no knowledge of the padding still parses.

    The fixed width is carried as trailing spaces inside the same one-key JSON
    object the record has always been, so a reader that simply parses the whole
    file - every build that predates the padding does exactly that - recovers
    the pid unchanged. Mutation: padding with anything JSON does not ignore, or
    appending the width outside the object, fails this parse.
    """
    anchor = tmp_path / "published.lock"
    claim = claim_anchor(anchor, pid_record=True, create_parent=True)
    assert claim.descriptor is not None, claim
    try:
        record_claim_owner(claim.descriptor)
    finally:
        release_anchor_claim(claim.descriptor, pid_record=True)

    assert json.loads(anchor.read_text(encoding="utf-8")) == {"pid": os.getpid()}


@contextmanager
def _relocated_machine_paths(tmp_path: Path) -> Generator[None]:
    """Point the no-argument capture facade at this test's real temp paths."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    prior_storage = os.environ.get(storage_key)
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield
    finally:
        if prior_storage is None:
            os.environ.pop(storage_key, None)
        else:
            os.environ[storage_key] = prior_storage
        reset_config()


def test_deleted_existing_anchor_is_absent_and_never_recreated(tmp_path: Path) -> None:
    """Deletion before the single no-create open refuses without recreation."""
    identity_lock_path = tmp_path / "original-service.lock"
    identity_lock_path.write_text('{"pid": 123}', encoding="utf-8")
    identity_lock_path.unlink()

    observation = observe_existing_anchor(identity_lock_path, pid_record=True)

    assert observation.outcome is AnchorOutcome.ABSENT
    assert observation.descriptor is None
    assert observation.fault is None
    assert _probe_existing_machine_lock_holder(identity_lock_path) is None
    assert not identity_lock_path.exists()


def test_existing_anchor_observation_reports_an_open_fault(tmp_path: Path) -> None:
    """An existing directory is an unusable anchor, not a path to create."""
    observation = observe_existing_anchor(tmp_path, pid_record=True)

    assert observation.outcome is AnchorOutcome.UNAVAILABLE
    assert observation.descriptor is None
    assert observation.holder_pid == 0
    assert observation.fault is not None


def test_pre_isolation_machine_capture_derives_paths_without_creating(
    tmp_path: Path,
) -> None:
    """The public capture facade refuses an absent lock without creating it."""
    with _relocated_machine_paths(tmp_path):
        identity_lock_path = machine_lock_path()

        captured = capture_pre_isolation_machine_lock()

        assert captured is None
        assert not identity_lock_path.exists()


def test_existing_anchor_observation_reads_a_real_contended_owner_pid(
    tmp_path: Path,
) -> None:
    """A separate process's durable record is recovered without retention."""
    with _held_anchor(tmp_path, _HOLD_EXISTING_ANCHOR, name="holder") as (
        identity_lock_path,
        expected_pid,
    ):
        observation = observe_existing_anchor(identity_lock_path, pid_record=True)

        assert observation.outcome is AnchorOutcome.CONTENDED
        assert observation.descriptor is None
        assert observation.fault is None
        assert observation.holder_pid == expected_pid
        assert _probe_existing_machine_lock_holder(identity_lock_path) == expected_pid


def test_pre_isolation_machine_capture_refuses_after_root_registration(
    tmp_path: Path,
) -> None:
    """The no-argument facade cannot capture a post-root external lock."""
    with (
        _relocated_machine_paths(tmp_path),
        _held_anchor(
            tmp_path,
            _HOLD_EXISTING_ANCHOR,
            name="capture-holder",
            anchor=machine_lock_path(),
        ),
    ):
        assert capture_pre_isolation_machine_lock() is None
