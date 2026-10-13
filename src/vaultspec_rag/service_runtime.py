"""The private environment the daemon runs in when its launcher cannot serve.

The daemon is GPU-only, and the environment that launches ``server start`` is
often not one that can run it: a uvx cache environment, a client installation,
or a pip install on a platform whose published torch is CPU-only. Rather than
refuse those launchers, the start builds one environment of its own, holding
exactly the launching release of this package with its GPU extra, and runs the
daemon from there.

Three properties make that safe to do on a start:

- **It is ours.** The runtime lives under the managed service directory, one
  directory per release. No environment the operator installed is read,
  written, replaced or removed.
- **It is the same release.** A client refuses a service from another release,
  so the requirement names the installed version, or the same archive the
  launching distribution itself came from. A checkout cannot be reproduced and
  is refused instead.
- **It is published whole.** The build happens in a staging directory under an
  exclusive lock and becomes the release directory by one rename, with its
  completion record written first. A build that fails or cannot run the
  service is deleted, so a present runtime is always a complete one and costs
  no network on the next start.

Nothing here imports torch: what the new environment can do is asked of the
new environment, in a child of its own interpreter.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from typing import TYPE_CHECKING, cast

from ._program_lookup import Where, find_program
from ._store_locks import FileLock
from .config._types import EnvVar
from .operator_state._provisioning import (
    CU130_INDEX_STRATEGY,
    HOST_PYTHON,
    host_install_command,
)
from .operator_state._topology import (
    RuntimeEnvKind,
    classify_environment,
    environment_root,
)
from .torch_config._index import CU130_INDEX_URL

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from .operator_state._service_environment import ServiceEnvironment

__all__ = [
    "RUNTIME_DIR_NAME",
    "RUNTIME_RECORD_NAME",
    "RUNTIME_REQUEST",
    "ManagedRuntime",
    "RuntimeRequirement",
    "ServiceInterpreterPlan",
    "ServiceInterpreterSource",
    "ServiceRuntimeError",
    "ensure_service_runtime",
    "install_arguments",
    "planned_service_interpreter",
    "remove_superseded_runtimes",
    "runtime_interpreter",
    "runtime_requirement",
    "runtime_root",
    "uv_executable",
    "uv_install_command",
    "venv_arguments",
]

#: The directory under the managed service directory holding every runtime.
RUNTIME_DIR_NAME = "runtime"

#: The completion record a published runtime carries. Its presence is what
#: makes a release directory usable: a directory without it is a build that
#: did not finish, and is rebuilt rather than run.
RUNTIME_RECORD_NAME = "runtime.json"

#: The distribution the runtime holds, with the extra that carries inference.
#: The MCP adapter is not among them: the runtime runs the daemon and nothing
#: else, and the adapter launches from the operator's own installation.
RUNTIME_REQUEST = "vaultspec-rag[gpu]"

#: The distribution name on its own, for reading the launching release.
_DISTRIBUTION = "vaultspec-rag"

#: Error codes a start reports for a runtime it could not use. Distinct from
#: the launching environment's own refusal, because the remedy is different:
#: nothing an operator does to their own environment changes these.
ERROR_RUNTIME_UNSUPPORTED = "service_runtime_unsupported"
ERROR_RUNTIME_FAILED = "service_runtime_failed"
ERROR_RUNTIME_NO_GPU = "service_runtime_no_gpu"

#: Where a staging build lives while it is being written. Named so a sweep can
#: tell one from a published release directory without parsing a version.
_STAGING_PREFIX = ".staging-"

#: The lock one build holds. A second start waits this long for it and then
#: says so, rather than downloading several gigabytes a second time.
_LOCK_NAME = ".runtime.lock"
_LOCK_WAIT_SECONDS = 20.0
_LOCK_POLL_SECONDS = 0.5

#: Bounds for the two uv steps. Creating the environment is a local operation;
#: installing it pulls the GPU stack over the network, which is several
#: gigabytes and is allowed the better part of an hour.
_VENV_TIMEOUT_SECONDS = 300.0
_INSTALL_TIMEOUT_SECONDS = 3600.0


class ServiceRuntimeError(Exception):
    """The managed runtime cannot be used, as the operator should read it.

    Attributes:
        code: The stable code the start reports the failure under.
        cause: One sentence naming what is wrong.
        command: The one command that moves the operator forward, or ``None``
            when there is none to offer.
        detail: The underlying diagnosis, for the structured outcome.
    """

    def __init__(
        self,
        code: str,
        cause: str,
        *,
        command: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(cause)
        self.code = code
        self.cause = cause
        self.command = command
        self.detail = detail or cause


class ServiceInterpreterSource(StrEnum):
    """Where the interpreter that would run the daemon comes from."""

    #: The environment that launched the command can serve, and will.
    LAUNCHING = "launching"
    #: A complete managed runtime is present and would serve.
    RUNTIME = "runtime"
    #: The launcher cannot serve and no runtime is present yet. Only
    #: ``server start`` creates one, so every other surface reports this as
    #: "not ready" rather than resolving an interpreter.
    RUNTIME_REQUIRED = "runtime_required"


@dataclass(frozen=True, slots=True)
class ServiceInterpreterPlan:
    """Which interpreter a ``server start`` would run the daemon from.

    Attributes:
        source: Where that interpreter comes from.
        interpreter: The interpreter itself, or ``None`` when a runtime would
            have to be created first.
        runtime_dir: This release's runtime directory, for the two sources
            that involve one.
    """

    source: ServiceInterpreterSource
    interpreter: str | None
    runtime_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class RuntimeRequirement:
    """What uv is asked to install, and where it comes from.

    Attributes:
        requirement: The requirement string handed to uv.
        source: The origin, for the completion record: the package index, or
            the archive the launching distribution itself came from.
    """

    requirement: str
    source: str


@dataclass(frozen=True, slots=True)
class ManagedRuntime:
    """A runtime that is present, complete and judged.

    Attributes:
        interpreter: The interpreter the daemon runs from.
        directory: The published release directory.
        environment: What that interpreter can do, judged in a child of it.
        created: Whether this start built it, as opposed to finding it.
        source: Where the release came from, from the completion record.
    """

    interpreter: str
    directory: Path
    environment: ServiceEnvironment
    created: bool
    source: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view for the start envelope."""
        return {
            "interpreter": self.interpreter,
            "directory": str(self.directory),
            "created": self.created,
            "source": self.source,
            "capability": str(self.environment.capability),
        }


def installed_release() -> str:
    """The release of this package, which the runtime must hold exactly."""
    return metadata.version(_DISTRIBUTION)


def runtime_root() -> Path:
    """The directory holding every release's runtime."""
    from .config._settings import managed_status_dir

    return managed_status_dir() / RUNTIME_DIR_NAME


def release_runtime_dir(release: str | None = None) -> Path:
    """The runtime directory for one release, published or not yet built."""
    return runtime_root() / (installed_release() if release is None else release)


def runtime_interpreter(directory: Path) -> Path:
    """The interpreter inside an environment rooted at *directory*."""
    if sys.platform == "win32":
        return directory / "Scripts" / "python.exe"
    return directory / "bin" / "python"


def read_runtime_record(directory: Path) -> dict[str, object] | None:
    """The completion record of *directory*, or ``None`` when it has none.

    An absent, unreadable or malformed record is an ordinary state - an
    interrupted build leaves one - so every caller gets a value to branch on.
    """
    try:
        parsed: object = json.loads(
            (directory / RUNTIME_RECORD_NAME).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else None


def complete_runtime(release: str | None = None) -> Path | None:
    """The published runtime directory for *release*, or ``None``.

    Complete means both halves: a record naming this release, and the
    interpreter it describes. Either one alone is a build that was interrupted.
    """
    wanted = installed_release() if release is None else release
    directory = release_runtime_dir(wanted)
    record = read_runtime_record(directory)
    if record is None or record.get("release") != wanted:
        return None
    if not runtime_interpreter(directory).is_file():
        return None
    return directory


def planned_service_interpreter(
    launching: ServiceEnvironment,
) -> ServiceInterpreterPlan:
    """Which interpreter would run the daemon, deciding nothing and writing nothing.

    Reads the judgement a caller already made of the launching environment and
    the state of the runtime directory, and answers the question every surface
    asks: what would a ``server start`` serve from. Creates nothing - a
    ``RUNTIME_REQUIRED`` plan is the honest answer for a launcher that cannot
    serve before a runtime exists, and only ``server start`` turns that into a
    runtime.

    A uvx cache environment is refused even when it can serve: uv prunes and
    replaces such an environment at any time, and the daemon outlives the run
    that created it.
    """
    interpreter = launching.interpreter
    kind = classify_environment(environment_root(interpreter))
    if launching.can_run_service and kind is not RuntimeEnvKind.UVX_EPHEMERAL:
        return ServiceInterpreterPlan(ServiceInterpreterSource.LAUNCHING, interpreter)
    directory = complete_runtime()
    if directory is not None:
        return ServiceInterpreterPlan(
            ServiceInterpreterSource.RUNTIME,
            str(runtime_interpreter(directory)),
            directory,
        )
    return ServiceInterpreterPlan(
        ServiceInterpreterSource.RUNTIME_REQUIRED, None, release_runtime_dir()
    )


def distribution_origin() -> Mapping[str, object] | None:
    """What the launching distribution records about where it came from.

    ``None`` means it came from a package index, which is both the common case
    and the one an index requirement reproduces exactly.
    """
    try:
        recorded = metadata.distribution(_DISTRIBUTION).read_text("direct_url.json")
    except (metadata.PackageNotFoundError, OSError):
        return None
    if not recorded:
        return None
    try:
        parsed: object = json.loads(recorded)
    except ValueError:
        return None
    return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else None


def runtime_requirement(
    release: str, origin: Mapping[str, object] | None
) -> RuntimeRequirement:
    """The requirement that reproduces *release* from where it came from.

    An index install is named by version. An install from a wheel file or a
    URL is named by that same archive, so the runtime holds the build the
    operator chose rather than whatever the index publishes under the version.

    Raises:
        ServiceRuntimeError: The launching distribution is a checkout - an
            editable or source install - which no requirement reproduces.
    """
    if origin is None:
        return RuntimeRequirement(f"{RUNTIME_REQUEST}=={release}", "index")
    url = origin.get("url")
    if isinstance(url, str) and url and "archive_info" in origin:
        return RuntimeRequirement(f"{RUNTIME_REQUEST} @ {url}", url)
    raise ServiceRuntimeError(
        ERROR_RUNTIME_UNSUPPORTED,
        "This installation is a source checkout, which the service runtime "
        "cannot reproduce, so the service has no environment to run in.",
        command=host_install_command(),
        detail=f"direct_url.json records {url or 'a local directory'}",
    )


def uv_executable() -> str | None:
    """The uv that creates the runtime, as an absolute path, or ``None``.

    uv names itself to its children, which is the only reading that is right
    when more than one uv is installed: the one running this command is the
    one the operator invoked. Otherwise an absolute uv on the search path,
    found without consulting the working directory.
    """
    named = os.environ.get(EnvVar.UV.value, "").strip()
    if named and os.path.isfile(named):
        return named
    return find_program("uv", Where.SEARCH_PATH)


def uv_install_command(platform_name: str | None = None) -> str:
    """The one command that installs uv on this platform."""
    if (sys.platform if platform_name is None else platform_name) == "win32":
        return (
            'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/'
            'install.ps1 | iex"'
        )
    return "curl -LsSf https://astral.sh/uv/install.sh | sh"


def venv_arguments(uv: str, staging: Path) -> tuple[str, ...]:
    """The uv call that creates the runtime's empty environment."""
    return (uv, "venv", "--python", HOST_PYTHON, str(staging))


def install_arguments(
    uv: str,
    interpreter: Path,
    requirement: RuntimeRequirement,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """The uv call that fills the runtime with this release and its GPU stack.

    The CUDA index and the strategy that reaches it are added where PyTorch
    publishes accelerated wheels under them. Apple silicon takes PyPI's own
    wheel, which is the one carrying Metal support.
    """
    platform_name = sys.platform if platform_name is None else platform_name
    arguments = (
        uv,
        "pip",
        "install",
        "--python",
        str(interpreter),
        requirement.requirement,
    )
    if platform_name in {"win32", "linux"}:
        arguments += (
            "--index",
            CU130_INDEX_URL,
            "--index-strategy",
            CU130_INDEX_STRATEGY,
        )
    return arguments


def ensure_service_runtime(
    *, stage: Callable[[str], None] | None = None
) -> ManagedRuntime:
    """Return a complete, judged runtime for this release, creating one if needed.

    A present runtime is judged and returned, which costs no network at all. A
    missing one is built under the exclusive lock, judged before it is
    published, and published by one rename.

    Args:
        stage: Where to report the activity now running, when the caller has
            somewhere to report it.

    Raises:
        ServiceRuntimeError: The runtime cannot be created, or the one that
            exists cannot run the service.
    """
    present = complete_runtime()
    if present is not None:
        return _judged(present, created=False)
    return _create_runtime(stage)


def _judge(interpreter: str) -> ServiceEnvironment:
    """Ask a runtime's own interpreter what it can do, and refuse what it cannot.

    No CPU runtime is ever accepted: the judgement is the one a start makes of
    any environment, and a refusal here is one sentence with at most the one
    command that can change the answer.

    Raises:
        ServiceRuntimeError: That interpreter cannot run the service.
    """
    from .operator_state._service_environment import judge_foreign_environment

    environment = judge_foreign_environment(interpreter)
    if not environment.can_run_service:
        raise ServiceRuntimeError(
            ERROR_RUNTIME_NO_GPU,
            f"The service runtime cannot run the GPU-only service: "
            f"{environment.reason}.",
            command=environment.capability.remediation,
            detail=environment.reason,
        )
    return environment


def _judged(directory: Path, *, created: bool) -> ManagedRuntime:
    """Judge a published runtime and describe it for the start that will use it."""
    interpreter = str(runtime_interpreter(directory))
    environment = _judge(interpreter)
    source = (read_runtime_record(directory) or {}).get("source")
    return ManagedRuntime(
        interpreter=interpreter,
        directory=directory,
        environment=environment,
        created=created,
        source=source if isinstance(source, str) else "",
    )


def _create_runtime(stage: Callable[[str], None] | None) -> ManagedRuntime:
    """Build this release's runtime and publish it, holding the lock throughout.

    The lock covers the whole build, not just the rename: two starts that both
    built would download the GPU stack twice and then race on one directory.
    """
    release = installed_release()
    requirement = runtime_requirement(release, distribution_origin())
    uv = uv_executable()
    if uv is None:
        raise ServiceRuntimeError(
            ERROR_RUNTIME_UNSUPPORTED,
            "The service needs its own GPU environment and uv creates it, but "
            "uv was not found.",
            command=uv_install_command(),
        )
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    with _publish_lock(root):
        # Another start may have published while this one waited for the lock.
        present = complete_runtime(release)
        if present is not None:
            return _judged(present, created=False)
        if stage is not None:
            stage(
                "Creating the service runtime (downloading the GPU stack, "
                "once per release)..."
            )
        staging = root / f"{_STAGING_PREFIX}{os.getpid()}-{uuid.uuid4().hex}"
        try:
            runtime = _build(uv, staging, release, requirement)
        finally:
            _discard(staging)
    return runtime


def _build(
    uv: str, staging: Path, release: str, requirement: RuntimeRequirement
) -> ManagedRuntime:
    """Create, fill, judge and publish one runtime from *staging*.

    The judgement comes before the completion record and the record before the
    rename, so nothing a start would refuse is ever published, and a directory
    carrying a record is a directory that was judged able to serve.
    """
    _run_uv(
        venv_arguments(uv, staging),
        "create the environment",
        _VENV_TIMEOUT_SECONDS,
    )
    _run_uv(
        install_arguments(uv, runtime_interpreter(staging), requirement),
        "install the GPU stack",
        _INSTALL_TIMEOUT_SECONDS,
    )
    environment = _judge(str(runtime_interpreter(staging)))
    _record(staging, release, requirement, environment)
    published = _publish(staging, release)
    interpreter = str(runtime_interpreter(published))
    from .operator_state._service_environment import ServiceEnvironment

    return ManagedRuntime(
        interpreter=interpreter,
        directory=published,
        # The same verdict, named against the interpreter that will serve: the
        # staging path it was taken from no longer exists.
        environment=ServiceEnvironment(
            interpreter, environment.capability, environment.detail
        ),
        created=True,
        source=requirement.source,
    )


def _record(
    staging: Path,
    release: str,
    requirement: RuntimeRequirement,
    environment: ServiceEnvironment,
) -> None:
    """Write the completion record into the staging build."""
    from ._atomic_write import write_json_atomically

    write_json_atomically(
        staging / RUNTIME_RECORD_NAME,
        {
            "release": release,
            "source": requirement.source,
            "requirement": requirement.requirement,
            "python": HOST_PYTHON,
            "capability": str(environment.capability),
        },
    )


def _publish(staging: Path, release: str) -> Path:
    """Make the staging build this release's runtime, by one rename.

    A directory already at the destination is an incomplete build - a complete
    one was returned long before anything was created - so it is removed first.
    """
    from ._atomic_write import fsync_directory
    from ._rmtree import remove_tree

    destination = release_runtime_dir(release)
    if destination.exists():
        remove_tree(destination)
    # Not ``os.replace``: on Windows the replace flag is refused for a
    # directory outright, and the destination is already gone here.
    os.rename(staging, destination)
    with contextlib.suppress(OSError):
        fsync_directory(destination.parent)
    return destination


def _run_uv(arguments: tuple[str, ...], activity: str, timeout: float) -> None:
    """Run one uv step, or raise the refusal naming what failed.

    The failure is one sentence: what uv was asked to do, and the last thing it
    said about it. Nothing is kept from a failed step, so the next start
    retries from the beginning.
    """
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ServiceRuntimeError(
            ERROR_RUNTIME_FAILED,
            f"The service runtime could not be created: uv did not {activity} "
            f"within {timeout:.0f}s, and the next start retries it.",
            command=_retry_command(),
            detail=str(exc),
        ) from exc
    except OSError as exc:
        raise ServiceRuntimeError(
            ERROR_RUNTIME_FAILED,
            f"The service runtime could not be created: uv could not be run to "
            f"{activity} ({exc}), and the next start retries it.",
            command=_retry_command(),
            detail=str(exc),
        ) from exc
    if completed.returncode != 0:
        raise ServiceRuntimeError(
            ERROR_RUNTIME_FAILED,
            f"The service runtime could not be created: uv failed to {activity} "
            f"({_last_line(completed)}), and the next start retries it.",
            command=_retry_command(),
            detail=_last_line(completed),
        )


def _retry_command() -> str:
    """The one command a failed creation offers: the start, again."""
    from ._operator_commands import server_start_command

    return server_start_command()


def _last_line(completed: subprocess.CompletedProcess[str]) -> str:
    """The most informative line uv left behind, bounded for one sentence."""
    for stream in (completed.stderr, completed.stdout):
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if lines:
            return lines[-1][:300]
    return f"exit code {completed.returncode}"


def _discard(staging: Path) -> None:
    """Delete a staging build, whether it failed or was already published."""
    from ._rmtree import remove_tree

    if not staging.exists():
        return
    with contextlib.suppress(OSError):
        remove_tree(staging)


def remove_superseded_runtimes() -> tuple[Path, ...]:
    """Delete every runtime directory that is not this release's, best effort.

    Run after a start the runtime served, so the removal cannot touch the
    environment the daemon just launched from. A removal that fails is left
    for the next start: the space matters, the moment does not. Leftover
    staging directories go the same way, which is how a build interrupted by a
    power loss is cleaned up.

    The build lock is held throughout, so a sweep cannot delete a staging
    directory another start is writing into right now; a lock that cannot be
    taken means a build is running and the sweep simply waits for the one
    after it.
    """
    from ._rmtree import remove_tree

    root = runtime_root()
    if not root.is_dir():
        return ()
    keep = os.path.normcase(str(release_runtime_dir()))
    removed: list[Path] = []
    try:
        with _publish_lock(root):
            entries = sorted(root.iterdir())
            for entry in entries:
                if not entry.is_dir() or os.path.normcase(str(entry)) == keep:
                    continue
                try:
                    remove_tree(entry)
                except OSError:
                    continue
                removed.append(entry)
    except (OSError, ServiceRuntimeError):
        return tuple(removed)
    return tuple(removed)


def _publish_lock(root: Path) -> _PublishLock:
    """The exclusive lock one build holds while it writes and publishes."""
    return _PublishLock(root / _LOCK_NAME)


class _PublishLock:
    """Bounded wait for the one build lock, released on the way out.

    Built on the project's own file lock, so the platform primitive keeps one
    implementation. The wait is bounded and the refusal says what is happening:
    the holder is downloading several gigabytes, and a second download of the
    same thing is the one outcome worth refusing.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock: FileLock | None = None

    def __enter__(self) -> None:
        lock = FileLock(self._path)
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while not lock.acquire():
            if time.monotonic() >= deadline:
                raise ServiceRuntimeError(
                    ERROR_RUNTIME_FAILED,
                    "Another vaultspec-rag start is already creating the "
                    "service runtime, and the next start uses it once that "
                    "one has finished.",
                    command=_retry_command(),
                    detail=str(lock.last_error or "lock held"),
                )
            time.sleep(_LOCK_POLL_SECONDS)
        self._lock = lock

    def __exit__(self, *_exc: object) -> None:
        if self._lock is not None:
            self._lock.release()
        self._lock = None
