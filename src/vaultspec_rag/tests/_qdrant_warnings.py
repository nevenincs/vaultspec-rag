"""Wait for the real SDK's asynchronous refused-endpoint warning in tests."""

from __future__ import annotations

import time
from collections import Counter
from typing import TYPE_CHECKING

from ._child_signal import PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    import pytest

VERSION_WARNING = (
    "Failed to obtain server version. Unable to check client-server compatibility. "
    "Set check_compatibility=False to skip version check."
)
INSECURE_KEY_WARNING = "Api key is used with an insecure connection."


def _client_warnings(captured: pytest.WarningsRecorder) -> Counter[str]:
    """Return the captured messages, less what the garbage collector raised.

    The interpreter raises ``ResourceWarning`` when it collects an unclosed
    resource, at a moment of its own choosing and on behalf of whatever left
    the resource open. One that lands in the caller's scope says nothing about
    the client. ``pytest.warns`` hands it back to the session when the scope
    closes, so it is still reported there.
    """
    return Counter(
        str(warning.message)
        for warning in captured
        if not issubclass(warning.category, ResourceWarning)
    )


def await_client_warnings(
    captured: pytest.WarningsRecorder, expected: list[str]
) -> None:
    """Assert exact warnings while the caller's pytest.warns scope stays active.

    Qdrant starts its compatibility probe on a daemon thread without retaining
    its handle. Construction can return before a refused connection warns, so
    the capture must stay active until that real probe answers. No SDK checks
    are disabled and unexpected warnings remain errors under strict pytest.

    The wait ends when every expected message has arrived, not when that many
    warnings have: counting any warning let an unrelated one end the wait
    before the probe answered, and the comparison then ran without it.
    """
    wanted = Counter(expected)
    deadline = time.monotonic() + PROCESS_TIMEOUT_SECONDS
    while wanted - _client_warnings(captured) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _client_warnings(captured) == wanted
