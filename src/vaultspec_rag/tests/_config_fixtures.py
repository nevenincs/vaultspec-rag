"""Settings-cache control for tests.

Production builds the settings object once per process and never rebuilds
it. A test that changes the environment has to, so the reset lives here.
"""

from __future__ import annotations

from ..config import _settings


def reset_config() -> None:
    """Drop the cached settings object so the next read rebuilds it."""
    _settings._cached_config = None
