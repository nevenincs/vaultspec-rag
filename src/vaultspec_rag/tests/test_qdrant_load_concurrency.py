"""Collection loading policy reaches the managed child's native configuration.

Mutation proof: removing the numeric bound failed the rejection assertions;
forcing native concurrency to one failed the default-two assertion. Both
mutations were process-local; restoring production behavior passed all cases.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ..config._settings import get_config
from ..config._types import EnvVar
from ..qdrant_runtime._supervise import QdrantSupervisor
from ._config_fixtures import reset_config
from ._scaffold import restore_env, set_env

pytestmark = [pytest.mark.unit]

_NATIVE_KEY = "QDRANT__STORAGE__PERFORMANCE__MAX_CONCURRENT_COLLECTION_LOADS"
_SETTING = "qdrant_collection_load_concurrency"
_VARIABLE = EnvVar.QDRANT_COLLECTION_LOAD_CONCURRENCY


@pytest.mark.parametrize(("raw", "expected"), [(None, "2"), ("1", "1"), ("4", "4")])
def test_managed_child_load_concurrency(raw: str | None, expected: str) -> None:
    previous = os.environ.pop(_VARIABLE.value, None)
    native_previous = os.environ.get(_NATIVE_KEY)
    os.environ[_NATIVE_KEY] = "99"
    if raw is not None:
        os.environ[_VARIABLE.value] = raw
    reset_config()
    try:
        supervisor = QdrantSupervisor(
            Path("qdrant"), http_port=6333, storage_dir=Path("unused-storage")
        )
        # Dropping the explicit native mapping or inheriting arbitrary QDRANT
        # overrides must fail this assertion. No process or storage is opened.
        assert supervisor._child_env()[_NATIVE_KEY] == expected
    finally:
        restore_env(_VARIABLE, previous)
        if native_previous is None:
            os.environ.pop(_NATIVE_KEY, None)
        else:
            os.environ[_NATIVE_KEY] = native_previous
        reset_config()


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "true", "invalid"])
def test_invalid_environment_load_concurrency_is_rejected(raw: str) -> None:
    previous = set_env(_VARIABLE, raw)
    reset_config()
    try:
        with pytest.raises(
            ValueError,
            match=r"VAULTSPEC_RAG_QDRANT_COLLECTION_LOAD_CONCURRENCY.*positive integer",
        ):
            get_config()
    finally:
        restore_env(_VARIABLE, previous)
        reset_config()


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_explicit_load_concurrency_is_rejected(value: object) -> None:
    # Removing this setting's positive-integer bound makes these fail with
    # DID NOT RAISE, including bool (an int subclass).
    try:
        with pytest.raises(ValueError, match=f"{_SETTING}.*positive integer"):
            get_config({_SETTING: value})
    finally:
        reset_config()


def test_explicit_load_concurrency_reaches_child() -> None:
    previous = set_env(_VARIABLE, "1")
    try:
        get_config({_SETTING: 4})
        supervisor = QdrantSupervisor(
            Path("qdrant"), http_port=6333, storage_dir=Path("unused-storage")
        )
        assert supervisor._child_env()[_NATIVE_KEY] == "4"
    finally:
        restore_env(_VARIABLE, previous)
        reset_config()
