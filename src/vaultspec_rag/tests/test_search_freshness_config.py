"""CPU-only configuration contracts for bounded search freshness waits."""

from __future__ import annotations

import os

import pytest

from ..config._settings import get_config, reset_config
from ..config._types import EnvVar
from ._scaffold import restore_env, set_env

pytestmark = [pytest.mark.unit]


def test_search_freshness_wait_max_default_and_settings_projection() -> None:
    previous = os.environ.pop(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS.value, None)
    try:
        reset_config()
        assert get_config().search_freshness_wait_max_seconds == 30.0
    finally:
        restore_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, previous)
        reset_config()


def test_search_freshness_wait_max_environment_and_explicit_override() -> None:
    # Removing explicit precedence returned 12.5 and failed the 18.25 assertion.
    previous = set_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, "12.5")
    try:
        reset_config()
        assert get_config().search_freshness_wait_max_seconds == 12.5
        configured = get_config({"search_freshness_wait_max_seconds": 18.25})
        assert configured.search_freshness_wait_max_seconds == 18.25
    finally:
        restore_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, previous)
        reset_config()


@pytest.mark.parametrize("value", [0, 300])
def test_search_freshness_wait_max_accepts_closed_boundaries(value: int) -> None:
    configured = get_config({"search_freshness_wait_max_seconds": value})
    assert configured.search_freshness_wait_max_seconds == float(value)
    reset_config()


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        (-0.01, "-0.01"),
        (300.01, "300.01"),
        (True, "True"),
        (float("inf"), "inf"),
        (float("nan"), "nan"),
        ("not-a-number", "'not-a-number'"),
    ],
)
def test_search_freshness_wait_max_rejects_invalid_explicit_values(
    value: object, rendered: str
) -> None:
    expected = (
        "search_freshness_wait_max_seconds must be a finite number between "
        f"0 and 300, got {rendered}"
    )
    reset_config()
    try:
        with pytest.raises(ValueError) as excinfo:
            get_config({"search_freshness_wait_max_seconds": value})
        assert str(excinfo.value) == expected
    finally:
        reset_config()


def test_search_freshness_wait_max_rejects_malformed_environment_exactly() -> None:
    previous = set_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, "not-a-number")
    try:
        reset_config()
        expected = (
            "VAULTSPEC_RAG_SEARCH_FRESHNESS_WAIT_MAX_SECONDS "
            "(search_freshness_wait_max_seconds) must be a finite number between "
            "0 and 300, got 'not-a-number'"
        )
        with pytest.raises(ValueError) as excinfo:
            get_config()
        assert str(excinfo.value) == expected
    finally:
        restore_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, previous)
        reset_config()


@pytest.mark.parametrize(
    ("raw", "rendered"),
    [("-0.01", "-0.01"), ("300.01", "300.01"), ("inf", "inf")],
)
def test_search_freshness_wait_max_rejects_out_of_range_environment_exactly(
    raw: str, rendered: str
) -> None:
    previous = set_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, raw)
    try:
        reset_config()
        expected = (
            "VAULTSPEC_RAG_SEARCH_FRESHNESS_WAIT_MAX_SECONDS "
            "(search_freshness_wait_max_seconds) must be a finite number between "
            f"0 and 300, got {rendered}"
        )
        with pytest.raises(ValueError) as excinfo:
            get_config()
        assert str(excinfo.value) == expected
    finally:
        restore_env(EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS, previous)
        reset_config()
