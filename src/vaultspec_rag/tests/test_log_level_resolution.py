"""The configured log level, and what an unusable one degrades to.

An unrecognised level name must not make the process noisier than the
default it falls back to. That direction matters: an operator who mistypes
a level and then sees MORE output reads it as a behaviour change somewhere
else, and goes looking in the wrong place.
"""

from __future__ import annotations

import logging
import os

import pytest

from ..config import EnvVar, rag_default
from vaultspec_core.logging_config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    reset_logging,
)

from ..logging_config import configure_logging

pytestmark = [pytest.mark.unit]


def _resolve_root_level(value: str | None) -> int:
    """Configure logging under *value* and return the resulting root level."""
    previous = os.environ.get(EnvVar.LOG_LEVEL.value)
    if value is None:
        os.environ.pop(EnvVar.LOG_LEVEL.value, None)
    else:
        os.environ[EnvVar.LOG_LEVEL.value] = value
    try:
        from ..config import reset_config

        reset_config()
        reset_logging()
        configure_logging()
        return logging.getLogger().level
    finally:
        if previous is None:
            os.environ.pop(EnvVar.LOG_LEVEL.value, None)
        else:
            os.environ[EnvVar.LOG_LEVEL.value] = previous
        from ..config import reset_config as _reset

        _reset()
        reset_logging()


def test_unset_resolves_to_the_shipped_default() -> None:
    expected = getattr(logging, str(rag_default("log_level")).upper())
    assert _resolve_root_level(None) == expected


@pytest.mark.parametrize("name", ["ERROR", "DEBUG", "INFO", "CRITICAL"])
def test_a_recognised_level_is_honoured(name: str) -> None:
    assert _resolve_root_level(name) == getattr(logging, name)


@pytest.mark.parametrize("bad", ["WARNIGN", "verbose", "17", "", "   "])
def test_an_unusable_level_degrades_to_the_default_never_to_something_noisier(
    bad: str,
) -> None:
    """A typo must not raise the verbosity above the documented default.

    Mutation-proved: restoring the old ``getattr(logging, configured,
    logging.INFO)`` fallback makes this fail on the comparison below for
    every non-empty case, because INFO is numerically below WARNING and so
    emits strictly more. The empty spellings pass either way - the settings
    object treats them as unset - and are kept because they are the
    unexpanded-variable case an operator actually hits.
    """
    default = getattr(logging, str(rag_default("log_level")).upper())
    resolved = _resolve_root_level(bad)
    assert resolved == default
    assert resolved >= default
