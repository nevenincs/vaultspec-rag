"""What a refused lock call on an anchor is taken to mean.

A non-blocking lock call fails when another holder has the lock, and it also
fails when the filesystem carries no locks, the call is not implemented, or
the device errors. Only the first is an answer about ownership. A caller that
waits for a holder must not wait out its whole bound on a filesystem that
will never grant the lock.

Two halves, kept apart because only one of them can be staged here. Real
contention is driven for real: a second claim on a held anchor is refused by
the operating system, and whatever error it raises on this platform must sort
as a holder. A filesystem that refuses the lock call itself is not available
to this suite, so that half is the sorting of error numbers alone, which is
pure logic: the errors are constructed, and nothing here shows what any
particular filesystem returns.
"""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING

import pytest

from .._anchor_claim import (
    AnchorOutcome,
    _lock_refused_by_a_holder,
    _refused_lock,
    claim_anchor,
    observe_existing_anchor,
    record_claim_owner,
    release_anchor_claim,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("pid_record", [True, False])
def test_a_real_refusal_by_a_holder_is_contention_on_this_platform(
    tmp_path: Path, pid_record: bool
) -> None:
    """The error this operating system raises for a held lock sorts as a holder.

    The lock is held through one descriptor and claimed through another,
    which the operating system refuses as it refuses another process.

    Mutation: took this platform's contention error number out of the set
    that means a holder. Observed the outcome assertion fail
    (``unavailable`` where ``contended`` was required), for the claim and
    for the observation. Restored; passes.
    """
    anchor = tmp_path / "anchor.lock"
    held = claim_anchor(anchor, pid_record=pid_record)
    assert held.descriptor is not None, held
    try:
        if pid_record:
            record_claim_owner(held.descriptor)

        claimed = claim_anchor(anchor, pid_record=pid_record)
        observed = observe_existing_anchor(anchor, pid_record=pid_record)
    finally:
        release_anchor_claim(held.descriptor, pid_record=pid_record)

    for refused in (claimed, observed):
        assert refused.outcome is AnchorOutcome.CONTENDED
        assert refused.descriptor is None
        assert refused.fault is None
        assert refused.holder_pid == (os.getpid() if pid_record else 0)


@pytest.mark.parametrize(
    "number",
    [errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK],
)
def test_an_error_that_means_the_lock_is_held_is_a_holder(number: int) -> None:
    assert _lock_refused_by_a_holder(OSError(number, os.strerror(number)))


@pytest.mark.parametrize(
    "number",
    [errno.ENOLCK, errno.ENOSYS, errno.EINVAL, errno.EIO, errno.EBADF, errno.EROFS],
)
def test_an_error_that_says_nothing_about_a_holder_is_not_one(number: int) -> None:
    """No locks here, no such call, a bad argument, a failing device.

    Mutation: made ``_lock_refused_by_a_holder`` answer yes to every error,
    which is what reading every refusal as contention amounted to. Observed
    each case fail, and the outcome assertion in the test below. Restored;
    passes.
    """
    assert not _lock_refused_by_a_holder(OSError(number, os.strerror(number)))


def test_a_lock_call_that_cannot_be_made_is_a_fault_carrying_its_reason(
    tmp_path: Path,
) -> None:
    """The caller is told at once what failed, and is not admitted.

    The descriptor is a real one on a real file. The error is constructed:
    it stands for a filesystem that carries no locks, which this suite has
    none of.
    """
    anchor = tmp_path / "anchor.lock"
    anchor.write_text('{"pid": 4242}', encoding="utf-8")
    descriptor = os.open(anchor, os.O_RDWR)
    no_locks = OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))

    refused = _refused_lock(anchor, descriptor, no_locks, pid_record=True)

    assert refused.outcome is AnchorOutcome.UNAVAILABLE
    assert refused.fault is no_locks
    assert refused.descriptor is None
    # No holder is named: nothing was learned about one.
    assert refused.holder_pid == 0
    # The descriptor was closed: the operating system no longer knows it.
    with pytest.raises(OSError, match=r"Bad file descriptor|handle is invalid"):
        os.fstat(descriptor)
