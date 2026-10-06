"""The bounds on a model fetch that the progress floor does not provide.

The floor stops a download that receives too little. It does not bound a
fetch as a whole: a hub that keeps sending just enough is never stopped by
it, and a fetch of three repositories that each waited out a full allowance
for another process waited three times as long as anyone was told. And when
what failed was a file on this machine, the remedy that sends an operator to
check the network is the wrong one.

The whole fetch runs in a fresh interpreter against a loopback hub, with the
time allowed for it set the way an operator sets it.
"""

from __future__ import annotations

import errno
from typing import TYPE_CHECKING, cast

import pytest

from .._anchor_claim import claim_anchor, release_anchor_claim
from ..commands._hub_failure import HubFailure, classify_hub_failure
from ..commands._model_fetch import (
    MODELS_BUSY,
    MODELS_CACHE_UNUSABLE,
    MODELS_DEADLINE,
)
from ..config._types import EnvVar
from ._loopback_model_hub import LoopbackModelHub, loopback_model_hub
from ._loopback_tls import plain_loopback_sources, stay_silent
from ._model_fetch_child import DENSE_REPO, RERANKER_REPO, fetch_from

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]

_DEADLINE = EnvVar.MODEL_FETCH_DEADLINE_SECONDS.value


def test_a_fetch_that_outlasts_its_allowance_is_stopped_whatever_it_receives(
    tmp_path: Path,
) -> None:
    """The whole fetch has an end, and what it had not reached is said so.

    The hub accepts every request and answers none. The hub client's own
    timeouts are raised to twenty seconds and the floor does not open its
    first window for a minute, so with three seconds allowed for the fetch
    nothing else can end it first. The first repository's download is
    stopped; the second is never started.

    Mutation check: with the allowance no longer checked while a download
    runs, the download outlives it, the hub client gives up after its own
    twenty seconds, and the first ``repos`` assertion fails with
    ``models_fetch_failed``. Restoring the check passes.
    """
    cache = tmp_path / "hub-cache"
    with plain_loopback_sources() as sources:
        hub = LoopbackModelHub(
            repos=(), endpoint=sources.serve(stay_silent, tls=False).url()
        )
        outcome, _progress = fetch_from(
            hub,
            cache,
            {
                _DEADLINE: "3",
                EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value: "20",
                "HF_HUB_ETAG_TIMEOUT": "20",
            },
        )

    assert outcome["repos"] == [
        [DENSE_REPO, "failed", MODELS_DEADLINE],
        [RERANKER_REPO, "failed", MODELS_DEADLINE],
    ]
    assert outcome["code"] == MODELS_DEADLINE
    details = cast("list[str]", outcome["details"])
    assert "the time allowed for the whole fetch ran out" in details[0]
    assert "was not fetched: the 3 seconds allowed" in details[1]
    remedy = str(outcome["detail"])
    assert _DEADLINE in remedy
    assert "vaultspec-rag server warmup" in remedy
    assert outcome["processes_left"] == []
    assert list(cache.rglob("*.incomplete")) == []


def test_the_wait_for_another_fetch_is_one_allowance_for_every_repository(
    tmp_path: Path,
) -> None:
    """A fetch that waited the allowance out does not wait it out again.

    The cache is held for the whole run. The first repository waits and is
    answered busy; the second finds the allowance already spent and is
    answered at once, so the wait is announced once.

    Mutation check: with the wait counted from each repository's own start,
    the second repository waits a second time and announces it, and the
    count assertion fails with two. Restoring the shared start passes.
    """
    cache = tmp_path / "hub-cache"
    held = claim_anchor(
        cache / ".locks" / "vaultspec-rag-fetch.lock",
        pid_record=True,
        create_parent=True,
    )
    assert held.descriptor is not None, "premise: this test holds the cache"
    try:
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            outcome, progress = fetch_from(hub, cache, {"TEST_FETCH_CONTENTION": "2"})

            assert hub.requests == [], "the hub was asked while the cache was held"
    finally:
        release_anchor_claim(held.descriptor, pid_record=True)

    assert outcome["repos"] == [
        [DENSE_REPO, "failed", MODELS_BUSY],
        [RERANKER_REPO, "failed", MODELS_BUSY],
    ]
    assert progress.count("to finish downloading models") == 1, progress


def test_a_cache_that_cannot_be_written_is_not_blamed_on_the_network(
    tmp_path: Path,
) -> None:
    """A file where the repository's directory belongs stops the download.

    The hub is healthy and is asked. What fails is this machine's cache, so
    the failure carries its own code and its remedy is the cache directory.

    Mutation check: with a failed file operation no longer told apart from a
    failed request, the repository fails as ``models_fetch_failed`` and the
    operator is sent to check a network that works; the first ``repos``
    assertion fails with that code. Restoring the rule passes.
    """
    cache = tmp_path / "hub-cache"
    cache.mkdir()
    (cache / f"models--{DENSE_REPO.replace('/', '--')}").write_bytes(b"not a directory")

    with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
        outcome, _progress = fetch_from(hub, cache)

    assert outcome["repos"] == [
        [DENSE_REPO, "failed", MODELS_CACHE_UNUSABLE],
        [RERANKER_REPO, "created", ""],
    ]
    detail = str(outcome["detail"])
    assert "could not be stored in the model cache" in detail
    assert str(cache) in detail
    assert EnvVar.HF_HOME.value in detail
    assert "Check network access" not in detail


def test_only_an_error_that_names_a_file_is_a_cache_fault() -> None:
    """A refused connection can carry a permission error number and no file.

    A firewall that blocks a socket raises the same error number as a
    directory that may not be written, so the number cannot tell the two
    apart; the file name can. Out of space keeps its own answer.
    """
    in_the_cache = PermissionError(errno.EACCES, "denied", "/cache/blobs/x")
    wrapped = RuntimeError("download failed")
    wrapped.__cause__ = in_the_cache
    blocked_socket = PermissionError(errno.EACCES, "an attempt was made to connect")
    full = OSError(errno.ENOSPC, "no space left on device", "/cache/blobs/x")

    assert classify_hub_failure(in_the_cache) is HubFailure.CACHE
    assert classify_hub_failure(wrapped) is HubFailure.CACHE
    assert classify_hub_failure(blocked_socket) is HubFailure.UNREACHABLE
    assert classify_hub_failure(full) is HubFailure.NO_SPACE
