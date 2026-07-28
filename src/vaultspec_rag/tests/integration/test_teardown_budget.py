"""The graceful-exit courtesy a live-service teardown funds, per platform.

A courtesy wait is free whenever the signal behind it can land: the wait ends
the moment the daemon exits, so a generous window costs nothing on a healthy
teardown. That is true on POSIX, where ``SIGTERM`` reaches the daemon.

It is false on Windows. The daemon is spawned with ``CREATE_NO_WINDOW``, which
puts it on a console of its own, and a console control event only reaches
processes sharing the sender's console - so the event never arrives, the daemon
never begins shutting down, and the window is spent in full before the
force-kill that actually ends it. Measured on this project's own fixture, that
was a flat five seconds on every single live-service teardown.

Both branches are stated here because a host can only ever run one of them, and
reassigning ``sys.platform`` to simulate the other would only prove that a
module read a string someone had just written.
"""

from __future__ import annotations

import pytest

from .conftest import (
    _TEARDOWN_GRACEFUL_COURTESY_SECONDS,
    teardown_graceful_courtesy_seconds,
)

pytestmark = [pytest.mark.unit]


class TestTeardownGracefulCourtesy:
    """Windows funds no courtesy; POSIX funds a real one.

    Proven able to fail: returning ``_TEARDOWN_GRACEFUL_COURTESY_SECONDS``
    unconditionally from ``teardown_graceful_courtesy_seconds`` fails
    ``test_windows_does_not_fund_a_courtesy_it_cannot_use`` on
    ``assert ... == 0.0`` (5.0 != 0.0) and
    ``test_the_two_platforms_fund_different_windows`` on its inequality;
    returning ``0.0`` unconditionally fails
    ``test_posix_funds_a_real_courtesy`` on its equality and the inequality
    test again. Restoring the branch returns all three to green.
    """

    def test_windows_does_not_fund_a_courtesy_it_cannot_use(self) -> None:
        assert teardown_graceful_courtesy_seconds("win32") == 0.0

    def test_posix_funds_a_real_courtesy(self) -> None:
        for platform in ("linux", "darwin"):
            assert (
                teardown_graceful_courtesy_seconds(platform)
                == _TEARDOWN_GRACEFUL_COURTESY_SECONDS
            )

    def test_the_two_platforms_fund_different_windows(self) -> None:
        # The rule is only meaningful if the branches differ; a refactor that
        # collapsed them would leave both assertions above passing on one
        # constant.
        assert teardown_graceful_courtesy_seconds(
            "win32"
        ) != teardown_graceful_courtesy_seconds("linux")

    def test_a_funded_courtesy_is_a_positive_window(self) -> None:
        # ``_cleanup_service_process`` sends the graceful signal only when the
        # courtesy is positive, so a zero POSIX window would silently drop the
        # signal rather than shorten the wait.
        assert _TEARDOWN_GRACEFUL_COURTESY_SECONDS > 0.0
