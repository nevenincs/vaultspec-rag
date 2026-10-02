"""Wait for the real SDK's asynchronous refused-endpoint warning in tests."""

from __future__ import annotations

import time
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

VERSION_WARNING = (
    "Failed to obtain server version. Unable to check client-server compatibility. "
    "Set check_compatibility=False to skip version check."
)
INSECURE_KEY_WARNING = "Api key is used with an insecure connection."


def await_client_warnings(
    captured: pytest.WarningsRecorder, expected: list[str]
) -> None:
    """Assert exact warnings while the caller's pytest.warns scope stays active.

    Qdrant starts its compatibility probe on a daemon thread without retaining
    its handle. Construction can return before a refused connection warns, so
    the capture must stay active until that real probe answers. No SDK checks
    are disabled and unexpected warnings remain errors under strict pytest.
    """
    deadline = time.monotonic() + 10.0
    while len(captured) < len(expected) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert Counter(str(warning.message) for warning in captured) == Counter(expected)
