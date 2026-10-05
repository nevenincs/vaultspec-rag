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
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar, hf_cache_only

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from ._provision import ProvisionProgress

logger = logging.getLogger(__name__)

__all__ = [
    "MODELS_FETCH_FAILED",
    "MODELS_HUB_MISSING",
    "MODELS_OFFLINE",
    "ModelFetch",
    "ModelRepoResult",
    "fetch_models",
]

#: Machine-readable reasons a fetch failed, for callers that report the
#: failure under its own name.
MODELS_OFFLINE = "models_offline"
MODELS_FETCH_FAILED = "models_fetch_failed"
MODELS_HUB_MISSING = "models_hub_missing"

#: Seconds the hub may spend on one file. Its own default is ten, which a
#: multi-gigabyte weight file on an ordinary link does not survive.
_HUB_DOWNLOAD_TIMEOUT_SECONDS = "300"

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
    """

    label: str
    repo: str
    action: ProvisionAction
    detail: str


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
    download: Callable[..., object]
    progress: ProvisionProgress | None
    total: int
    dry_run: bool
    offline: bool
    cache: str


def fetch_models(
    *,
    dry_run: bool = False,
    progress: ProvisionProgress | None = None,
) -> ModelFetch:
    """Ensure every configured model repository is cached, downloading the rest.

    Idempotent: a fully cached inventory reports ``unchanged`` and never
    touches the network.

    Args:
        dry_run: Report what would be fetched without downloading it.
        progress: Where to report the probe and each download as they run;
            silent when omitted.

    Returns:
        The outcome of the whole fetch with one result per repository.
    """
    # The hub reads its per-file budget once, when it is first imported, so
    # the default has to be in the environment before that import.
    os.environ.setdefault(
        EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value, _HUB_DOWNLOAD_TIMEOUT_SECONDS
    )
    try:
        from huggingface_hub import (
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
        )
    except ImportError:
        return ModelFetch(
            ProvisionAction.FAILED,
            "huggingface_hub is not installed, so the model files cannot be "
            "checked or downloaded; reinstall vaultspec-rag with the gpu extra",
            MODELS_HUB_MISSING,
        )

    from ..config._settings import configured_model_repos, get_config

    models = configured_model_repos()
    context = _FetchContext(
        # The hub ships partial stubs, so the imported symbol is only
        # partially typed; naming the shape this call site actually uses is
        # what keeps the strict gate honest.
        download=cast("Callable[..., object]", snapshot_download),
        progress=progress,
        total=len(models),
        dry_run=dry_run,
        offline=hf_cache_only(),
        cache=get_config().hf_cache_location,
    )
    repos = tuple(
        _fetch_repo(context, label, repo, position)
        for position, (label, repo) in enumerate(models, start=1)
    )
    return _summarise(repos, offline=context.offline)


def _fetch_repo(
    context: _FetchContext, label: str, repo: str, position: int
) -> ModelRepoResult:
    """Probe the cache for one repository and download it when it is absent."""
    from .._model_cache import cached_snapshot_is_complete

    place = f"({position}/{context.total})"
    if context.progress is not None:
        context.progress.stage(f"Checking the cache for {label} {place}")
    if cached_snapshot_is_complete(repo):
        return ModelRepoResult(label, repo, ProvisionAction.UNCHANGED, "cached")
    if context.dry_run:
        return ModelRepoResult(
            label, repo, ProvisionAction.DRY_RUN, "would be downloaded"
        )
    if context.offline:
        return ModelRepoResult(
            label,
            repo,
            ProvisionAction.FAILED,
            "not in the local cache, and the hub is offline",
        )
    return _download_repo(context, label, repo, f"Downloading {label} {place}")


def _download_repo(
    context: _FetchContext, label: str, repo: str, heading: str
) -> ModelRepoResult:
    """Download one repository, reporting its bytes when a sink was given.

    Every failure becomes a result rather than an exception: the caller goes
    on to the next repository, and an operator re-running the fetch to
    discover the next unavailable one is the cost of stopping at the first.
    """
    from .._sparse_profile import sparse_model_revision

    scope: AbstractContextManager[type[Any] | None] = (
        contextlib.nullcontext()
        if context.progress is None
        else context.progress.download(heading)
    )
    try:
        with scope as bar_class:
            context.download(
                repo,
                tqdm_class=bar_class,
                revision=sparse_model_revision(repo),
                token=False,
            )
    except Exception as exc:
        logger.error("model fetch failed for %s: %s", repo, exc)
        # The cache location comes from the config rather than a default
        # spelled inline: an operator who set HF_HOME would otherwise be sent
        # to the library's default directory to clean up a partial download
        # that is not there.
        return ModelRepoResult(
            label,
            repo,
            ProvisionAction.FAILED,
            f"failed: {exc} (partial cache may remain in {context.cache})",
        )
    return ModelRepoResult(label, repo, ProvisionAction.CREATED, "downloaded")


def _summarise(repos: tuple[ModelRepoResult, ...], *, offline: bool) -> ModelFetch:
    """Collapse the per-repository results into the outcome of the fetch."""

    def named(action: ProvisionAction) -> list[str]:
        return [result.repo for result in repos if result.action == action]

    failed = [result for result in repos if result.action == ProvisionAction.FAILED]
    if failed and offline:
        return ModelFetch(
            ProvisionAction.FAILED,
            f"{len(failed)} of {len(repos)} model repos are not in the local "
            "cache and the Hugging Face hub is offline: "
            f"{', '.join(result.repo for result in failed)}. Unset "
            f"{EnvVar.HF_HUB_OFFLINE.value} and "
            f"{EnvVar.TRANSFORMERS_OFFLINE.value}, then run `{_WARMUP_COMMAND}` "
            "to download them.",
            MODELS_OFFLINE,
            repos,
        )
    if failed:
        return ModelFetch(
            ProvisionAction.FAILED,
            f"{len(failed)} of {len(repos)} model repos failed to download: "
            f"{'; '.join(f'{result.repo} {result.detail}' for result in failed)}. "
            "Check network access to the Hugging Face Hub, then run "
            f"`{_WARMUP_COMMAND}`.",
            MODELS_FETCH_FAILED,
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
