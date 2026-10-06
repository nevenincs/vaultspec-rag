"""Make the configured model snapshots present in the Hugging Face cache.

The one implementation of "probe the cache, download what is missing". Every
command that needs the weights on disk - ``install``, ``server warmup``, and
the preflight of ``server start`` - reaches it through the provisioning front
door, so they probe the same inventory, fetch the same revisions, and fail the
same way.

Only snapshot files are fetched. No model is constructed and torch is never
imported, so this is safe on the service-control path, which must not touch
the GPU.

The hub's offline switch is honoured rather than worked around: with it set, a
missing repository is a failure that names the switch, never a download
attempt. Every missing repository is attempted before the result is returned,
so one unavailable repository does not hide the next.

Every way a fetch can fail ends as a result, never an exception, and each
names what the operator should do: a hub that cannot be reached, one that
presents a certificate this host does not trust, a repository or revision the
hub does not have, a cache volume that cannot hold the download, and a
transfer that stopped moving. The volume is refused before the first byte when
the hub declares a size it cannot fit. Nothing has to be cleaned up before the
next run: a file that was not finished is removed and every file that was is
kept, so a re-run fetches only what is still missing.

Present is not the same as correct. A model revision is a name the hub
resolves, and the hub may be a mirror, so every repository is put through the
snapshot check before it is reported: a default model is hashed against the
digests committed for its pinned commit, and any other model is checked for
its files and for safetensors weights. A cached file that fails is downloaded
again once; a repository that still fails, or that fails in a way no download
cures, is a failed result under its own code. Nothing is ever reported as
downloaded without having passed.

This module decides; it downloads nothing and asks the hub nothing itself.
Each repository that needs fetching is downloaded by a child process, which
also makes the request that asks how large it is, because a request made in a
child is the only kind that can always be stopped. A repository already in the
cache costs no process and no request.

Three bounds apply to a hub that misbehaves. One that goes silent is given up
on by the hub client itself: it abandons a request after its per-read timeout
with no bytes, and a file after six consecutive such attempts. One that keeps
sending too little to ever finish is stopped by the progress floor, whichever
request it does that to. One that keeps sending just enough is stopped by the
time allowed for the whole fetch, which is a setting, and which the wait for
another fetch into the same cache is counted against too.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .._model_cache import ModelSnapshotError, SnapshotFault, verify_snapshot
from .._sync_vocabulary import ProvisionAction
from .._units import human_bytes
from ..config._types import EnvVar, hf_cache_only
from ._hub_failure import HubFailure
from ._model_download import (
    DEFAULT_LIMITS,
    DownloadCaller,
    FetchLimits,
    download_snapshot,
    exclusive_fetch,
)

if TYPE_CHECKING:
    from ._provision import ProvisionProgress

logger = logging.getLogger(__name__)

__all__ = [
    "MODELS_BUSY",
    "MODELS_CACHE_UNUSABLE",
    "MODELS_DEADLINE",
    "MODELS_DOWNLOAD_DIED",
    "MODELS_FETCH_FAILED",
    "MODELS_HUB_MISSING",
    "MODELS_NOT_FOUND",
    "MODELS_NO_SPACE",
    "MODELS_OFFLINE",
    "MODELS_STALLED",
    "MODELS_UNTRUSTED_CERTIFICATE",
    "MODELS_UNVERIFIED",
    "ModelFetch",
    "ModelRepoResult",
    "fetch_models",
]

#: Machine-readable reasons a fetch failed, for callers that report the
#: failure under its own name.
MODELS_OFFLINE = "models_offline"
MODELS_FETCH_FAILED = "models_fetch_failed"
MODELS_NOT_FOUND = "models_not_found"
MODELS_NO_SPACE = "models_no_space"
MODELS_UNTRUSTED_CERTIFICATE = "models_untrusted_certificate"
MODELS_STALLED = "models_stalled"
MODELS_DOWNLOAD_DIED = "models_download_died"
MODELS_BUSY = "models_busy"
MODELS_HUB_MISSING = "models_hub_missing"
#: A snapshot is in the cache and is not one this package will load: a file
#: differs from the pinned release, a file is there that the release does not
#: have, or the model has no safetensors weights.
MODELS_UNVERIFIED = "models_unverified"
#: The time allowed for the whole fetch ran out.
MODELS_DEADLINE = "models_fetch_deadline"
#: A file or directory of the model cache could not be used.
MODELS_CACHE_UNUSABLE = "models_cache_unusable"

#: The code each way a hub request can fail is reported under.
_CODE_OF = {
    HubFailure.UNREACHABLE: MODELS_FETCH_FAILED,
    HubFailure.NOT_FOUND: MODELS_NOT_FOUND,
    HubFailure.NO_SPACE: MODELS_NO_SPACE,
    HubFailure.UNTRUSTED_CERTIFICATE: MODELS_UNTRUSTED_CERTIFICATE,
    HubFailure.STALLED: MODELS_STALLED,
    HubFailure.DIED: MODELS_DOWNLOAD_DIED,
    HubFailure.DEADLINE: MODELS_DEADLINE,
    HubFailure.CACHE: MODELS_CACHE_UNUSABLE,
}

_WARMUP_COMMAND = "vaultspec-rag server warmup"


@dataclass(frozen=True, slots=True)
class ModelRepoResult:
    """What happened to one configured model repository.

    Attributes:
        label: The operator-facing name of the model's role.
        repo: The repository id.
        action: ``unchanged`` when already cached and passing its check,
            ``created`` when downloaded, ``updated`` when a cached file that
            failed its check was downloaded again, ``dry_run`` when a preview
            found it missing, and ``failed`` otherwise.
        detail: The same outcome in words, ready to follow the repo id.
        code: Why it failed, as one of the module's reason constants; empty
            unless ``action`` is ``failed``.
        pinned: Whether file digests are committed for this repository at
            the commit it is used at. A model that is not pinned was checked
            for its files and weight format only, and every surface that
            lists it says so.
    """

    label: str
    repo: str
    action: ProvisionAction
    detail: str
    code: str = ""
    pinned: bool = False


@dataclass(frozen=True, slots=True)
class ModelFetch:
    """The outcome of one fetch across every configured repository.

    Attributes:
        action: The shared-vocabulary outcome of the whole fetch.
        detail: The outcome in words, carrying the remedy when it failed.
        code: A stable machine-readable reason when ``action`` is ``failed``.
        repos: One result per configured repository, in inventory order.
    """

    action: ProvisionAction
    detail: str
    code: str = ""
    repos: tuple[ModelRepoResult, ...] = ()


@dataclass(frozen=True, slots=True)
class _FetchContext:
    progress: ProvisionProgress | None
    limits: FetchLimits
    total: int
    dry_run: bool
    offline: bool
    #: The directory the hub client keeps snapshots in, and the endpoint it
    #: fetches from, as the client itself resolved them. An operator who moved
    #: either is told about the one actually in use.
    cache: Path
    endpoint: str
    #: When the fetch began, on the monotonic clock, and how long all of it
    #: may take. Every wait and every download is measured against the one
    #: start, so three repositories do not each get the whole allowance.
    started: float
    deadline_seconds: float

    @property
    def until(self) -> float:
        """The monotonic time by which the whole fetch must be over."""
        return self.started + self.deadline_seconds

    @property
    def out_of_time(self) -> bool:
        return time.monotonic() >= self.until


@dataclass(frozen=True, slots=True)
class _Wanted:
    """One repository of the inventory and where it stands in the run.

    ``revision`` is the commit it is fetched and checked at, or ``None`` for
    a model nothing pins. ``pinned`` says whether digests are committed for
    it, which decides how a passing check is worded: only a pinned model has
    been compared with anything.
    """

    label: str
    repo: str
    place: str
    revision: str | None
    pinned: bool

    @property
    def passed(self) -> str:
        """How a snapshot that passed its check is described."""
        return "verified" if self.pinned else "cached, unpinned"

    def result(
        self, action: ProvisionAction, detail: str, code: str = ""
    ) -> ModelRepoResult:
        return ModelRepoResult(self.label, self.repo, action, detail, code, self.pinned)


def fetch_models(
    *,
    dry_run: bool = False,
    progress: ProvisionProgress | None = None,
    limits: FetchLimits = DEFAULT_LIMITS,
) -> ModelFetch:
    """Ensure every configured model repository is cached, downloading the rest.

    Idempotent: a fully cached inventory reports ``unchanged`` and touches
    neither the network nor another process.

    Args:
        dry_run: Report what would be fetched without downloading it.
        progress: Where to report the probe and each download as they run;
            silent when omitted.
        limits: How little progress a download tolerates, and how long this
            fetch waits for another process that is fetching into the same
            cache.

    Returns:
        The outcome of the whole fetch with one result per repository.
    """
    try:
        from huggingface_hub import constants
    except ImportError:
        return ModelFetch(
            ProvisionAction.FAILED,
            "huggingface_hub is not installed, so the model files cannot be "
            "checked or downloaded; reinstall vaultspec-rag",
            MODELS_HUB_MISSING,
        )

    from ..config._settings import configured_model_repos, get_config

    models = configured_model_repos()
    context = _FetchContext(
        progress=progress,
        limits=limits,
        total=len(models),
        dry_run=dry_run,
        offline=hf_cache_only(),
        cache=Path(constants.HF_HUB_CACHE),
        endpoint=constants.ENDPOINT,
        started=time.monotonic(),
        deadline_seconds=float(get_config().model_fetch_deadline_seconds),
    )
    repos = tuple(
        _fetch_repo(
            context,
            _Wanted(
                model.label,
                model.repo,
                f"({position}/{len(models)})",
                model.revision,
                model.pinned,
            ),
        )
        for position, model in enumerate(models, start=1)
    )
    return _summarise(repos, context)


def _fault(context: _FetchContext, wanted: _Wanted) -> ModelSnapshotError | None:
    """Check the cached snapshot of one repository; return what is wrong.

    The whole check: for a pinned model every file is hashed, so this is the
    step an operator waits on when the models are already cached.
    """
    try:
        verify_snapshot(wanted.repo, revision=wanted.revision, cache_dir=context.cache)
    except ModelSnapshotError as fault:
        return fault
    return None


def _look(
    context: _FetchContext, wanted: _Wanted
) -> ModelRepoResult | ModelSnapshotError:
    """Check the cache and settle the repository when no fetch can help it.

    Returns:
        The repository's result when the snapshot passes, or fails in a way
        no download cures; otherwise the fault a download is expected to cure.
    """
    fault = _fault(context, wanted)
    if fault is None:
        return wanted.result(ProvisionAction.UNCHANGED, wanted.passed)
    if not fault.fetchable:
        return wanted.result(ProvisionAction.FAILED, fault.detail, MODELS_UNVERIFIED)
    return fault


def _without_fetching(
    context: _FetchContext, wanted: _Wanted, fault: ModelSnapshotError
) -> ModelRepoResult | None:
    """Answer for a repository that needs a fetch this run will not make.

    Returns:
        The preview under a dry run, the failure when the hub is offline or
        the time allowed for the whole fetch has passed, and ``None`` when
        the fetch should go ahead.
    """
    altered = fault.fault is SnapshotFault.MISMATCH
    if context.dry_run:
        return wanted.result(
            ProvisionAction.DRY_RUN,
            "would be downloaded again" if altered else "would be downloaded",
        )
    if not context.offline:
        return _not_reached(context, wanted) if context.out_of_time else None
    if altered:
        return wanted.result(ProvisionAction.FAILED, fault.detail, MODELS_UNVERIFIED)
    return wanted.result(
        ProvisionAction.FAILED,
        "not in the local cache, and the hub is offline",
        MODELS_OFFLINE,
    )


def _fetch_repo(context: _FetchContext, wanted: _Wanted) -> ModelRepoResult:
    """Check the cache for one repository and download what the check wants."""
    if context.progress is not None:
        context.progress.stage(f"Verifying {wanted.label} {wanted.place}")
    looked = _look(context, wanted)
    if isinstance(looked, ModelRepoResult):
        return looked
    answered = _without_fetching(context, wanted, looked)
    if answered is not None:
        return answered
    stage = None if context.progress is None else context.progress.stage
    with exclusive_fetch(
        context.cache,
        limits=context.limits,
        on_wait=stage,
        # One allowance for the whole fetch: a repository that waited it out
        # leaves none for the next, which is answered at once.
        since=context.started,
        until=context.until,
    ) as busy:
        if busy is not None:
            # Out of time is the reason when both hold: the wait ended
            # because the fetch did, not because the allowance for it ran out.
            return (
                _not_reached(context, wanted)
                if context.out_of_time
                else wanted.result(
                    ProvisionAction.FAILED, f"not fetched: {busy}", MODELS_BUSY
                )
            )
        # Whoever held the cache may have fetched this very repository.
        looked = _look(context, wanted)
        if isinstance(looked, ModelRepoResult):
            return looked
        return _download_repo(
            context, wanted, repair=looked.fault is SnapshotFault.MISMATCH
        )


def _not_reached(context: _FetchContext, wanted: _Wanted) -> ModelRepoResult:
    """Answer for a repository the fetch ran out of time before downloading."""
    return wanted.result(
        ProvisionAction.FAILED,
        f"was not fetched: the {context.deadline_seconds:g} seconds allowed for "
        "the whole fetch had passed",
        MODELS_DEADLINE,
    )


def _download_repo(
    context: _FetchContext, wanted: _Wanted, *, repair: bool
) -> ModelRepoResult:
    """Download one repository, reporting its counts when a sink was given.

    With *repair* the files are fetched again even though the cache holds
    them, because one of them failed its check and the hub client would
    otherwise keep it. Either way the snapshot is checked again afterwards,
    and only a snapshot that passes is reported as downloaded.

    Every failure becomes a result rather than an exception: the caller goes
    on to the next repository, and an operator re-running the fetch to
    discover the next unavailable one is the cost of stopping at the first.
    """
    revision = wanted.revision
    heading = f"Downloading {wanted.label} {wanted.place}"
    progress = context.progress
    if progress is not None:
        progress.stage(f"{heading}...")
    outcome = download_snapshot(
        wanted.repo,
        revision=revision,
        force=repair,
        limits=context.limits,
        caller=DownloadCaller(
            on_progress=(
                None
                if progress is None
                else lambda counts: progress.downloading(heading, counts)
            ),
            # Asked before the first byte, because the alternative is a
            # download of several gigabytes that fails near its end.
            admit=lambda declared: _space_shortfall(context, wanted.repo, declared),
            until=context.until,
        ),
    )
    if outcome.failure is HubFailure.REFUSED:
        return wanted.result(ProvisionAction.FAILED, outcome.message, MODELS_NO_SPACE)
    if outcome.failure is not None:
        logger.error("model fetch failed for %s: %s", wanted.repo, outcome.message)
        return _failed(context, wanted, outcome.failure, outcome.message)
    if progress is not None:
        progress.stage(f"Verifying {wanted.label} {wanted.place}")
    fault = _fault(context, wanted)
    if fault is not None:
        logger.error("model fetch failed for %s: %s", wanted.repo, fault)
        return wanted.result(
            ProvisionAction.FAILED,
            f"was downloaded from {context.endpoint} and refused: {fault.detail}",
            MODELS_UNVERIFIED,
        )
    if repair:
        return wanted.result(ProvisionAction.UPDATED, "downloaded again")
    return wanted.result(ProvisionAction.CREATED, "downloaded")


def _failed(
    context: _FetchContext, wanted: _Wanted, failure: HubFailure, message: str
) -> ModelRepoResult:
    """Word one repository's failure under the code its cause is reported as."""
    if failure is HubFailure.NO_SPACE:
        detail = f"ran out of disk space in {context.cache} while downloading"
    elif failure is HubFailure.NOT_FOUND:
        detail = f"was not found on the hub: {message}"
    elif failure is HubFailure.UNTRUSTED_CERTIFICATE:
        detail = f"was refused: the certificate of {context.endpoint} is not trusted"
    elif failure in {HubFailure.STALLED, HubFailure.DIED, HubFailure.DEADLINE}:
        detail = message
    elif failure is HubFailure.CACHE:
        detail = f"could not be stored in the model cache: {message}"
    else:
        detail = f"failed: {message}"
    return wanted.result(ProvisionAction.FAILED, detail, _CODE_OF[failure])


def _space_shortfall(context: _FetchContext, repo: str, needed: int) -> str | None:
    """Say why *repo* cannot fit in the cache, or ``None`` when it can.

    *needed* is the size the hub declares for the revision, as the download
    process reported it; this process asks the hub nothing. The files of this
    repository the cache already holds are credited against it, since the hub
    client does not fetch a finished file again. A hub that declares no sizes
    cannot be judged, and neither can a volume that cannot be measured: the
    download goes ahead, and one that does not fit still ends as one outcome.

    Never raises: it is called while the download process waits for its
    answer, and an error here would leave it waiting.
    """
    from huggingface_hub.file_download import repo_folder_name

    blobs = context.cache / repo_folder_name(repo_id=repo, repo_type="model") / "blobs"
    try:
        held = (
            sum(entry.stat().st_size for entry in blobs.iterdir() if entry.is_file())
            if blobs.is_dir()
            else 0
        )
        free = shutil.disk_usage(_existing_ancestor(context.cache)).free
    except OSError as exc:
        logger.debug("free space in %s could not be measured: %s", context.cache, exc)
        return None
    if needed - held <= free:
        return None
    return (
        f"needs {human_bytes(needed - held)} more in {context.cache}, which has "
        f"{human_bytes(free)} free"
    )


def _existing_ancestor(path: Path) -> Path:
    """Return *path*, or its nearest ancestor that exists.

    A cache that has never been written to does not exist yet, and free space
    is a property of the volume it will be created on.
    """
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def _remedy(code: str, context: _FetchContext) -> str:
    """Say what to do about one kind of failure."""
    rerun = f"then run `{_WARMUP_COMMAND}`"
    without_this_link = (
        f"copy a complete model cache into {context.cache} and set "
        f"{EnvVar.HF_HUB_OFFLINE.value}=1, or point "
        f"{EnvVar.RAG_HF_ENDPOINT.value} at a mirror"
    )
    remedies = {
        MODELS_OFFLINE: (
            f"Unset {EnvVar.HF_HUB_OFFLINE.value} and "
            f"{EnvVar.TRANSFORMERS_OFFLINE.value}, {rerun} to download them."
        ),
        MODELS_NO_SPACE: (
            f"Free space on the volume holding {context.cache}, or set "
            f"{EnvVar.HF_HOME.value} to a directory on a larger one, {rerun}; "
            "files that finished downloading are kept."
        ),
        MODELS_NOT_FOUND: (
            f"The hub at {context.endpoint} has no such public repository or "
            f"revision. Correct the model setting that names it, {rerun}."
        ),
        MODELS_UNTRUSTED_CERTIFICATE: (
            "This host does not trust the certificate the hub presented, and "
            "verification is never skipped. For a mirror with a private "
            "certificate authority, set SSL_CERT_FILE to a PEM bundle that "
            "includes that authority, or SSL_CERT_DIR to a directory of such "
            f"certificates, {rerun}."
        ),
        MODELS_STALLED: (
            f"The link to {context.endpoint} is delivering too little to "
            f"finish. To fetch without it, {without_this_link}; {rerun}. "
            "Files that finished downloading are kept."
        ),
        MODELS_DOWNLOAD_DIED: (
            f"Run `{_WARMUP_COMMAND}` again; files that finished downloading "
            "are kept. If it ends the same way, the detail above is what to "
            "report."
        ),
        MODELS_BUSY: (f"Wait for that process to finish, {rerun}."),
        MODELS_DEADLINE: (
            f"One fetch is allowed {context.deadline_seconds:g} seconds in "
            "all, waiting for another fetch included. Files that finished "
            f"downloading are kept: run `{_WARMUP_COMMAND}` again to continue, "
            f"or raise {EnvVar.MODEL_FETCH_DEADLINE_SECONDS.value} for a link "
            "that needs longer."
        ),
        MODELS_CACHE_UNUSABLE: (
            "The hub was not the problem: a file or directory of the model "
            f"cache in {context.cache} could not be created, written or read. "
            "Make it writable by the account that runs this command, or set "
            f"{EnvVar.HF_HOME.value} to a directory that is, {rerun}."
        ),
        MODELS_UNVERIFIED: (
            "A model that fails its check is never loaded. A file that still "
            "does not match after being downloaded again means the hub at "
            f"{context.endpoint} is not serving the pinned release: if "
            f"{EnvVar.RAG_HF_ENDPOINT.value} names a mirror, point it at one "
            "that serves the official files. A file that is not part of the "
            "release has to be removed by hand; the detail above gives its "
            "path. A model with only pickle weights cannot be used; name one "
            "that ships safetensors. After any of these, run "
            f"`{_WARMUP_COMMAND}`."
        ),
    }
    return remedies.get(code) or (
        f"Check network access to {context.endpoint}, {rerun}; files that "
        "finished downloading are kept and an interrupted one is fetched "
        "again. On a link that goes quiet for longer than ten seconds at a "
        f"time, raise {EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value}, the hub "
        "client's per-read timeout in seconds."
    )


def _summarise(
    repos: tuple[ModelRepoResult, ...], context: _FetchContext
) -> ModelFetch:
    """Collapse the per-repository results into the outcome of the fetch."""
    failed = [result for result in repos if result.action == ProvisionAction.FAILED]
    if failed:
        return _summarise_failed(failed, repos, context)
    missing = _named(repos, ProvisionAction.DRY_RUN)
    if missing:
        return ModelFetch(
            ProvisionAction.DRY_RUN,
            f"would download {len(missing)} missing model repo(s): "
            + ", ".join(missing),
            repos=repos,
        )
    # Every successful outcome names the models nothing vouches for, so an
    # operator is told whichever command they ran.
    unpinned = [result.repo for result in repos if not result.pinned]
    unpinned_note = f"; unpinned: {', '.join(unpinned)}" if unpinned else ""
    downloaded = _named(repos, ProvisionAction.CREATED)
    repaired = _named(repos, ProvisionAction.UPDATED)
    parts = [
        f"{verb} {len(repos_of)} model repo(s): " + ", ".join(repos_of)
        for verb, repos_of in (
            ("downloaded", downloaded),
            ("downloaded again", repaired),
        )
        if repos_of
    ]
    if parts:
        return ModelFetch(
            ProvisionAction.CREATED if downloaded else ProvisionAction.UPDATED,
            "; ".join(parts) + unpinned_note,
            repos=repos,
        )
    return ModelFetch(
        ProvisionAction.UNCHANGED,
        f"all {len(repos)} model repos already cached" + unpinned_note,
        repos=repos,
    )


def _named(repos: tuple[ModelRepoResult, ...], action: ProvisionAction) -> list[str]:
    """Return the repositories whose result is *action*, in fetch order."""
    return [result.repo for result in repos if result.action == action]


def _summarise_failed(
    failed: list[ModelRepoResult],
    repos: tuple[ModelRepoResult, ...],
    context: _FetchContext,
) -> ModelFetch:
    """Word a fetch in which at least one repository failed."""
    # Offline explains a repository that is missing. One that is present and
    # refused is refused for its own reason, offline or not.
    if all(result.code == MODELS_OFFLINE for result in failed):
        return ModelFetch(
            ProvisionAction.FAILED,
            f"{len(failed)} of {len(repos)} model repos are not in the local "
            "cache and the Hugging Face hub is offline: "
            f"{', '.join(result.repo for result in failed)}. "
            + _remedy(MODELS_OFFLINE, context),
            MODELS_OFFLINE,
            repos,
        )
    codes = list(dict.fromkeys(result.code for result in failed))
    return ModelFetch(
        ProvisionAction.FAILED,
        f"{len(failed)} of {len(repos)} model repos could not be fetched: "
        f"{'; '.join(f'{result.repo} {result.detail}' for result in failed)}. "
        + " ".join(_remedy(code, context) for code in codes),
        # One reason names the failure; several different ones are a
        # failed fetch, and the detail says which repository had which.
        codes[0] if len(codes) == 1 else MODELS_FETCH_FAILED,
        repos,
    )
