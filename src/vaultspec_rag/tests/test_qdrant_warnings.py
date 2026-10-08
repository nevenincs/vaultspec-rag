"""The refused-endpoint warning wait judges the client's warnings, and all of them.

The tests that drive a real client against a refused endpoint share one wait
for its asynchronous warning. These pin what that wait may and may not be
ended or failed by, using warnings raised here in the shapes the real ones
arrive in: one from the garbage collector on this thread, one from a thread
that answers later.
"""

from __future__ import annotations

import threading
import time
import warnings

import pytest

from ._qdrant_warnings import VERSION_WARNING, await_client_warnings

pytestmark = pytest.mark.unit

#: Long enough that a wait which stopped early has already compared.
PROBE_DELAY_SECONDS = 0.2


def _warn_later(message: str) -> threading.Thread:
    """Start a thread that raises *message* as a ``UserWarning`` after a delay."""

    def answer() -> None:
        time.sleep(PROBE_DELAY_SECONDS)
        warnings.warn(message, UserWarning, stacklevel=1)

    thread = threading.Thread(target=answer)
    thread.start()
    return thread


def test_a_collector_warning_neither_ends_the_wait_nor_fails_it() -> None:
    """An unclosed-resource warning in scope leaves the wait on the client.

    Mutation proof: ending the wait once as many warnings of any kind had
    arrived as were expected made this fail on the helper's comparison, and
    so did counting ``ResourceWarning`` among the client's; restoring each
    made it pass.
    """
    with warnings.catch_warnings():
        # The scope below hands the collector's warning back when it closes.
        warnings.simplefilter("ignore", ResourceWarning)
        with pytest.warns(UserWarning, match="Failed to obtain") as captured:
            warnings.warn("unclosed database", ResourceWarning, stacklevel=1)
            probe = _warn_later(VERSION_WARNING)
            try:
                await_client_warnings(captured, [VERSION_WARNING])
            finally:
                probe.join()


def test_a_client_warning_nobody_expected_fails_the_wait() -> None:
    """A warning beyond the expected ones is a difference, not noise.

    Mutation proof: asserting only that every expected warning had arrived
    made this fail with nothing raised; restoring the exact comparison made
    it pass.
    """
    with pytest.warns(UserWarning) as captured:
        warnings.warn(VERSION_WARNING, UserWarning, stacklevel=1)
        warnings.warn("a second thing the client said", UserWarning, stacklevel=1)
        with pytest.raises(AssertionError):
            await_client_warnings(captured, [VERSION_WARNING])
