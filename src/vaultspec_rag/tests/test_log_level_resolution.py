"""The configured log level, and what an unusable one does.

An unrecognised level name used to degrade to the shipped default. That was
chosen over degrading to something noisier, which is the worse of the two -
an operator who mistypes a level and then sees MORE output reads it as a
behaviour change somewhere else and goes looking in the wrong place - but
both are wrong, and for the same reason: neither tells the operator the
value was rejected. Quiet, they never get the diagnostics they asked for;
loud, they chase output they did not ask for. So the name is refused.

Blank is a different case and keeps its old answer. It is not a typo, it is
an unexpanded variable, and unset is what it means everywhere else.
"""

from __future__ import annotations

import logging
import os

import pytest
from vaultspec_core.config import ConfigurationError
from vaultspec_core.logging_config import reset_logging

from ..config._settings import rag_default, reset_config
from ..config._types import EnvVar
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
        reset_config()
        reset_logging()
        configure_logging()
        return logging.getLogger().level
    finally:
        if previous is None:
            os.environ.pop(EnvVar.LOG_LEVEL.value, None)
        else:
            os.environ[EnvVar.LOG_LEVEL.value] = previous
        reset_config()
        reset_logging()
        logging.getLogger().setLevel(logging.WARNING)


def test_unset_resolves_to_the_shipped_default() -> None:
    expected = getattr(logging, str(rag_default("log_level")).upper())
    assert _resolve_root_level(None) == expected


@pytest.mark.parametrize("name", ["ERROR", "DEBUG", "INFO", "CRITICAL"])
def test_a_recognised_level_is_honoured(name: str) -> None:
    assert _resolve_root_level(name) == getattr(logging, name)


@pytest.mark.parametrize("name", ["error", "Debug"])
def test_a_level_name_is_not_case_sensitive(name: str) -> None:
    assert _resolve_root_level(name) == getattr(logging, name.upper())


@pytest.mark.parametrize("bad", ["WARNIGN", "verbose", "17"])
def test_an_unusable_level_is_refused_rather_than_guessed_at(bad: str) -> None:
    """The refusal names the variable and the value, so it is fixable.

    Degrading hid the mistake behind whichever behaviour the guess produced.
    Quieter than asked and the diagnostics the operator wanted never arrive;
    louder and the new output reads as something else changing. Neither says
    the level was rejected, which is the one thing that would have helped.
    """
    with pytest.raises(ConfigurationError) as refusal:
        _resolve_root_level(bad)

    assert EnvVar.LOG_LEVEL.value in str(refusal.value)
    assert bad in str(refusal.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_level_is_unset_and_takes_the_default(blank: str) -> None:
    """The unexpanded-variable case an operator actually hits.

    Blank is not a mistyped level, it is no level, and unset is what it
    means for every other value this project reads. Refusing it would turn
    a deployment template with one unfilled slot into a process that will
    not start.
    """
    default = getattr(logging, str(rag_default("log_level")).upper())

    assert _resolve_root_level(blank) == default
