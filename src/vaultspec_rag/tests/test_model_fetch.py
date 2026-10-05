"""The one model fetch every command reaches through the provisioning front door.

``install``, ``server warmup`` and the preflight of ``server start`` all ensure
the model files through the same step, so what is proven here holds for all
three: the cache is probed per repository, a missing repository is a preview
under dry-run and a loud failure with the hub offline, every repository is
attempted before the result comes back, and the probe is reported through
whatever sink the command supplied.

The model cache is a directory the test seeds and the product's own probe
reads, with the hub's offline switch set, so no outcome depends on which
weights the host holds and nothing can be downloaded from the real hub.

The download itself is driven for real, against a loopback stand-in hub. The
hub client reads its endpoint and cache location once, at import, so that run
happens in a fresh interpreter started with both in its environment; the fetch
it executes is the shipped one, reporting through the CLI's own sink.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest

from .._anchor_claim import claim_anchor, release_anchor_claim
from .._model_cache import cached_snapshot_is_complete
from .._sync_vocabulary import ProvisionAction
from ..commands._hub_failure import HubFailure, classify_hub_failure
from ..commands._install import install_run
from ..commands._model_download import FetchLimits, _Floor
from ..commands._model_fetch import (
    MODELS_BUSY,
    MODELS_DOWNLOAD_DIED,
    MODELS_FETCH_FAILED,
    MODELS_NO_SPACE,
    MODELS_NOT_FOUND,
    MODELS_OFFLINE,
    MODELS_STALLED,
    MODELS_UNTRUSTED_CERTIFICATE,
)
from ..commands._provision import ProvisionStep, provision_models
from ..config._settings import configured_model_repos
from ..config._types import EnvVar
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from ._cli_helpers import app, runner
from ._loopback_model_hub import (
    WEIGHT_FILE,
    LoopbackModelHub,
    loopback_model_hub,
    weight_bytes,
)
from ._loopback_tls import (
    LOOPBACK_HOST,
    plain_loopback_sources,
    send_then_reset,
    send_trickle,
    stay_silent,
    trusted_loopback_sources,
)
from ._model_cache_seed import seed_model_cache
from ._model_fetch_child import (
    DENSE_REPO,
    FETCH_IN_A_FRESH_INTERPRETER,
    QUICK_TIMEOUTS,
    RERANKER_REPO,
    TIMEOUT_AFTER_A_FETCH,
    child_environment,
    fetch_from,
    reported_outcome,
    run_child,
)
from ._ports import free_loopback_port
from ._provision_fixtures import result_for
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Collection, Generator
    from pathlib import Path

    from ..commands._snapshot_progress import SnapshotCounts
    from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]

_ABSENT_MODEL = "vaultspec-test/absent-dense"

PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


class _RecordingProgress:
    """A sink that keeps what the front door reported, for assertions.

    An implementation of the front door's own reporting protocol, not a
    substitute for anything: the fetch runs unchanged and this is simply where
    it was told to report.
    """

    def __init__(self) -> None:
        self.stages: list[str] = []
        self.downloads: list[str] = []

    def stage(self, label: str) -> None:
        self.stages.append(label)
        if label.startswith("Downloading"):
            self.downloads.append(label)

    def downloading(self, heading: str, counts: SnapshotCounts) -> None:
        del counts
        self.downloads.append(heading)


@pytest.fixture(autouse=True)
def offline_hub() -> Generator[None]:
    """Set the hub's offline switch, so no test here can start a download."""
    with managed_env(**{EnvVar.HF_HUB_OFFLINE.value: "1"}):
        yield


def test_a_fully_cached_inventory_is_unchanged_and_names_every_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")
    inventory = configured_model_repos()
    progress = _RecordingProgress()

    result = provision_models(progress=progress)

    assert result.step == ProvisionStep.MODELS
    assert result.action == ProvisionAction.UNCHANGED
    # The seeded models are ones an operator named, so nothing vouches for
    # their content and every line that lists them says so.
    assert result.detail == (
        f"all {len(inventory)} model repos already cached; unpinned: "
        + ", ".join(model.repo for model in inventory)
    )
    assert [
        (repo.label, repo.repo, repo.detail, repo.pinned) for repo in result.repos
    ] == [(model.label, model.repo, "cached, unpinned", False) for model in inventory]
    assert progress.stages == [
        f"Verifying {model.label} ({position}/{len(inventory)})"
        for position, model in enumerate(inventory, start=1)
    ]
    assert progress.downloads == []


def test_a_missing_repo_with_the_hub_offline_fails_and_names_the_remedy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offline is honoured: a missing model is a failure, not a download.

    The missing repository is the first in the inventory and exists nowhere.
    The later ones are still probed and reported, because a fetch that stopped
    at the first unavailable repository would hide the next.

    Mutation check: with the offline branch removed from the fetch, the hub is
    asked for the repository and the step fails as ``models_fetch_failed`` -
    failing the code assertion, and the download assertion with the heading
    it recorded. Restoring the branch passes.
    """
    progress = _RecordingProgress()
    with managed_env(**{EnvVar.EMBEDDING_MODEL.value: _ABSENT_MODEL}):
        seed_model_cache(monkeypatch, tmp_path / "hf-cache", missing=[_ABSENT_MODEL])
        inventory = configured_model_repos()
        assert inventory[0].repo == _ABSENT_MODEL, "premise: the first repo is absent"

        result = provision_models(progress=progress)

    assert progress.downloads == [], "a download was attempted with the hub offline"
    assert result.action == ProvisionAction.FAILED
    assert result.code == MODELS_OFFLINE
    assert _ABSENT_MODEL in result.detail
    assert EnvVar.HF_HUB_OFFLINE.value in result.detail
    assert "vaultspec-rag server warmup" in result.detail
    assert [repo.action for repo in result.repos] == [
        ProvisionAction.FAILED,
        *[ProvisionAction.UNCHANGED] * (len(inventory) - 1),
    ]


def test_a_missing_repo_under_dry_run_is_previewed_not_fetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    progress = _RecordingProgress()
    with managed_env(**{EnvVar.EMBEDDING_MODEL.value: _ABSENT_MODEL}):
        seed_model_cache(monkeypatch, tmp_path / "hf-cache", missing=[_ABSENT_MODEL])

        result = provision_models(dry_run=True, progress=progress)

    assert progress.downloads == []
    assert result.action == ProvisionAction.DRY_RUN
    assert result.code == ""
    assert result.detail == f"would download 1 missing model repo(s): {_ABSENT_MODEL}"


def test_install_reports_the_model_probe_through_the_sink_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_status_dir: Path,
) -> None:
    """``install`` reaches the same fetch and reports it the same way.

    The sink arrives at the model step through the install orchestration, so
    an install shows the cache probe and the download it is waiting on in the
    words the service verbs use.
    """
    del isolated_status_dir
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")
    workspace = tmp_path / "consumer"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(
        PROJECT_ONLY, encoding="utf-8", newline=""
    )
    inventory = configured_model_repos()
    progress = _RecordingProgress()

    report = install_run(
        path=workspace,
        provision=True,
        local_only=True,
        assume_yes=True,
        provision_progress=progress,
    )

    outcome = report.provision_outcome
    assert outcome is not None
    models = result_for(outcome, ProvisionStep.MODELS)
    assert models is not None
    assert models.action == ProvisionAction.UNCHANGED
    assert progress.stages == [
        f"Verifying {model.label} ({position}/{len(inventory)})"
        for position, model in enumerate(inventory, start=1)
    ]


def _unserved_hub() -> LoopbackModelHub:
    """An endpoint nothing listens on: every connection to it is refused."""
    return LoopbackModelHub(
        repos=(), endpoint=f"http://{LOOPBACK_HOST}:{free_loopback_port()}"
    )


def _assert_a_rerun_completes(cache: Path) -> None:
    """A healthy hub and no cleanup: the next run must finish the job.

    Whatever the failed run left in the cache - nothing, lock files, a partial
    weight file - is left exactly as it was, because an operator is told to
    run the command again and nothing more.
    """
    with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as healthy:
        outcome, _progress = fetch_from(healthy, cache)

    assert outcome["action"] in {ProvisionAction.CREATED, ProvisionAction.UNCHANGED}
    assert cached_snapshot_is_complete(DENSE_REPO, revision=None, cache_dir=cache)
    assert cached_snapshot_is_complete(RERANKER_REPO, revision=None, cache_dir=cache)


def test_missing_repos_are_downloaded_reported_and_then_left_alone(
    tmp_path: Path,
) -> None:
    """Missing models are fetched from the hub, with progress, exactly once.

    The whole branch the offline tests cannot reach: an empty cache, a hub
    that answers, and the shipped fetch downloading through the shipped
    client. The cache is then judged by the product's own completeness probe,
    and a second run has to find it complete and ask the hub for nothing.

    Mutation check: with the download call removed from the download
    process, the repositories are reported ``downloaded`` although nothing
    arrived - the hub saw no file request and the first downloads assertion
    fails. With both of the fetch's looks at the cache ignored, the second run
    starts download processes and asks the hub again, and the request-count
    assertion fails; the first look alone is held by the cached-inventory test
    above, and the second by the test of a fetch that waited. Restoring each
    passes.
    """
    cache = tmp_path / "hub-cache"
    with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
        first, progress = fetch_from(hub, cache)

        assert hub.downloads_of(DENSE_REPO).count("model.safetensors") == 1
        assert hub.downloads_of(RERANKER_REPO).count("model.safetensors") == 1
        assert first["processes_started"] == 2, "one download process per repository"
        assert first["processes_left"] == []
        assert first["action"] == ProvisionAction.CREATED
        assert first["code"] == ""
        assert first["detail"] == (
            f"downloaded 2 model repo(s): {DENSE_REPO}, {RERANKER_REPO}"
            f"; unpinned: {DENSE_REPO}, {RERANKER_REPO}"
        )
        assert first["repos"] == [
            [DENSE_REPO, "created", ""],
            [RERANKER_REPO, "created", ""],
        ]
        assert first["details"] == ["downloaded", "downloaded"]
        assert "Verifying Dense (Qwen3) (1/2)" in progress
        assert "Downloading Dense (Qwen3) (1/2)" in progress
        assert "Downloading Reranker (CrossEncoder) (2/2)" in progress
        assert cached_snapshot_is_complete(DENSE_REPO, revision=None, cache_dir=cache)
        assert cached_snapshot_is_complete(
            RERANKER_REPO, revision=None, cache_dir=cache
        )

        asked_so_far = len(hub.requests)
        second, _progress = fetch_from(hub, cache)

        assert len(hub.requests) == asked_so_far, hub.requests[asked_so_far:]
        assert second["processes_started"] == 0, "a cached start pays for no process"
        assert second["action"] == ProvisionAction.UNCHANGED
        assert second["detail"] == (
            f"all 2 model repos already cached; unpinned: {DENSE_REPO}, {RERANKER_REPO}"
        )


class TestAFetchThatCannotComplete:
    """Each way the hub or the disk lets a fetch down ends the same way.

    One failed outcome whose code names the cause and whose detail names what
    to do, with every repository still attempted - and then, with the cause
    gone and nothing cleaned up by hand, a run that completes. The fetch is
    the shipped one in a fresh interpreter; the hub is a loopback stand-in and
    the conditions are real ones on a real socket or a real volume.
    """

    def test_a_hub_that_refuses_connections(self, tmp_path: Path) -> None:
        """Nothing listens at the endpoint: the network is the remedy.

        Mutation check: with an unreachable hub classed as a missing
        repository, the code assertion fails with ``models_not_found``;
        restoring the classification passes.
        """
        cache = tmp_path / "hub-cache"
        dead = _unserved_hub()

        outcome, _progress = fetch_from(dead, cache, QUICK_TIMEOUTS)

        assert outcome["action"] == ProvisionAction.FAILED
        assert outcome["code"] == MODELS_FETCH_FAILED
        assert outcome["repos"] == [
            [DENSE_REPO, "failed", MODELS_FETCH_FAILED],
            [RERANKER_REPO, "failed", MODELS_FETCH_FAILED],
        ]
        detail = str(outcome["detail"])
        assert f"Check network access to {dead.endpoint}" in detail
        assert "vaultspec-rag server warmup" in detail
        assert EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value in detail
        _assert_a_rerun_completes(cache)

    def test_a_repository_the_hub_does_not_have(self, tmp_path: Path) -> None:
        """A name the hub answers "not found" for: the setting is the remedy.

        The other repository is still fetched, so the failure names exactly
        the one that is wrong.

        Mutation check: with the not-found errors no longer recognised, the
        code assertion fails with ``models_fetch_failed`` and the operator
        would be sent to check a network that works; restoring them passes.
        """
        cache = tmp_path / "hub-cache"
        with loopback_model_hub([RERANKER_REPO]) as hub:
            outcome, _progress = fetch_from(hub, cache)

            assert hub.downloads_of(DENSE_REPO) == []
            assert outcome["action"] == ProvisionAction.FAILED
            assert outcome["code"] == MODELS_NOT_FOUND
            assert outcome["repos"] == [
                [DENSE_REPO, "failed", MODELS_NOT_FOUND],
                [RERANKER_REPO, "created", ""],
            ]
            detail = str(outcome["detail"])
            assert f"The hub at {hub.endpoint} has no such public repository" in detail
            assert "Correct the model setting" in detail
        _assert_a_rerun_completes(cache)

    def test_a_download_the_volume_cannot_hold(self, tmp_path: Path) -> None:
        """A repository larger than the free space is refused before a byte.

        How the condition is staged, exactly: the volume is not filled. The
        hub declares a weight file one gibibyte larger than the space this
        volume really has free, and the fetch compares that declaration with
        the volume's real free space, as it would for a real repository. What
        is proven is the refusal and that nothing was requested; what is not
        reproduced here is a volume that fills during a transfer, which is
        the classification test below.

        The size is asked for by the download process, which then fetches
        nothing until the fetch has judged it. Refused, it is stopped where
        it waits.

        Mutation checks: with the free-space comparison removed, the weight
        file is requested and the downloads assertion fails. With the
        download process no longer waiting for its answer, it has fetched
        files by the time the refusal reaches it and the same assertion
        fails. Restoring each passes.
        """
        cache = tmp_path / "hub-cache"
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            hub.declared_weight_size[DENSE_REPO] = shutil.disk_usage(tmp_path).free + (
                1 << 30
            )

            outcome, _progress = fetch_from(hub, cache)

            assert hub.downloads_of(DENSE_REPO) == [], "a doomed download was started"
            assert outcome["action"] == ProvisionAction.FAILED
            assert outcome["code"] == MODELS_NO_SPACE
            assert outcome["repos"] == [
                [DENSE_REPO, "failed", MODELS_NO_SPACE],
                [RERANKER_REPO, "created", ""],
            ]
            detail = str(outcome["detail"])
            assert str(cache) in detail
            assert "Free space on the volume" in detail
            assert EnvVar.HF_HOME.value in detail
        _assert_a_rerun_completes(cache)

    def test_a_hub_that_goes_silent_mid_fetch(self, tmp_path: Path) -> None:
        """A hub that accepts the request and then says nothing is given up on.

        The bound is the hub client's own, and this pins it: one attempt per
        read timeout, and six attempts before the file fails, because no byte
        ever arrives to start the count again. With the client's default
        timeout of ten seconds that is about a minute for a dead hub; here the
        operator's own variable shortens the timeout to one second.

        Mutation check: the attempt count is the client's and cannot be broken
        from this side, so what was mutated is the outcome - with a timed-out
        transfer classed as a missing repository the code assertion fails;
        restoring the classification passes.
        """
        cache = tmp_path / "hub-cache"
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            hub.weight_responders[DENSE_REPO] = stay_silent

            outcome, _progress = fetch_from(hub, cache, QUICK_TIMEOUTS)

            assert hub.downloads_of(DENSE_REPO).count(WEIGHT_FILE) == 6
            assert outcome["action"] == ProvisionAction.FAILED
            assert outcome["code"] == MODELS_FETCH_FAILED
            assert outcome["repos"] == [
                [DENSE_REPO, "failed", MODELS_FETCH_FAILED],
                [RERANKER_REPO, "created", ""],
            ]
            assert f"Check network access to {hub.endpoint}" in str(outcome["detail"])
        assert list(cache.rglob("*.incomplete")) == []
        _assert_a_rerun_completes(cache)

    def test_a_hub_that_never_answers_the_first_question(
        self, tmp_path: Path, fetched_once: Path
    ) -> None:
        """Asking how large a repository is has the client's timeout too.

        The hub accepts every request and answers none, so the first thing a
        download process asks - the size of the repository - is never
        answered. That request is given the timeout the hub client gives its
        own, shortened here to a second the way an operator shortens it, and
        the failure is the ordinary one: the hub cannot be reached, check the
        network. Without a timeout the client waits on that request without
        limit, and only the progress floor would end it, a minute and a
        window later, as a stalled download.

        Mutation check: with the request made without a timeout, the floor
        is what ends the download and the code assertion fails with
        ``models_stalled``; restoring the timeout passes.
        """
        cache = tmp_path / "hub-cache"
        _copy_cached(fetched_once, cache, [RERANKER_REPO])
        with plain_loopback_sources() as sources:
            hub = LoopbackModelHub(
                repos=(), endpoint=sources.serve(stay_silent, tls=False).url()
            )

            outcome, _progress = fetch_from(
                hub, cache, {"TEST_FETCH_WINDOW": "5", "HF_HUB_ETAG_TIMEOUT": "1"}
            )

        assert outcome["code"] == MODELS_FETCH_FAILED
        assert f"Check network access to {hub.endpoint}" in str(outcome["detail"])
        _assert_a_rerun_completes(cache)

    def test_a_connection_reset_in_the_middle_of_a_file(self, tmp_path: Path) -> None:
        """A transfer cut off part-way fails once and leaves nothing half-made.

        The hub sends the first half of the weight file and then resets the
        connection, every time it is asked. The hub client deletes the file it
        could not finish, so the cache holds no partial file afterwards. The
        run that follows fetches that file whole from a healthy hub and does
        not ask again for the repository that had already finished - which is
        what the remedy tells the operator to expect.

        Mutation check: with the remedy still promising that a partial
        download resumes, the wording assertion fails; the cache and request
        assertions describe the hub client and cannot be broken from here.
        """
        cache = tmp_path / "hub-cache"
        weight = weight_bytes()
        half = len(weight) // 2
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            hub.weight_responders[DENSE_REPO] = lambda handler: send_then_reset(
                handler, weight[:half], declared=len(weight)
            )

            outcome, _progress = fetch_from(hub, cache, QUICK_TIMEOUTS)

            assert outcome["action"] == ProvisionAction.FAILED
            assert outcome["code"] == MODELS_FETCH_FAILED
            assert outcome["repos"] == [
                [DENSE_REPO, "failed", MODELS_FETCH_FAILED],
                [RERANKER_REPO, "created", ""],
            ]
            assert "an interrupted one is fetched again" in str(outcome["detail"])
        assert list(cache.rglob("*.incomplete")) == []

        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as healthy:
            again, _progress = fetch_from(healthy, cache)

            assert again["action"] == ProvisionAction.CREATED
            assert healthy.downloads_of(DENSE_REPO).count(WEIGHT_FILE) == 1
            assert healthy.resumed_from == []
            assert healthy.downloads_of(RERANKER_REPO) == []
        assert cached_snapshot_is_complete(DENSE_REPO, revision=None, cache_dir=cache)

    def test_the_fetch_leaves_the_hub_clients_read_timeout_alone(
        self, tmp_path: Path
    ) -> None:
        """How long a silent hub is waited on is the client's default, ten seconds.

        The fetch once raised that timeout to five minutes, which let a dead
        hub hold a run for half an hour. The stall bound the guides state -
        six attempts of ten seconds - is true only while nothing here
        overrides the client, and while the client's own default stays what
        it is; either changing must fail here, not go unnoticed.

        Mutation check: with a default for the client's timeout written into
        the environment before the client is imported, the value read back is
        that default and the assertion fails; removing it passes.
        """
        env = child_environment(_unserved_hub(), tmp_path / "hub-cache")
        env.pop(EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value, None)

        completed = run_child(TIMEOUT_AFTER_A_FETCH, env)

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip().splitlines()[-1] == "10"

    def test_a_volume_that_fills_mid_transfer_is_named_as_such(self) -> None:
        """An out-of-space error is recognised wherever the client wrapped it.

        The limit of this test, stated plainly: no volume is filled. A
        transfer that exhausts a real volume cannot be staged in a unit run
        without a volume of a chosen size, which needs privileges the suite
        does not have. What is exercised is the classification, at the one
        seam it has: the operating system's own error object, bare and as the
        cause of the error the hub client raises. That the client's write
        raises it, and that the run then ends as one failed outcome, is the
        same path the refused-connection test drives with a different error.

        Mutation check: with the error-number test removed, the first
        assertion fails with ``models_fetch_failed``; restoring it passes.
        """
        full = OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        wrapped = RuntimeError("the hub client gave up on the file")
        wrapped.__cause__ = full

        assert classify_hub_failure(full) is HubFailure.NO_SPACE
        assert classify_hub_failure(wrapped) is HubFailure.NO_SPACE
        assert (
            classify_hub_failure(OSError(errno.EACCES, "denied"))
            is HubFailure.UNREACHABLE
        )


@pytest.fixture(scope="module")
def fetched_once(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A cache holding both stand-in repositories, fetched once for the module.

    Fetched by the shipped fetch from the stand-in hub, so what a case copies
    out of it is what a real run leaves behind.
    """
    cache = tmp_path_factory.mktemp("fetched-once") / "hub-cache"
    with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as healthy:
        fetch_from(healthy, cache)
    assert cached_snapshot_is_complete(DENSE_REPO, revision=None, cache_dir=cache)
    assert cached_snapshot_is_complete(RERANKER_REPO, revision=None, cache_dir=cache)
    return cache


def _copy_cached(fetched: Path, cache: Path, repos: Collection[str]) -> None:
    """Put *repos* into *cache* as an earlier fetch would have left them."""
    for repo in repos:
        name = f"models--{repo.replace('/', '--')}"
        shutil.copytree(fetched / name, cache / name, symlinks=True)
        assert cached_snapshot_is_complete(repo, revision=None, cache_dir=cache)


def _cache_holding_the_reranker(cache: Path, fetched: Path) -> None:
    """Leave the reranker cached in *cache* and the dense model missing.

    The cases below shorten the progress window to seconds, which would also
    stop a healthy download that takes longer than that on a loaded machine.
    With one repository already cached, the only download a short window ever
    judges is the one that is meant to fail.
    """
    _copy_cached(fetched, cache, [RERANKER_REPO])
    assert not cached_snapshot_is_complete(DENSE_REPO, revision=None, cache_dir=cache)


#: A progress window of two seconds, opened only by a first byte. The wait for
#: a first byte is left far longer than any case runs, so a download process
#: that is slow to start on a loaded machine is never judged before the hub
#: has sent it anything: what stops it is the condition the case staged.
_SHORT_WINDOW = {"TEST_FETCH_WINDOW": "2", "TEST_FETCH_FIRST_BYTE": "600"}


class _TricklingHub:
    """Answer every request a few bytes at a time, and count who was dropped.

    A quarter of a kilobyte every twentieth of a second for a minute: fast
    enough that no read ever times out, and far too slow to finish anything.
    """

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self.began = 0
        self.dropped = 0

    def respond(self, handler: QuietHandler) -> None:
        with self._changed:
            self.began += 1
        try:
            send_trickle(handler, pieces=1200, piece=b"\0" * 256, interval=0.05)
        except OSError:
            with self._changed:
                self.dropped += 1
                self._changed.notify_all()
            raise

    def saw_every_connection_drop(self) -> bool:
        """Wait until each response that was being sent lost its reader.

        The ceiling is only a ceiling: the wait returns the moment the count
        is met, and a response still being read when it expires is a download
        that outlived the fetch.
        """
        with self._changed:
            return self._changed.wait_for(
                lambda: self.began > 0 and self.dropped == self.began,
                timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
            )


class TestTheProgressFloor:
    """When the first window opens, and what it then takes to fall short.

    The rule itself, on a clock the test supplies, so each case is exact and
    takes no time. A mebibyte a window is the shipped floor; the windows here
    are ten seconds and the wait for a first byte is sixty.
    """

    _LIMITS = FetchLimits(window_seconds=10.0, first_byte_seconds=60.0)

    def test_nothing_is_judged_while_the_first_byte_is_awaited(self) -> None:
        """A process that is slow to start is not a hub that sent too little.

        Mutation check: with the first window opened when the process is
        started, the tenth second is already a breach and this fails;
        restoring the rule passes.
        """
        floor = _Floor(self._LIMITS, 0.0)

        assert not any(floor.breached(float(second), 0) for second in range(60))

    def test_a_download_that_never_receives_a_byte_is_still_stopped(self) -> None:
        """The window opens a minute after the start whatever has happened.

        Mutation check: with the window opened by a first byte alone, a
        download that receives nothing is never judged and the last assertion
        fails; restoring the wait's end passes.
        """
        floor = _Floor(self._LIMITS, 0.0)

        assert not any(floor.breached(float(second), 0) for second in range(70))
        assert floor.breached(70.0, 0), "sixty seconds waited, then one window"

    def test_the_window_opens_at_the_first_byte(self) -> None:
        """From the first byte, one window with too little is enough.

        The byte arrives in the fifth second and a hundred more every second
        after it. The fifteenth second is the first with a whole window behind
        it, and it is a breach.
        """
        floor = _Floor(self._LIMITS, 0.0)

        assert not any(floor.breached(float(second), 0) for second in range(5))
        assert not any(
            floor.breached(float(second), 100 * (second - 4)) for second in range(5, 15)
        )
        assert floor.breached(15.0, 1100)

    def test_a_slow_link_that_keeps_the_floor_is_never_stopped(self) -> None:
        """An eighth of the floor every second is a floor and a quarter a window."""
        floor = _Floor(self._LIMITS, 0.0)
        each_second = self._LIMITS.min_bytes // 8

        assert not any(
            floor.breached(float(second), second * each_second)
            for second in range(1, 300)
        )

    def test_a_burst_buys_one_window_and_no_more(self) -> None:
        """A hub that sends a great deal and then nothing is stopped a window on."""
        floor = _Floor(self._LIMITS, 0.0)
        burst = 50 * self._LIMITS.min_bytes

        assert not floor.breached(1.0, burst)
        assert not any(floor.breached(float(second), burst) for second in range(2, 11))
        assert floor.breached(11.0, burst)


class TestADownloadThatMustBeStopped:
    """A download that will never finish is stopped, and nothing is left running.

    The download runs in a process of its own and the fetch watches what it
    reports: fewer than a mebibyte in a whole window, and the process and
    everything it started are killed. The window is ten minutes in production
    and two seconds here; the code is the same.

    No case here is decided by how fast the machine is. The short window is
    opened only by the first byte the hub sends, and what each case then
    asserts is something the hub or the cache saw, never how long the run
    took.

    What these cases do not exercise is the hub's native transfer protocol,
    which the default weights use and a loopback hub cannot serve. They do not
    need to: the stop is the operating system ending a process, which does not
    depend on what was moving the bytes inside it.
    """

    def test_a_hub_that_trickles_is_stopped_by_the_floor(
        self, tmp_path: Path, fetched_once: Path
    ) -> None:
        """A few bytes at a time never trips a read timeout, and never finishes.

        The stand-in answers every request that way, so the very first thing
        the download process asks the hub - how large the repository is - is
        already the trickle, and the first byte it receives opens the window.
        A hub that kept going could hold a command for ever. The floor stops
        the download one window later, and the hub then sees every reader it
        had go while it is still sending: the evidence that the download is
        really gone and not merely no longer waited for. It is the hub that
        is asked, because a download process that had lost its parent would
        no longer be among the fetch's own processes and would still be
        reading.

        Mutation checks, each restored and passing afterwards. With the floor
        never judged breached, the fetch waits out the whole minute of
        trickle and ends as a failed transfer, failing the code assertion
        with ``models_fetch_failed``. A download is stopped twice over - it
        is killed, and it ends itself when nobody reads its reports - so the
        connection assertion fails only with both removed: the download then
        reads the trickle to its end and no reader is ever dropped.
        """
        cache = tmp_path / "hub-cache"
        _cache_holding_the_reranker(cache, fetched_once)
        trickling = _TricklingHub()
        with plain_loopback_sources() as sources:
            hub = LoopbackModelHub(
                repos=(), endpoint=sources.serve(trickling.respond, tls=False).url()
            )

            outcome, _progress = fetch_from(hub, cache, _SHORT_WINDOW)

            assert outcome["code"] == MODELS_STALLED
            assert outcome["repos"] == [
                [DENSE_REPO, "failed", MODELS_STALLED],
                [RERANKER_REPO, "unchanged", ""],
            ]
            assert trickling.saw_every_connection_drop(), (
                "the hub was still being read after the fetch returned"
            )
        detail = str(outcome["detail"])
        assert "fewer than 1.0 MiB arrived in 2 seconds" in detail
        assert f"{EnvVar.HF_HUB_OFFLINE.value}=1" in detail
        assert EnvVar.RAG_HF_ENDPOINT.value in detail
        assert list(cache.rglob("*.incomplete")) == []
        _assert_a_rerun_completes(cache)

    def test_a_hub_that_never_sends_a_byte_is_stopped_too(
        self, tmp_path: Path, fetched_once: Path
    ) -> None:
        """Waiting for a first byte has an end, and the window follows it.

        The hub accepts every request and answers none. The hub client gives
        such a request up by itself after its own timeout, ten seconds unless
        an operator on a poor link has raised it; here it is raised to a
        minute, and the wait for a first byte and the window are a second
        each, so the download is stopped first, having received nothing.
        Whether its process had even finished starting by then makes no
        difference to the outcome, which is what makes this case independent
        of load.

        Mutation check: with the window opened by a first byte alone, nothing
        is ever judged, the hub client gives up after its minute, and the
        code assertion fails with ``models_fetch_failed``; restoring the end
        of the wait passes.
        """
        cache = tmp_path / "hub-cache"
        _cache_holding_the_reranker(cache, fetched_once)
        with plain_loopback_sources() as sources:
            hub = LoopbackModelHub(
                repos=(), endpoint=sources.serve(stay_silent, tls=False).url()
            )

            outcome, _progress = fetch_from(
                hub,
                cache,
                {
                    "TEST_FETCH_WINDOW": "1",
                    "TEST_FETCH_FIRST_BYTE": "1",
                    "HF_HUB_ETAG_TIMEOUT": "60",
                },
            )

        assert outcome["code"] == MODELS_STALLED
        assert "arrived in 1 seconds (0 B in all)" in str(outcome["detail"])
        _assert_a_rerun_completes(cache)

    def test_a_download_that_reports_nothing_is_stopped_by_the_floor(
        self, tmp_path: Path, fetched_once: Path
    ) -> None:
        """A wedged download is caught by the same rule as a slow one.

        The hub answers everything but the weight file: it accepts that
        request and never answers it. The hub client's read timeout -
        normally the fast path for exactly this - is set well above the
        window, as an operator on a poor link might raise it, so left to
        itself the client would ask for the file again every twelve seconds
        for over a minute. The floor stops it during the first wait: the hub
        is asked for the weight file once at most. The download process is
        still alive and still waiting when it is stopped, so this is also
        where the stop is held to removing the file the download had opened.

        Mutation checks, each restored and passing afterwards. With the floor
        judged only when a new report arrives, nothing is judged while the
        download waits, the client asks again, and the request-count
        assertion fails. With nothing killed after a breach the download
        carries on asking and the same assertion fails. With the unfinished
        file left where the killed download put it, the ``.incomplete``
        assertion fails. Killing only the one process, and not what it
        started, is not caught here - on a host whose interpreter is not a
        launcher the download has no descendants - and has its own test
        below.
        """
        cache = tmp_path / "hub-cache"
        _cache_holding_the_reranker(cache, fetched_once)
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            hub.weight_responders[DENSE_REPO] = stay_silent

            outcome, _progress = fetch_from(
                hub,
                cache,
                {**_SHORT_WINDOW, EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value: "12"},
            )

            assert hub.downloads_of(DENSE_REPO).count(WEIGHT_FILE) <= 1, (
                "the download was still asking after the floor should have stopped it"
            )
            assert outcome["code"] == MODELS_STALLED
            assert outcome["processes_left"] == []
        assert list(cache.rglob("*.incomplete")) == []
        _assert_a_rerun_completes(cache)

    def test_stopping_a_download_kills_what_it_started_too(self) -> None:
        """The stop reaches a process the download process started.

        On Windows the interpreter a virtual environment names can be a
        launcher that runs the real interpreter as its child, so the process
        this package starts is not always the one doing the downloading. A
        real two-level tree stands in for that shape: a process that starts
        another and waits. Both must be gone, and confirmed gone, when the
        stop returns.

        Mutation check: with only the process itself killed, the one it
        started is still running and the last assertion fails; restoring the
        descendant kill passes.
        """
        import psutil

        from .._process_probe import wait_for_exit
        from ..commands._model_download import _kill_tree

        started_another = (
            "import subprocess, sys, time\n"
            "inner = subprocess.Popen("
            "[sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "print(inner.pid, flush=True)\n"
            "time.sleep(120)\n"
        )
        outer = subprocess.Popen(
            [sys.executable, "-c", started_another],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        inner_pid = 0
        try:
            assert outer.stdout is not None
            inner_pid = int(outer.stdout.readline())
            assert psutil.pid_exists(inner_pid), "premise: a two-level tree is running"

            survivors = _kill_tree(outer)

            assert survivors == []
            assert outer.poll() is not None
            assert wait_for_exit(inner_pid, timeout=5.0), "a started process survived"
        finally:
            for pipe in (outer.stdout, outer.stderr):
                if pipe is not None:
                    pipe.close()
            # Only reached with something alive when the stop under test failed.
            for pid in (outer.pid, inner_pid):
                if pid and psutil.pid_exists(pid):
                    with contextlib.suppress(psutil.Error):
                        psutil.Process(pid).kill()

    def test_a_download_process_that_dies_is_its_own_failure(
        self, tmp_path: Path, fetched_once: Path
    ) -> None:
        """A process ended from outside reports nothing, and that is reported.

        The download is killed mid-transfer the way the operating system kills
        one that ran out of memory. It leaves no result and no chance to
        remove the file it was writing, so the fetch says the process died,
        with its exit code, and removes the file itself.

        Mutation check: with a process that reported no result taken as a
        completed download, the repository is reported downloaded and the
        code assertion fails; restoring the check passes.
        """
        cache = tmp_path / "hub-cache"
        _cache_holding_the_reranker(cache, fetched_once)
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            hub.weight_responders[DENSE_REPO] = stay_silent

            outcome, _progress = fetch_from(
                hub,
                cache,
                {
                    "TEST_KILL_FIRST_DOWNLOAD": "1",
                    EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value: "45",
                },
            )

            assert outcome["code"] == MODELS_DOWNLOAD_DIED
            assert outcome["processes_left"] == []
        details = cast("list[str]", outcome["details"])
        assert "exit code" in details[0]
        assert "reported no result" in details[0]
        assert list(cache.rglob("*.incomplete")) == []
        _assert_a_rerun_completes(cache)

    def test_a_second_fetch_waits_for_the_cache_and_is_not_called_stalled(
        self, tmp_path: Path
    ) -> None:
        """Waiting for another process's fetch is not a failing download.

        Two fetches of one repository meet inside the hub client, where the
        second waits on a file lock and receives nothing - which the floor
        would stop as stalled. The second waits for the cache instead, before
        it asks the hub for anything, and says who it is waiting for; only
        when that wait runs out does it fail, as busy.

        Mutation check: with the claim on the cache not taken, the fetch goes
        straight to the hub and downloads both repositories, failing the
        request assertion; restoring the claim passes.
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
                outcome, progress = fetch_from(
                    hub, cache, {"TEST_FETCH_CONTENTION": "1.5"}
                )

                assert hub.requests == [], "the hub was asked while the cache was held"
        finally:
            release_anchor_claim(held.descriptor, pid_record=True)
        assert outcome["code"] == MODELS_BUSY
        assert outcome["processes_started"] == 0
        assert "to finish downloading models" in progress
        assert "Wait for that process to finish" in str(outcome["detail"])
        _assert_a_rerun_completes(cache)


@contextmanager
def _tls_hub(tmp_path: Path, *, trusted: bool) -> Generator[LoopbackModelHub]:
    """Serve the stand-in hub over real TLS, with a known or an unknown certificate."""
    hub = LoopbackModelHub(repos=(DENSE_REPO, RERANKER_REPO))
    with trusted_loopback_sources(tmp_path / "tls") as sources:
        hub.endpoint = sources.serve(hub.respond, trusted=trusted).url()
        yield hub


def test_what_another_process_fetched_meanwhile_is_not_fetched_again(
    tmp_path: Path, fetched_once: Path
) -> None:
    """A fetch that waited for the cache looks at it again before downloading.

    The cache is held while a fetch starts, so the fetch waits. While it
    waits, both repositories appear in the cache - what the holder was there
    to do - and the claim is released. The waiting fetch must find them and
    ask the hub for nothing.

    Mutation check: with the look after the wait removed, the fetch downloads
    the first repository it had already judged missing, and the request
    assertion fails; restoring the look passes.
    """
    cache = tmp_path / "hub-cache"
    held = claim_anchor(
        cache / ".locks" / "vaultspec-rag-fetch.lock",
        pid_record=True,
        create_parent=True,
    )
    assert held.descriptor is not None, "premise: this test holds the cache"
    released = False
    with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
        waiting = subprocess.Popen(
            [sys.executable, "-c", FETCH_IN_A_FRESH_INTERPRETER],
            env=child_environment(hub, cache),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert waiting.stderr is not None
            line = "\n"
            while "to finish downloading models" not in line:
                assert line, "the fetch ended without ever waiting for the cache"
                line = waiting.stderr.readline()
            _copy_cached(fetched_once, cache, [DENSE_REPO, RERANKER_REPO])
            release_anchor_claim(held.descriptor, pid_record=True)
            released = True
            stdout, _stderr = waiting.communicate(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
        finally:
            if waiting.poll() is None:
                waiting.kill()
                waiting.communicate()
            if not released:
                release_anchor_claim(held.descriptor, pid_record=True)

        assert hub.requests == [], "what the cache already held was asked for again"
    outcome = reported_outcome(stdout)
    assert outcome["repos"] == [
        [DENSE_REPO, "unchanged", ""],
        [RERANKER_REPO, "unchanged", ""],
    ]
    assert outcome["processes_started"] == 0


class TestAHubWithAnUntrustedCertificate:
    """A mirror whose certificate this host does not trust, and the way to trust it."""

    def test_an_untrusted_certificate_is_refused_and_named(
        self, tmp_path: Path
    ) -> None:
        """Nothing is fetched, and the remedy is the certificate, not the network.

        The hub serves real TLS with a certificate the client has never been
        told about; the bundle named in ``SSL_CERT_FILE`` holds a different
        one. The refusal is the download process's - it is the only one that
        asks the hub anything - and it reports why in a word the fetch can
        act on.

        Mutation check: with a verification failure no longer recognised, the
        code assertion fails with ``models_fetch_failed`` and the operator
        would be sent to check a network that works; restoring it passes.
        """
        cache = tmp_path / "hub-cache"
        with _tls_hub(tmp_path, trusted=False) as hub:
            outcome, _progress = fetch_from(hub, cache, QUICK_TIMEOUTS)

            assert hub.requests == [], "a request was served over an untrusted link"
        assert outcome["code"] == MODELS_UNTRUSTED_CERTIFICATE
        detail = str(outcome["detail"])
        assert f"the certificate of {hub.endpoint} is not trusted" in detail
        assert "SSL_CERT_FILE" in detail
        assert "verification is never skipped" in detail

    def test_the_named_bundle_is_what_makes_a_private_hub_usable(
        self, tmp_path: Path
    ) -> None:
        """The remedy works: a bundle in ``SSL_CERT_FILE`` is honoured end to end.

        The same kind of hub, with the certificate the named bundle holds.
        Both requests of a fetch reach it - the one that asks how large the
        repository is and the download itself, each made by the download
        process - so this is the proof that the sentence the failure prints
        is true of the client that printed it.
        """
        cache = tmp_path / "hub-cache"
        with _tls_hub(tmp_path, trusted=True) as hub:
            outcome, _progress = fetch_from(hub, cache)

            assert hub.downloads_of(DENSE_REPO).count(WEIGHT_FILE) == 1
        assert outcome["action"] == ProvisionAction.CREATED
        assert cached_snapshot_is_complete(DENSE_REPO, revision=None, cache_dir=cache)


#: Run ``server warmup`` as a host that can serve, in a fresh interpreter, and
#: report on the last line of stderr whether the run imported torch. The
#: installation role and what the daemon's interpreter can do are pinned with
#: the helpers the in-process suites use - both are facts about the machine,
#: which a test cannot change - and the pins have to be applied here because
#: they do not cross a process boundary.
_WARMUP_AS_A_HOST = """
import sys

import pytest

from vaultspec_rag.operator_state._installation import ComputeCapability, InstallRole
from vaultspec_rag.tests.conftest import pin_daemon_capability, pin_install_role

pinned = pytest.MonkeyPatch()
pin_install_role(pinned, InstallRole.HOST)
pin_daemon_capability(pinned, ComputeCapability.READY)

from vaultspec_rag.cli import app

code = 0
try:
    app(["server", "warmup"])
except SystemExit as stopped:
    code = stopped.code if isinstance(stopped.code, int) else 1
print("torch loaded" if "torch" in sys.modules else "torch absent", file=sys.stderr)
sys.exit(code)
"""


class TestWarmupVerb:
    """``server warmup`` exits by what it achieved, and never loads torch.

    The verb is run whole, in a fresh interpreter, against the stand-in hub:
    its exit code is the process's, and its lines are what an operator reads.
    """

    def test_fetched_then_already_cached_both_exit_zero(self, tmp_path: Path) -> None:
        cache = tmp_path / "hub-cache"
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            env = child_environment(hub, cache)

            fetched = run_child(_WARMUP_AS_A_HOST, env)
            asked_so_far = len(hub.requests)
            cached = run_child(_WARMUP_AS_A_HOST, env)

            assert fetched.returncode == 0, fetched.stderr
            assert f"Dense (Qwen3): {DENSE_REPO} downloaded" in fetched.stdout
            assert f"Reranker (CrossEncoder): {RERANKER_REPO} downloaded" in (
                fetched.stdout
            )
            assert cached.returncode == 0, cached.stderr
            assert f"Dense (Qwen3): {DENSE_REPO} cached" in cached.stdout
            assert len(hub.requests) == asked_so_far

    def test_a_missing_model_with_the_hub_offline_exits_one(
        self, tmp_path: Path
    ) -> None:
        """Offline and missing is a failed warmup, with the switch named.

        Mutation check: with the verb no longer exiting on a failed fetch, the
        return code is 0 and the first assertion fails; restoring the exit
        passes.
        """
        dead = _unserved_hub()
        env = child_environment(
            dead, tmp_path / "hub-cache", {EnvVar.HF_HUB_OFFLINE.value: "1"}
        )

        completed = run_child(_WARMUP_AS_A_HOST, env)

        assert completed.returncode == 1, completed.stdout
        assert f"{DENSE_REPO} not in the local cache" in completed.stdout
        flattened = " ".join(completed.stdout.split())
        assert f"Unset {EnvVar.HF_HUB_OFFLINE.value}" in flattened

    def test_a_fetch_that_fails_exits_one_with_the_remedy(self, tmp_path: Path) -> None:
        dead = _unserved_hub()
        env = child_environment(dead, tmp_path / "hub-cache", QUICK_TIMEOUTS)

        completed = run_child(_WARMUP_AS_A_HOST, env)

        assert completed.returncode == 1, completed.stdout
        flattened = " ".join(completed.stdout.split())
        assert f"Check network access to {dead.endpoint}" in flattened

    def test_warmup_never_imports_torch(self, tmp_path: Path) -> None:
        """The verb fetches files; whether torch works is not its question.

        A service-control command that imports torch pays seconds for it and
        refuses on a host whose card is merely busy. The fetch is driven all
        the way through a real download so the claim covers the whole verb,
        not only its first branch.

        Mutation check: with the accelerator loaded at the top of the verb
        again, a host interpreter reports ``torch loaded`` and the assertion
        fails; restoring the verb passes. In a lane without torch installed
        the assertion cannot fail, which is why the host lane is where it
        was proven.
        """
        with loopback_model_hub([DENSE_REPO, RERANKER_REPO]) as hub:
            completed = run_child(
                _WARMUP_AS_A_HOST, child_environment(hub, tmp_path / "hub-cache")
            )

        assert completed.returncode == 0, completed.stderr
        assert completed.stderr.strip().splitlines()[-1] == "torch absent"


class TestInstallExitCode:
    """``install`` fails when a dependency it was asked to provision is missing."""

    def test_a_failed_model_step_fails_the_run_and_a_rerun_completes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        isolated_status_dir: Path,
    ) -> None:
        """Exit 1 and status ``failed``, with the whole report still there.

        Enrollment completed before provisioning ran, so the envelope has to
        go on carrying it: a caller reads which step failed, why, and what to
        do, and a second run - once the model is there - finds the enrollment
        in place and finishes.

        Mutation check: with a failed provisioning step no longer counted as
        a failure of the run, the first run exits 0 with status ``created``
        and the exit-code assertion fails; restoring it passes.
        """
        del isolated_status_dir
        workspace = tmp_path / "consumer"
        workspace.mkdir()
        (workspace / "pyproject.toml").write_text(
            PROJECT_ONLY, encoding="utf-8", newline=""
        )
        argv = [
            "install",
            "--target",
            str(workspace),
            "--local-only",
            "--yes",
            "--json",
        ]

        with managed_env(**{EnvVar.EMBEDDING_MODEL.value: _ABSENT_MODEL}):
            cache = seed_model_cache(
                monkeypatch, tmp_path / "hf-cache", missing=[_ABSENT_MODEL]
            )
            failed = runner.invoke(app, argv)

            assert failed.exit_code == 1, failed.output
            envelope = cast("dict[str, object]", json.loads(failed.stdout))
            assert envelope["status"] == "failed"
            report = cast("dict[str, object]", envelope["data"])
            assert report["action"] == "install"
            provisioning = cast("dict[str, object]", report["provisioning"])
            steps = cast("list[dict[str, object]]", provisioning["steps"])
            models = next(step for step in steps if step["step"] == "models")
            assert models["action"] == ProvisionAction.FAILED
            assert models["code"] == MODELS_OFFLINE
            assert "vaultspec-rag server warmup" in str(models["detail"])

            seed_model_cache(monkeypatch, cache.with_name("hf-cache-complete"))
            again = runner.invoke(app, argv)

        assert again.exit_code == 0, again.output
        envelope = cast("dict[str, object]", json.loads(again.stdout))
        assert envelope["status"] == "created"
        report = cast("dict[str, object]", envelope["data"])
        provisioning = cast("dict[str, object]", report["provisioning"])
        steps = cast("list[dict[str, object]]", provisioning["steps"])
        models = next(step for step in steps if step["step"] == "models")
        assert models["action"] == ProvisionAction.UNCHANGED
