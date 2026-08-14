"""Search timeout resolution tests with no CLI or service-process dependency."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from ..serviceclient._search_transport import get_search_timeout
from ..serviceclient._transport import (
    DEFAULT_ADMIN_TIMEOUT_SECONDS,
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _get_admin_timeout,
)

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from collections.abc import Generator

_ENV_NAME = "VAULTSPEC_RAG_SEARCH_TIMEOUT"
_ADMIN_ENV_NAME = "VAULTSPEC_RAG_ADMIN_TIMEOUT"


@contextmanager
def _search_timeout_env(value: str | None) -> Generator[None]:
    previous = os.environ.get(_ENV_NAME)
    if value is None:
        os.environ.pop(_ENV_NAME, None)
    else:
        os.environ[_ENV_NAME] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_ENV_NAME, None)
        else:
            os.environ[_ENV_NAME] = previous


@contextmanager
def _admin_timeout_env(value: str | None) -> Generator[None]:
    previous = os.environ.get(_ADMIN_ENV_NAME)
    if value is None:
        os.environ.pop(_ADMIN_ENV_NAME, None)
    else:
        os.environ[_ADMIN_ENV_NAME] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_ADMIN_ENV_NAME, None)
        else:
            os.environ[_ADMIN_ENV_NAME] = previous


def test_default_search_timeout_is_production_budget() -> None:
    with _search_timeout_env(None):
        assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["not-a-number", "", "   "])
def test_invalid_env_timeout_uses_production_budget(env_timeout: str) -> None:
    # The settings lookup coerces and RAISES on any of these; the resolver
    # catches that so an operator typo degrades to the budget instead of
    # turning every search into a crash. Drop the catch and these fail with
    # ValueError, not an assertion.
    with _search_timeout_env(env_timeout):
        assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["0", "-1", "nan", "inf", "-inf"])
def test_non_positive_or_non_finite_env_timeout_uses_production_budget(
    env_timeout: str,
) -> None:
    with _search_timeout_env(env_timeout):
        assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_explicit_timeout_uses_production_budget(
    timeout: float,
) -> None:
    assert get_search_timeout(timeout) == DEFAULT_SEARCH_TIMEOUT_SECONDS


def test_explicit_timeout_still_wins() -> None:
    assert get_search_timeout(0.25) == 0.25


def test_default_admin_timeout_is_bounded() -> None:
    with _admin_timeout_env(None):
        assert _get_admin_timeout(None) == DEFAULT_ADMIN_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["0", "-1", "nan", "inf", "-inf"])
def test_non_positive_or_non_finite_admin_env_uses_default(
    env_timeout: str,
) -> None:
    with _admin_timeout_env(env_timeout):
        assert _get_admin_timeout(None) == DEFAULT_ADMIN_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["not-a-number", "", "   "])
def test_invalid_admin_env_timeout_uses_default(env_timeout: str) -> None:
    # As above: the settings lookup raises on these, and the catch is what
    # keeps a lifecycle verb emitting one envelope instead of a traceback.
    with _admin_timeout_env(env_timeout):
        assert _get_admin_timeout(None) == DEFAULT_ADMIN_TIMEOUT_SECONDS


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_explicit_admin_timeout_uses_default(
    timeout: float,
) -> None:
    assert _get_admin_timeout(timeout) == DEFAULT_ADMIN_TIMEOUT_SECONDS


def test_finite_positive_admin_timeout_still_wins() -> None:
    with _admin_timeout_env("0.75"):
        assert _get_admin_timeout(None) == 0.75
    assert _get_admin_timeout(0.25) == 0.25
