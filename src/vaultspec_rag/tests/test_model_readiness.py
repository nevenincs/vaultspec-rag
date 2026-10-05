"""Tests for how the model snapshots are reported, at each depth of check.

Two surfaces answer "are the models there", and they must not be confused.
The cheap one lists files and reads none, so it may say a model is present
and may never say it is verified. The deep one, which the health command
runs, hashes every file of a pinned model, and is the only one entitled to
the word.

Both report each model as pinned or unpinned: whether file digests are
committed for that repository at the commit it is used at. That is a fact
about the model, not about any check, so it is the same at both depths.

A cache directory this file owns, real files in the hub client's layout, the
real probe and the real check.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import pytest

from .._model_pins import DENSE_MODEL_ID, DENSE_MODEL_REVISION, committed_manifest
from .._readiness import ReadinessStatus, compute_readiness
from ..config._types import EnvVar
from ._config_fixtures import reset_config
from ._model_cache_seed import (
    ORDINARY_FILES,
    STAND_IN_DENSE,
    STAND_IN_RERANKER,
    point_hub_cache,
    seed_model_cache,
    seed_snapshot,
)
from ._scaffold import restore_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .._readiness import DependencyReadiness

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_status_dir")]

_MODEL_VARS = (
    EnvVar.EMBEDDING_MODEL,
    EnvVar.EMBEDDING_MODEL_REVISION,
    EnvVar.RERANKER_MODEL,
    EnvVar.RERANKER_MODEL_REVISION,
    EnvVar.SPARSE_ENABLED,
)


@pytest.fixture
def clean_models() -> Iterator[None]:
    """Run from an environment that names no model and no commit."""
    saved = {var: os.environ.pop(var.value, None) for var in _MODEL_VARS}
    reset_config()
    try:
        yield
    finally:
        for var, previous in saved.items():
            restore_env(var, previous)
        reset_config()


def _models(*, verify: bool) -> DependencyReadiness:
    node = compute_readiness(verify_models=verify).dimension("models")
    assert node is not None
    return node


@pytest.mark.usefixtures("clean_models")
def test_models_an_operator_named_are_present_and_reported_unpinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Present at both depths, and called unpinned at both.

    Nothing vouches for their content, so even the deep check, which finds
    nothing wrong, counts none of them as verified.
    """
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")

    for verify in (False, True):
        node = _models(verify=verify)
        assert node.status is ReadinessStatus.READY
        assert node.info["pinned"] == {STAND_IN_DENSE: False, STAND_IN_RERANKER: False}
        assert f"unpinned: {STAND_IN_DENSE}, {STAND_IN_RERANKER}" in node.detail
    assert "0 verified against committed digests" in _models(verify=True).detail


@pytest.mark.usefixtures("clean_models")
def test_a_pinned_model_with_other_bytes_is_present_but_fails_the_deep_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The gap between the two depths, on one snapshot.

    The cache holds every file of the pinned dense release, by name, with
    other content. The cheap surface reads nothing: it finds the model
    present, and does not use the word verified. The deep one hashes, refuses
    the model, and names a file.

    Mutations. With the cheap surface made to say "verified", the wording
    assertion failed. With the deep check reduced to the file listing, the
    model read as ready and the status assertion failed. Restored after each,
    it passed.
    """
    cache = point_hub_cache(monkeypatch, tmp_path / "hf-cache")
    monkeypatch.setenv(EnvVar.RERANKER_MODEL.value, STAND_IN_RERANKER)
    monkeypatch.setenv(EnvVar.SPARSE_ENABLED.value, "0")
    manifest = committed_manifest(DENSE_MODEL_ID, DENSE_MODEL_REVISION)
    assert manifest is not None
    seed_snapshot(
        cache,
        DENSE_MODEL_ID,
        DENSE_MODEL_REVISION,
        dict.fromkeys(manifest, b"not the release"),
    )
    seed_snapshot(cache, STAND_IN_RERANKER, "0" * 40, ORDINARY_FILES)

    cheap = _models(verify=False)
    assert cheap.status is ReadinessStatus.READY
    assert cheap.info["verified"] is False
    assert "verified" not in cheap.detail
    assert cheap.info["pinned"] == {DENSE_MODEL_ID: True, STAND_IN_RERANKER: False}

    deep = _models(verify=True)
    assert deep.status is ReadinessStatus.NOT_READY
    assert deep.info["verified"] is True
    repos = cast("dict[str, bool]", deep.info["repos"])
    assert repos == {DENSE_MODEL_ID: False, STAND_IN_RERANKER: True}
    assert DENSE_MODEL_ID in deep.detail
    assert "does not match the SHA256 committed for the pinned release" in deep.detail
    assert "vaultspec-rag server warmup" in deep.detail


@pytest.mark.usefixtures("clean_models")
def test_a_missing_model_is_named_as_missing_at_both_depths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed_model_cache(monkeypatch, tmp_path / "hf-cache", missing=[STAND_IN_DENSE])

    cheap = _models(verify=False)
    assert cheap.status is ReadinessStatus.NOT_READY
    assert STAND_IN_DENSE in cheap.detail and "missing from the cache" in cheap.detail

    deep = _models(verify=True)
    assert deep.status is ReadinessStatus.NOT_READY
    assert STAND_IN_DENSE in deep.detail


@pytest.mark.usefixtures("clean_models")
def test_the_commit_each_model_is_used_at_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A model nothing pins reports no commit, instead of an invented one."""
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")

    assert _models(verify=False).info["revisions"] == {
        STAND_IN_DENSE: None,
        STAND_IN_RERANKER: None,
    }
