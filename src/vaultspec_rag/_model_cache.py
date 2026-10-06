"""Torch-free checks that a cached model snapshot is what it should be.

Two questions are answered here, and they are kept apart on purpose.

*Is it there?* :func:`cached_snapshot_is_complete` looks at which files a
snapshot holds and reads none of them. It is cheap enough for a status
surface, and it proves nothing about content, so nothing built on it may
describe a model as verified.

*Is it the reviewed model?* :func:`verified_snapshot` hashes every file of a
default model against the digests committed for its pinned commit, and yields
the directory only when the snapshot matches file for file. That is the check
a fetch finishes with and every load begins with. A model an operator named
has no committed digests; for it the same call checks structure and weight
format, and its callers report it as unpinned.

Nothing here downloads. Fetching belongs to the provisioning command; a load
goes through :func:`loadable_snapshot`, reads the cache only, and stops with
the command to run when the cache cannot supply a snapshot that passes.

How long the check stays true depends on the platform, and the difference is
a security property:

Windows
    Every file is opened without write or delete sharing before it is hashed
    and stays open until the caller has finished loading. Nothing can rewrite,
    rename, remove or replace a file that was hashed, or rename a directory
    above it, while the loader reads it. A file can still be *added* to the
    directory, which no handle prevents; the directory is listed again when
    the caller is done and an addition fails the load before the model is
    handed to anyone.

Elsewhere
    Nothing stops a process that can write the model cache from replacing a
    file between the hash and the loader's own read of it. That window is
    not closed here and cannot be without loading from memory, which the
    model libraries do not offer for these files. What it exposes is limited
    by two other rules: weights are read from safetensors only, so a swapped
    weight file is wrong numbers and not executed code, and the one source
    file a default model executes is imported from the very buffer that was
    hashed, never read a second time.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from contextlib import ExitStack, contextmanager
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ._model_pins import committed_manifest

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from io import BufferedReader

__all__ = [
    "ModelSnapshotError",
    "SnapshotFault",
    "VerifiedSnapshot",
    "cached_snapshot_is_complete",
    "loadable_snapshot",
    "verified_snapshot",
    "verify_snapshot",
]

_TOKENIZER_FILENAMES = frozenset(
    {
        "tokenizer.json",
        "tokenizer.model",
        "vocab.json",
        "vocab.txt",
        "spiece.model",
        "sentencepiece.bpe.model",
    },
)


class SnapshotFault(StrEnum):
    """Why a snapshot cannot be used, in terms a caller can act on."""

    #: No snapshot of that repository at that commit is in the cache.
    ABSENT = "absent"
    #: A file the model needs is not in the snapshot.
    INCOMPLETE = "incomplete"
    #: The snapshot holds a file the committed manifest does not list.
    EXTRA_FILE = "extra_file"
    #: A file's content differs from its committed digest.
    MISMATCH = "mismatch"
    #: The model ships its weights only in a pickle format.
    PICKLE_ONLY = "pickle_only"
    #: A file could not be held, because something has it open for writing.
    IN_USE = "in_use"


class ModelSnapshotError(RuntimeError):
    """A model snapshot is absent, incomplete, altered, or not loadable.

    Attributes:
        repo: The repository the snapshot belongs to.
        fault: What is wrong with it.
        detail: The fault in words, phrased to follow the repository's name.
        file: The file at fault, relative to the snapshot, when one is.
    """

    def __init__(
        self, repo: str, fault: SnapshotFault, detail: str, *, file: str | None = None
    ) -> None:
        super().__init__(f"model {repo}: {detail}")
        self.repo = repo
        self.fault = fault
        self.detail = detail
        self.file = file

    @property
    def fetchable(self) -> bool:
        """Whether downloading the snapshot can be expected to cure the fault.

        A missing snapshot or file is cured by fetching it. A file with the
        wrong content is cured by fetching it again, provided the hub serves
        the pinned content. An extra file is not cured by any download, and a
        model with no safetensors weights has none to fetch.
        """
        return self.fault in {
            SnapshotFault.ABSENT,
            SnapshotFault.INCOMPLETE,
            SnapshotFault.MISMATCH,
        }


class VerifiedSnapshot(Protocol):
    """A snapshot directory that passed its check, and its held files."""

    @property
    def directory(self) -> Path:
        """The snapshot directory to load from."""
        ...

    def read(self, name: str) -> bytes:
        """Return the whole content of *name* through its held handle."""
        ...


class _SnapshotLoader(Protocol):
    def snapshot_download(self, model_id: str, **kwargs: object) -> str: ...


def _locate(repo: str, revision: str | None, cache_dir: Path | None) -> Path | None:
    """Return the cached snapshot directory, asking the hub nothing."""
    import huggingface_hub

    hub = cast("_SnapshotLoader", huggingface_hub)
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return Path(
            hub.snapshot_download(
                repo, revision=revision, cache_dir=cache_dir, local_files_only=True
            )
        )
    except (LocalEntryNotFoundError, OSError):
        return None


def _listed(snapshot: Path) -> dict[str, Path]:
    """Return every file in *snapshot*, keyed by its forward-slash name.

    A broken link is listed too: it is an entry in the directory that names
    nothing, and a caller has to see it to report the file as missing.
    """
    return {
        path.relative_to(snapshot).as_posix(): path
        for path in snapshot.rglob("*")
        if path.is_file() or path.is_symlink()
    }


def _structural_fault(
    repo: str, files: Mapping[str, Path], manifest: Mapping[str, str] | None
) -> ModelSnapshotError | None:
    """Return what is wrong with the set of files present, reading none."""
    if manifest is not None:
        for name in sorted(manifest):
            path = files.get(name)
            if path is None or not path.is_file():
                return ModelSnapshotError(
                    repo,
                    SnapshotFault.INCOMPLETE,
                    f"the snapshot is missing {name}",
                    file=name,
                )
        for name in sorted(files):
            if name not in manifest:
                return ModelSnapshotError(
                    repo,
                    SnapshotFault.EXTRA_FILE,
                    f"the snapshot holds {name}, which is not part of the "
                    f"pinned release; remove {files[name]}",
                    file=name,
                )
        return None
    present = {name for name, path in files.items() if path.is_file()}
    if "config.json" not in present:
        return ModelSnapshotError(
            repo,
            SnapshotFault.INCOMPLETE,
            "the snapshot is missing config.json",
            file="config.json",
        )
    if not any(name.rsplit("/", 1)[-1] in _TOKENIZER_FILENAMES for name in present):
        return ModelSnapshotError(
            repo, SnapshotFault.INCOMPLETE, "the snapshot holds no tokenizer file"
        )
    return _weights_fault(repo, files, present)


def _weights_fault(
    repo: str, files: Mapping[str, Path], present: set[str]
) -> ModelSnapshotError | None:
    """Return what is wrong with the snapshot's weights, if anything.

    Weights are accepted in the safetensors format only. A pickle weight file
    is executable content from whatever endpoint served it, so a model that
    ships nothing else is refused, and said to be refused for that reason
    rather than reported as merely incomplete.
    """
    for index in sorted(
        name for name in present if name.endswith(".safetensors.index.json")
    ):
        shards = _declared_shards(files[index])
        if shards is None:
            continue
        missing = _missing_shard(index, shards, present)
        if missing is None:
            return None
        return ModelSnapshotError(
            repo,
            SnapshotFault.INCOMPLETE,
            f"the snapshot is missing weight shard {missing}",
            file=missing,
        )
    if any(name.endswith(".safetensors") for name in present):
        return None
    pickled = sorted(
        name
        for name in present
        if name.rsplit("/", 1)[-1].startswith("pytorch_model") and name.endswith(".bin")
    )
    if pickled:
        return ModelSnapshotError(
            repo,
            SnapshotFault.PICKLE_ONLY,
            f"it ships its weights only as {pickled[0]}, a pickle file; "
            "weights are loaded from the safetensors format only, so this "
            "model cannot be used",
            file=pickled[0],
        )
    return ModelSnapshotError(
        repo, SnapshotFault.INCOMPLETE, "the snapshot holds no safetensors weights"
    )


def _declared_shards(index: Path) -> set[object] | None:
    """Return the weight files a shard index names, or ``None`` when it names none.

    An index that cannot be read, or that declares no weights, says nothing
    about which shards the model needs, so it is passed over rather than
    taken as a complete model.
    """
    try:
        payload = cast("dict[str, object]", json.loads(index.read_text("utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
    weight_map = payload.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        return None
    return set(cast("dict[object, object]", weight_map).values())


def _missing_shard(index: str, shards: set[object], present: set[str]) -> str | None:
    """Return a shard *index* names that the snapshot does not hold, if any."""
    folder = index.rsplit("/", 1)[0] + "/" if "/" in index else ""
    for shard in shards:
        if not isinstance(shard, str) or folder + shard not in present:
            return f"{folder}{shard}"
    return None


def cached_snapshot_is_complete(
    repo: str,
    *,
    revision: str | None,
    cache_dir: Path | None = None,
) -> bool:
    """Return whether every file a snapshot needs is present, reading none.

    A structural answer only, cheap enough for a status surface. It does not
    hash anything, so it is not evidence about content: a complete snapshot
    of a pinned model has the files the pinned release has, and may still
    fail :func:`verified_snapshot`.

    Args:
        repo: The hub repository id.
        revision: The commit the snapshot must be for; ``None`` judges the
            snapshot the default branch last resolved to.
        cache_dir: The hub cache to look in; the client's own when omitted.
    """
    snapshot = _locate(repo, revision, cache_dir)
    if snapshot is None:
        return False
    manifest = committed_manifest(repo, revision)
    return _structural_fault(repo, _listed(snapshot), manifest) is None


class _Held:
    """The files of one snapshot, open for as long as a load takes."""

    def __init__(self, directory: Path, readers: dict[str, BufferedReader]) -> None:
        self.directory = directory
        self._readers = readers

    def read(self, name: str) -> bytes:
        reader = self._readers[name]
        reader.seek(0)
        return reader.read()

    def sha256(self, name: str) -> str:
        reader = self._readers[name]
        reader.seek(0)
        return hashlib.file_digest(reader, "sha256").hexdigest()


def _hold(stack: ExitStack, path: Path) -> BufferedReader:
    """Open *path* for reading and keep it open until *stack* unwinds.

    On Windows the entry itself is opened with no write or delete sharing,
    and when it is a link the file it names is opened the same way, so
    neither the name nor the content behind it can change while it is held.
    Elsewhere this is an ordinary open, which pins nothing.
    """
    if sys.platform != "win32":
        return stack.enter_context(path.open("rb"))

    from ._win32 import open_without_following

    entry = stack.enter_context(
        os.fdopen(open_without_following(str(path), share_write=False), "rb")
    )
    attributes = getattr(os.fstat(entry.fileno()), "st_file_attributes", 0)
    if not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return entry
    target = Path(os.path.realpath(path))
    content = stack.enter_context(
        os.fdopen(open_without_following(str(target), share_write=False), "rb")
    )
    status = os.fstat(content.fileno())
    target_attributes = getattr(status, "st_file_attributes", 0)
    if target_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or not stat.S_ISREG(
        status.st_mode
    ):
        raise OSError(f"{path} does not lead to a regular file")
    return content


@contextmanager
def verified_snapshot(
    repo: str,
    *,
    revision: str | None,
    cache_dir: Path | None = None,
) -> Generator[VerifiedSnapshot]:
    """Yield the cached snapshot of *repo*, checked and held for the block.

    For a model with a committed manifest every file is hashed and compared.
    For any other model the file set and the weight format are checked. The
    files stay open for the block, and the directory is listed again on the
    way out, so a caller that loads inside the block and returns its result
    only after leaving it never returns a model built from a snapshot that
    changed underneath it.

    Args:
        repo: The hub repository id.
        revision: The commit the snapshot must be for, or ``None``.
        cache_dir: The hub cache to look in; the client's own when omitted.

    Raises:
        ModelSnapshotError: If the snapshot is absent, incomplete, holds an
            extra file, differs from its manifest, or ships only pickle
            weights. The file at fault is named.
    """
    snapshot = _locate(repo, revision, cache_dir)
    if snapshot is None:
        raise ModelSnapshotError(
            repo,
            SnapshotFault.ABSENT,
            "no snapshot of it"
            + (f" at commit {revision}" if revision else "")
            + " is in the model cache",
        )
    with checked_directory(repo, snapshot, committed_manifest(repo, revision)) as held:
        yield held


@contextmanager
def checked_directory(
    repo: str, snapshot: Path, manifest: Mapping[str, str] | None
) -> Generator[VerifiedSnapshot]:
    """Check one snapshot directory against *manifest* and hold it for the block.

    The whole of the check, apart from finding the directory and choosing the
    manifest: the file set, the holds, the hashing, and the second listing on
    the way out. With no manifest only the file set and weight format are
    judged.

    Raises:
        ModelSnapshotError: As :func:`verified_snapshot`.
    """
    files = _listed(snapshot)
    fault = _structural_fault(repo, files, manifest)
    if fault is not None:
        raise fault
    with ExitStack() as stack:
        readers: dict[str, BufferedReader] = {}
        for name in sorted(files):
            try:
                readers[name] = _hold(stack, files[name])
            except OSError as exc:
                raise ModelSnapshotError(
                    repo,
                    SnapshotFault.IN_USE,
                    f"{name} could not be opened for an exclusive read ({exc}); "
                    "another process may be writing the model cache",
                    file=name,
                ) from exc
        held = _Held(snapshot, readers)
        for name, expected in sorted((manifest or {}).items()):
            if held.sha256(name) != expected:
                raise ModelSnapshotError(
                    repo,
                    SnapshotFault.MISMATCH,
                    f"{name} does not match the SHA256 committed for the "
                    "pinned release",
                    file=name,
                )
        yield held
        added = sorted(set(_listed(snapshot)) - set(files))
        if added:
            raise ModelSnapshotError(
                repo,
                SnapshotFault.EXTRA_FILE,
                f"{added[0]} appeared in the snapshot while it was being "
                "loaded; the model was discarded",
                file=added[0],
            )


def verify_snapshot(
    repo: str,
    *,
    revision: str | None,
    cache_dir: Path | None = None,
) -> None:
    """Check the cached snapshot of *repo* and return only if it passes.

    The check a fetch ends with. Nothing is held once this returns, so a
    process that goes on to load the model checks again as it loads.

    Raises:
        ModelSnapshotError: As :func:`verified_snapshot`.
    """
    with verified_snapshot(repo, revision=revision, cache_dir=cache_dir):
        pass


_WARMUP = "vaultspec-rag server warmup"
_DOCTOR = "vaultspec-rag server doctor"

# What an operator does about each fault when it stops a load. A load never
# downloads, so every remedy is a command run before the next attempt.
_LOAD_REMEDIES: dict[SnapshotFault, str] = {
    SnapshotFault.ABSENT: (
        f"Nothing is downloaded while a model loads; run '{_WARMUP}' to fetch it"
    ),
    SnapshotFault.INCOMPLETE: (
        f"Nothing is downloaded while a model loads; run '{_WARMUP}' to fetch "
        "what is missing"
    ),
    SnapshotFault.MISMATCH: (
        f"Run '{_WARMUP}' to fetch the pinned files again, then '{_DOCTOR}' "
        "to confirm the model cache passes"
    ),
    SnapshotFault.EXTRA_FILE: (
        f"Once it is removed, run '{_DOCTOR}' to confirm the model cache passes"
    ),
    SnapshotFault.PICKLE_ONLY: (
        "Name a model that ships safetensors weights, or unset the model "
        "setting to use the default"
    ),
    SnapshotFault.IN_USE: (
        "Wait for whatever is writing the model cache to finish, then run "
        f"'{_DOCTOR}' to confirm it passes"
    ),
}


@contextmanager
def loadable_snapshot(
    repo: str,
    *,
    revision: str | None,
) -> Generator[VerifiedSnapshot]:
    """Yield the verified snapshot a model is loaded from; never fetch one.

    The one way a model reaches a loader. The cache is the only source: a
    load that could download would fetch gigabytes inside a process that is
    starting or answering a search, under none of the provisioning command's
    progress, timeout or one-at-a-time rules. So a snapshot that is absent or
    fails its check stops the load, and the refusal names the command that
    cures it.

    Args:
        repo: The hub repository id.
        revision: The commit to load, or ``None`` for an unpinned model.

    Raises:
        ModelSnapshotError: If the cache holds no snapshot that passes the
            check. Its text is the fault followed by what to run.
    """
    try:
        with verified_snapshot(repo, revision=revision) as snapshot:
            yield snapshot
    except ModelSnapshotError as exc:
        raise ModelSnapshotError(
            exc.repo,
            exc.fault,
            f"{exc.detail}. {_LOAD_REMEDIES[exc.fault]}.",
            file=exc.file,
        ) from exc
