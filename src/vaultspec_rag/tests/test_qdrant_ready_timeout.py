"""Unit tests for the env-overridable qdrant readiness timeout.

Pure env-parsing logic: no GPU, no server. The env var is set and
restored directly (no monkeypatch), matching the project's isolation
idiom.
"""

from __future__ import annotations

import os

import pytest

from ..qdrant_runtime._supervise import (
    _READY_TIMEOUT_DEFAULT_SECONDS,
    _READY_TIMEOUT_ENV,
    _ready_timeout_seconds,
)

pytestmark = [pytest.mark.unit]


def _set(value: str | None) -> str | None:
    prev = os.environ.get(_READY_TIMEOUT_ENV)
    if value is None:
        os.environ.pop(_READY_TIMEOUT_ENV, None)
    else:
        os.environ[_READY_TIMEOUT_ENV] = value
    return prev


def _restore(prev: str | None) -> None:
    if prev is None:
        os.environ.pop(_READY_TIMEOUT_ENV, None)
    else:
        os.environ[_READY_TIMEOUT_ENV] = prev


def test_default_when_unset() -> None:
    prev = _set(None)
    try:
        assert _ready_timeout_seconds() == _READY_TIMEOUT_DEFAULT_SECONDS
    finally:
        _restore(prev)


def test_env_override_is_honoured() -> None:
    prev = _set("600")
    try:
        assert _ready_timeout_seconds() == 600.0
    finally:
        _restore(prev)


def test_malformed_falls_back_to_default() -> None:
    prev = _set("not-a-number")
    try:
        assert _ready_timeout_seconds() == _READY_TIMEOUT_DEFAULT_SECONDS
    finally:
        _restore(prev)


def test_non_positive_falls_back_to_default() -> None:
    prev = _set("0")
    try:
        assert _ready_timeout_seconds() == _READY_TIMEOUT_DEFAULT_SECONDS
    finally:
        _restore(prev)


def test_default_is_generous_for_large_stores() -> None:
    # A ~131s measured cold-load must sit comfortably under the default.
    assert _READY_TIMEOUT_DEFAULT_SECONDS >= 180.0
