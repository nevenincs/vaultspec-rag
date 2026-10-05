"""Tests for the committed model pins and the settings that sit over them.

Two things are pinned for each default model: the commit it is fetched and
loaded at, and the digest of every file that commit holds. A commit alone is
a name the hub resolves; the digests are what make the pin checkable. These
tests hold the table to the shape the snapshot check relies on, and hold the
settings to the rule that configuration may move a commit but can never
manufacture a pin: a model is pinned only when a committed table covers that
repository at exactly that commit.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import pytest

from .._model_pins import (
    DENSE_MODEL_ID,
    DENSE_MODEL_REVISION,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    committed_manifest,
    committed_revision,
)
from .._sparse_profile import SPARSE_MODEL_ID, SPARSE_MODEL_REVISION
from ..config._registry import entry
from ..config._settings import (
    collect_environment_problems,
    configured_model_repos,
    dense_model_repo,
    rag_default,
    reranker_model_repo,
    sparse_model_repo,
)
from ..config._types import EnvVar
from ._config_fixtures import reset_config
from ._scaffold import restore_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

_DEFAULTS = (
    (DENSE_MODEL_ID, DENSE_MODEL_REVISION),
    (SPARSE_MODEL_ID, SPARSE_MODEL_REVISION),
    (RERANKER_MODEL_ID, RERANKER_MODEL_REVISION),
)
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OTHER_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_OPERATOR_REPO = "example-org/operator-model"

#: Every variable that names a model or the commit it is used at.
_MODEL_VARS = (
    EnvVar.EMBEDDING_MODEL,
    EnvVar.EMBEDDING_MODEL_REVISION,
    EnvVar.SPARSE_MODEL,
    EnvVar.RERANKER_MODEL,
    EnvVar.RERANKER_MODEL_REVISION,
    EnvVar.SPARSE_ENABLED,
)

_COMMIT_SHAPE = "a full commit id of 40 hexadecimal characters"


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


def _configure(**values: str) -> None:
    for name, value in values.items():
        os.environ[EnvVar[name].value] = value
    reset_config()


@pytest.mark.parametrize(("repo", "revision"), _DEFAULTS, ids=lambda v: str(v)[:24])
def test_every_default_model_has_a_commit_and_a_table_for_it(
    repo: str, revision: str
) -> None:
    """A default model with no table could never be checked, only trusted.

    Mutation: with one model's entry removed from the table of manifests this
    failed for that model on the first assertion; restored, it passed.
    """
    manifest = committed_manifest(repo, revision)

    assert manifest is not None
    assert committed_revision(repo) == revision
    assert _COMMIT.fullmatch(revision)
    assert all(_SHA256.fullmatch(digest) for digest in manifest.values())
    assert "config.json" in manifest


@pytest.mark.parametrize(("repo", "revision"), _DEFAULTS, ids=lambda v: str(v)[:24])
def test_a_default_models_files_are_safe_to_resolve_and_to_load(
    repo: str, revision: str
) -> None:
    """Names stay inside the snapshot, and the weights are safetensors.

    A name with a parent step would be read from outside the directory that
    was checked. A pickle weight file in the table would make the table
    vouch for something that is never loaded, or worse, invite loading it.
    """
    manifest = committed_manifest(repo, revision)
    assert manifest is not None

    for name in manifest:
        parts = name.split("/")
        assert name == name.strip() and "\\" not in name
        assert ".." not in parts and "" not in parts
    assert any(name.endswith(".safetensors") for name in manifest)
    assert not [
        name for name in manifest if name.endswith((".bin", ".pt", ".pkl", ".ckpt"))
    ]


def test_the_sparse_table_covers_the_code_that_builds_the_model() -> None:
    """The one source file a default model executes has a committed digest."""
    manifest = committed_manifest(SPARSE_MODEL_ID, SPARSE_MODEL_REVISION)

    assert manifest is not None
    assert "modeling_splade.py" in manifest


def test_no_table_answers_for_another_commit_or_another_repository() -> None:
    """A table describes one commit. Asked about any other, there is none.

    Mutation: with the table looked up by repository alone, a default model
    at another commit was handed the pinned commit's table and the first
    assertion failed; restored, it passed.
    """
    assert committed_manifest(DENSE_MODEL_ID, _OTHER_COMMIT) is None
    assert committed_manifest(DENSE_MODEL_ID, None) is None
    assert committed_manifest(_OPERATOR_REPO, DENSE_MODEL_REVISION) is None
    assert committed_revision(_OPERATOR_REPO) is None


def test_the_shipped_model_settings_name_the_pinned_repositories() -> None:
    """The defaults and the pins are one list, so neither can drift."""
    assert rag_default("embedding_model") == DENSE_MODEL_ID
    assert rag_default("sparse_model") == SPARSE_MODEL_ID
    assert rag_default("reranker_model") == RERANKER_MODEL_ID
    assert rag_default("embedding_model_revision") is None
    assert rag_default("reranker_model_revision") is None


@pytest.mark.usefixtures("clean_models")
def test_unconfigured_every_model_is_at_its_committed_commit_and_pinned() -> None:
    models = configured_model_repos()

    assert [(m.repo, m.revision, m.pinned) for m in models] == [
        (repo, revision, True) for repo, revision in _DEFAULTS
    ]


@pytest.mark.usefixtures("clean_models")
def test_a_model_the_operator_names_has_no_commit_and_is_not_pinned() -> None:
    """Nothing is invented for it: no commit, and no claim that it is pinned.

    It is still listed, so it is still fetched and loaded, from the hub's
    default branch.
    """
    _configure(EMBEDDING_MODEL=_OPERATOR_REPO)

    dense = dense_model_repo()

    assert (dense.repo, dense.revision, dense.pinned) == (_OPERATOR_REPO, None, False)
    assert reranker_model_repo().pinned


@pytest.mark.usefixtures("clean_models")
def test_a_commit_the_operator_names_is_used_and_is_not_pinned() -> None:
    """A configured commit is honoured, normalised, and never called pinned.

    This holds for a default repository too: moved to another commit it has
    no table. Mutation: with ``pinned`` decided by the repository alone, the
    default repository at another commit read as pinned and this failed;
    restored, it passed.
    """
    _configure(
        EMBEDDING_MODEL=_OPERATOR_REPO,
        EMBEDDING_MODEL_REVISION=f"  {_OTHER_COMMIT.upper()} ",
        RERANKER_MODEL_REVISION=_OTHER_COMMIT,
    )

    dense = dense_model_repo()
    reranker = reranker_model_repo()

    assert (dense.revision, dense.pinned) == (_OTHER_COMMIT, False)
    assert (reranker.repo, reranker.revision, reranker.pinned) == (
        RERANKER_MODEL_ID,
        _OTHER_COMMIT,
        False,
    )


@pytest.mark.usefixtures("clean_models")
def test_the_committed_commit_named_explicitly_is_still_pinned() -> None:
    _configure(EMBEDDING_MODEL_REVISION=DENSE_MODEL_REVISION)

    assert dense_model_repo().pinned


@pytest.mark.usefixtures("clean_models")
def test_a_configured_commit_belongs_to_the_configured_repository() -> None:
    """A caller that names another repository does not inherit the commit."""
    _configure(EMBEDDING_MODEL_REVISION=_OTHER_COMMIT)

    other = dense_model_repo(_OPERATOR_REPO)

    assert (other.repo, other.revision, other.pinned) == (_OPERATOR_REPO, None, False)


@pytest.mark.parametrize(
    "raw",
    ["main", "v1.0", _OTHER_COMMIT[:7], _OTHER_COMMIT + "0", "g" + _OTHER_COMMIT[1:]],
    ids=["branch", "tag", "short-commit", "too-long", "not-hex"],
)
@pytest.mark.parametrize(
    "var",
    [EnvVar.EMBEDDING_MODEL_REVISION, EnvVar.RERANKER_MODEL_REVISION],
    ids=lambda v: v.name,
)
@pytest.mark.usefixtures("clean_models")
def test_a_revision_that_is_not_a_full_commit_is_refused(var: EnvVar, raw: str) -> None:
    """A branch or a tag is a name that moves, so it cannot be a revision here.

    Admitting one would let configuration unpin a model while looking as if
    it pinned it. Mutation: with the revision's declared shape removed from
    the bounds table every case failed on the problem count (0 in place of
    1); restored, all passed.
    """
    os.environ[var.value] = raw
    reset_config()

    problems = collect_environment_problems(None)

    assert len(problems) == 1
    assert var.value in problems[0]
    assert _COMMIT_SHAPE in problems[0]


def test_the_sparse_model_has_no_revision_setting() -> None:
    """Its repository ships code, so its commit is not the environment's to move.

    The other two models' repositories ship weights and configuration only.
    Mutation: with a sparse revision variable added to the settings enum this
    failed naming it; restored, it passed.
    """
    revisions = sorted(var.name for var in EnvVar if var.name.endswith("_REVISION"))

    assert revisions == ["EMBEDDING_MODEL_REVISION", "RERANKER_MODEL_REVISION"]
    assert sparse_model_repo().revision in {SPARSE_MODEL_REVISION, None}


@pytest.mark.parametrize(
    "var",
    [EnvVar.EMBEDDING_MODEL_REVISION, EnvVar.RERANKER_MODEL_REVISION],
    ids=lambda v: v.name,
)
def test_a_revision_cannot_be_supplied_by_a_workspace_file(var: EnvVar) -> None:
    """A project may not choose which commit of a model a host loads."""
    declared = entry(var)

    assert not declared.workspace_dotenv
    assert not declared.persistable
    assert not declared.secret
