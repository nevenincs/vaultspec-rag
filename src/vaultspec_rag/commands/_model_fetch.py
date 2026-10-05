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

This module decides; it downloads nothing itself. Each repository that needs
fetching is downloaded by a child process, because that is the only kind of
download that can always be stopped. A repository already in the cache costs
no process and no request.

Two bounds apply to a hub that misbehaves. One that goes silent is given up
on by the hub client itself: it abandons a request after its per-read timeout
with no bytes, and a file after six consecutive such attempts. One that keeps
sending too little to ever finish is stopped by the progress floor.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from .._sync_vocabulary import ProvisionAction
from .._units import human_bytes
from ..config._types import EnvVar, hf_cache_only
from ._hub_failure import HubFailure, classify_hub_failure, first_line
from ._model_download import (
    DEFAULT_LIMITS,
    FetchLimits,
    download_snapshot,
    exclusive_fetch,
)

if TYPE_CHECKING:
    from ._provision import ProvisionProgress

logger = logging.getLogger(__name__)

__all__ = [
    "MODELS_BUSY",
    "MODELS_DOWNLOAD_DIED",
    "MODELS_FETCH_FAILED",
    "MODELS_HUB_MISSING",
    "MODELS_NOT_FOUND",
    "MODELS_NO_SPACE",
    "MODELS_OFFLINE",
    "MODELS_STALLED",
    "MODELS_UNTRUSTED_CERTIFICATE",
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

#: The code each way a hub request can fail is reported under.
_CODE_OF = {
    HubFailure.UNREACHABLE: MODELS_FETCH_FAILED,
    HubFailure.NOT_FOUND: MODELS_NOT_FOUND,
    HubFailure.NO_SPACE: MODELS_NO_SPACE,
    HubFailure.UNTRUSTED_CERTIFICATE: MODELS_UNTRUSTED_CERTIFICATE,
    HubFailure.STALLED: MODELS_STALLED,
    HubFailure.DIED: MODELS_DOWNLOAD_DIED,
}

_WARMUP_COMMAND = "vaultspec-rag server warmup"


@dataclass(frozen=True, slots=True)
class ModelRepoResult:
    """What happened to one configured model repository.

    Attributes:
        label: The operator-facing name of the model's role.
        repo: The repository id.
        action: ``unchanged`` when already cached, ``created`` when
            downloaded, ``dry_run`` when a preview found it missing, and
            ``failed`` otherwise.
        detail: The same outcome in words, ready to follow the repo id.
        code: Why it failed, as one of the module's reason constants; empty
            unless ``action`` is ``failed``.
    """

    label: str
    repo: str
    action: ProvisionAction
    detail: str
    code: str = ""


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


class _HubApi(Protocol):
    """The one hub call the free-space check makes, as this module uses it."""

    def model_info(self, repo_id: str, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class _FetchContext:
    api: _HubApi
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


@dataclass(frozen=True, slots=True)
class _Wanted:
    """One repository of the inventory and where it stands in the run."""

    label: str
    repo: str
    place: str

    def result(
        self, action: ProvisionAction, detail: str, code: str = ""
    ) -> ModelRepoResult:
        return ModelRepoResult(self.label, self.repo, action, detail, code)


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
        from huggingface_hub import HfApi, constants
    except ImportError:
        return ModelFetch(
            ProvisionAction.FAILED,
            "huggingface_hub is not installed, so the model files cannot be "
            "checked or downloaded; reinstall vaultspec-rag",
            MODELS_HUB_MISSING,
        )

    from ..config._settings import configured_model_repos

    models = configured_model_repos()
    context = _FetchContext(
        # The hub ships partial stubs, so the imported symbol is only
        # partially typed; naming the shape this call site actually uses is
        # what keeps the strict gate honest.
        api=cast("_HubApi", HfApi()),
        progress=progress,
        limits=limits,
        total=len(models),
        dry_run=dry_run,
        offline=hf_cache_only(),
        cache=Path(constants.HF_HUB_CACHE),
        endpoint=constants.ENDPOINT,
    )
    repos = tuple(
        _fetch_repo(context, _Wanted(label, repo, f"({position}/{len(models)})"))
        for position, (label, repo) in enumerate(models, start=1)
    )
    return _summarise(repos, context)


def _fetch_repo(context: _FetchContext, wanted: _Wanted) -> ModelRepoResult:
    """Probe the cache for one repository and download it when it is absent."""
    from .._model_cache import cached_snapshot_is_complete

    if context.progress is not None:
        context.progress.stage(f"Checking the cache for {wanted.label} {wanted.place}")
    if cached_snapshot_is_complete(wanted.repo):
        return wanted.result(ProvisionAction.UNCHANGED, "cached")
    if context.dry_run:
        return wanted.result(ProvisionAction.DRY_RUN, "would be downloaded")
    if context.offline:
        return wanted.result(
            ProvisionAction.FAILED,
            "not in the local cache, and the hub is offline",
            MODELS_OFFLINE,
        )
    stage = None if context.progress is None else context.progress.stage
    with exclusive_fetch(context.cache, limits=context.limits, on_wait=stage) as busy:
        if busy is not None:
            return wanted.result(
                ProvisionAction.FAILED, f"not fetched: {busy}", MODELS_BUSY
            )
        # Whoever held the cache may have fetched this very repository.
        if cached_snapshot_is_complete(wanted.repo):
            return wanted.result(ProvisionAction.UNCHANGED, "cached")
        return _download_repo(context, wanted)


def _download_repo(context: _FetchContext, wanted: _Wanted) -> ModelRepoResult:
    """Download one repository, reporting its counts when a sink was given.

    Every failure becomes a result rather than an exception: the caller goes
    on to the next repository, and an operator re-running the fetch to
    discover the next unavailable one is the cost of stopping at the first.
    """
    from .._sparse_profile import sparse_model_revision

    revision = sparse_model_revision(wanted.repo)
    heading = f"Downloading {wanted.label} {wanted.place}"
    progress = context.progress
    try:
        shortfall = _space_shortfall(context, wanted.repo, revision)
    except Exception as exc:
        logger.error("model fetch failed for %s: %s", wanted.repo, exc)
        return _failed(context, wanted, classify_hub_failure(exc), first_line(exc))
    if shortfall is not None:
        return wanted.result(ProvisionAction.FAILED, shortfall, MODELS_NO_SPACE)
    if progress is not None:
        progress.stage(f"{heading}...")
    outcome = download_snapshot(
        wanted.repo,
        revision=revision,
        limits=context.limits,
        on_progress=(
            None
            if progress is None
            else lambda counts: progress.downloading(heading, counts)
        ),
    )
    if outcome.failure is not None:
        logger.error("model fetch failed for %s: %s", wanted.repo, outcome.message)
        return _failed(context, wanted, outcome.failure, outcome.message)
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
    elif failure in {HubFailure.STALLED, HubFailure.DIED}:
        detail = message
    else:
        detail = f"failed: {message}"
    return wanted.result(ProvisionAction.FAILED, detail, _CODE_OF[failure])


def _space_shortfall(
    context: _FetchContext, repo: str, revision: str | None
) -> str | None:
    """Say why *repo* cannot fit in the cache, or ``None`` when it can.

    Asked before the first byte, because the alternative is a download of
    several gigabytes that fails near its end. The size is the one the hub
    declares for the revision; the files of this repository the cache already
    holds are credited against it, since the hub client does not fetch a
    finished file again. A hub that declares no sizes cannot be judged, and
    the download goes ahead.

    Raises:
        Exception: Whatever the hub client raises when it cannot answer; the
            caller classifies it exactly as it would a failed download.
    """
    from huggingface_hub.file_download import repo_folder_name

    info = context.api.model_info(
        repo, revision=revision, files_metadata=True, token=False
    )
    siblings = cast("list[object]", getattr(info, "siblings", None) or [])
    declared = [getattr(sibling, "size", None) for sibling in siblings]
    needed = sum(size for size in declared if isinstance(size, int))
    blobs = context.cache / repo_folder_name(repo_id=repo, repo_type="model") / "blobs"
    held = (
        sum(entry.stat().st_size for entry in blobs.iterdir() if entry.is_file())
        if blobs.is_dir()
        else 0
    )
    free = shutil.disk_usage(_existing_ancestor(context.cache)).free
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

    def named(action: ProvisionAction) -> list[str]:
        return [result.repo for result in repos if result.action == action]

    failed = [result for result in repos if result.action == ProvisionAction.FAILED]
    if failed and context.offline:
        return ModelFetch(
            ProvisionAction.FAILED,
            f"{len(failed)} of {len(repos)} model repos are not in the local "
            "cache and the Hugging Face hub is offline: "
            f"{', '.join(result.repo for result in failed)}. "
            + _remedy(MODELS_OFFLINE, context),
            MODELS_OFFLINE,
            repos,
        )
    if failed:
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
    missing = named(ProvisionAction.DRY_RUN)
    if missing:
        return ModelFetch(
            ProvisionAction.DRY_RUN,
            f"would download {len(missing)} missing model repo(s): "
            + ", ".join(missing),
            repos=repos,
        )
    downloaded = named(ProvisionAction.CREATED)
    if downloaded:
        return ModelFetch(
            ProvisionAction.CREATED,
            f"downloaded {len(downloaded)} model repo(s): " + ", ".join(downloaded),
            repos=repos,
        )
    return ModelFetch(
        ProvisionAction.UNCHANGED,
        f"all {len(repos)} model repos already cached",
        repos=repos,
    )
