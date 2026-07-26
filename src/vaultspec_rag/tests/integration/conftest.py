"""RAG integration test fixtures.

Uses the session-scoped ``rag_components`` from the parent conftest.
Only defines ``rag_components_with_code`` for tests that need codebase
indexing on top of vault indexing.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ..conftest import RagComponentsWithManifest

from ..._machine_lock import (
    machine_lock_live_holder,
    machine_lock_path,
    release_machine_lock,
)
from ...config import EnvVar, get_config, reset_config
from ...progress import NullProgressReporter
from .._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    model_setup_timeout_seconds,
    models_are_cached,
)
from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault

_MAX_STARTUP_CLEANUP_RESERVE_SECONDS = 15.0


@pytest.fixture(scope="session", autouse=True)
def _pin_index_cuda_ceiling() -> Generator[None]:
    """Pin the indexing CUDA ceiling for every in-process integration test.

    ``_service_env`` pins the same figure for spawned daemons; this covers the
    tests that index inside the pytest process, where no child env is built.

    Without it the ceiling is derived from free device memory when the budget
    is built, so a neighbouring CUDA process decides whether these tests pass.
    See ``INTEGRATION_CUDA_CEILING_MB`` for the measurements behind the value.

    Session-scoped and set before any config is cached, so a later
    ``reset_config()`` re-reads it rather than dropping back to derivation. An
    explicit setting already in the environment is left alone, which is what
    lets an operator reproduce a ceiling failure by exporting their own.
    """
    from ._helpers import INTEGRATION_CUDA_CEILING_MB

    key = EnvVar.INDEX_CUDA_CEILING_MB.value
    previous = os.environ.get(key)
    if previous is None:
        os.environ[key] = str(INTEGRATION_CUDA_CEILING_MB)
        reset_config()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
            reset_config()


#: Upper bound on the graceful-exit courtesy wait during teardown before
#: escalating to a hard, pid-targeted force-kill. Kept short because the
#: graceful console signal often never reaches a stub-relaunched descendant
#: daemon; the remainder of the teardown budget is reserved so the force-kill
#: and its confirmation always have time to run.
_TEARDOWN_GRACEFUL_COURTESY_SECONDS = 5.0

#: Wall-clock always held back from the graceful courtesy so the pid-targeted
#: force-kill AND its exit confirmation can run no matter how small the total
#: teardown budget is. The failed-startup cleanup path hands in only the
#: startup reserve (a few seconds), so a fixed courtesy that consumed the whole
#: budget would re-create the very starvation the courtesy cap exists to avoid.
_TEARDOWN_FORCE_KILL_RESERVE_SECONDS = 4.0


def _service_output(log_path: Path) -> str:
    """Return the complete retained service log, or an empty string."""
    if not log_path.is_file():
        return ""
    return log_path.read_text(encoding="utf-8", errors="replace")


def _service_diagnostics(log_path: Path) -> str:
    """Return the bounded retained service-log tail."""
    output = _service_output(log_path)
    if not output:
        return "service log was not created"
    return "\n".join(output.splitlines()[-80:])


def _remaining_startup_budget(
    *,
    started: float,
    budget: float,
    stages: list[str],
    stage: str,
) -> float:
    """Return the remaining whole-startup budget or fail with stage context."""
    elapsed = time.monotonic() - started
    remaining = budget - elapsed
    if remaining <= 0:
        detail = "\n".join(stages) or "<no completed startup stages>"
        raise AssertionError(
            f"Service startup exceeded {budget:.3f}s before {stage}; "
            f"elapsed={elapsed:.3f}s\nStartup stages:\n{detail}"
        )
    return remaining


def _startup_cleanup_reserve(budget: float) -> float:
    """Reserve bounded teardown time inside the one startup envelope."""
    if budget <= 0.0:
        return 0.0
    return min(
        _MAX_STARTUP_CLEANUP_RESERVE_SECONDS,
        max(5.0, budget * 0.25),
        budget * 0.5,
    )


#: Upper bound on how far host contention may stretch the default startup
#: envelope. The envelope is a whole-startup hang-guard, so enlarging it only
#: defers a genuine-hang failure; the cap stops a runaway load signal from
#: inflating it without end.
_MAX_STARTUP_LOAD_MULTIPLIER = 4.0


def _startup_load_multiplier() -> float:
    """Stretch the default startup envelope when the host is oversubscribed.

    Returns a factor in ``[1.0, _MAX_STARTUP_LOAD_MULTIPLIER]`` from the
    one-minute load average per logical core, so a busy fleet grants a
    proportionally longer whole-startup hang-guard instead of racing a fixed
    default. It only ever grows the envelope (floor 1.0), so it can make a
    previously-passing startup more tolerant, never less; any probe failure
    falls back to 1.0. Applied only to the fixture default - an explicit
    ``startup_budget`` (used by tests that assert timeout behaviour) is left
    exactly as given.
    """
    try:
        import psutil

        cores = psutil.cpu_count(logical=True) or 1
        load1, _, _ = psutil.getloadavg()
    except (ImportError, OSError, ValueError):
        return 1.0
    return min(_MAX_STARTUP_LOAD_MULTIPLIER, max(1.0, load1 / cores))


def _resolve_startup_budget(startup_budget: float | None) -> float:
    """Return the startup envelope: an explicit override, else load-scaled default."""
    if startup_budget is not None:
        return startup_budget
    return model_setup_timeout_seconds() * _startup_load_multiplier()


def _verify_offline_service_startup(log_path: Path, stages: list[str]) -> str:
    """Prove local-only constructors ran without the configured HF endpoint."""
    output = _service_output(log_path)
    expected_markers = ["EmbeddingModel cache-only mode: True"]
    if bool(get_config().reranker_enabled):
        expected_markers.append("(cache-only=True)")
    missing_markers = [marker for marker in expected_markers if marker not in output]
    hf_endpoint = (
        os.environ.get(EnvVar.HF_ENDPOINT.value) or "https://huggingface.co"
    ).rstrip("/")
    if missing_markers or hf_endpoint in output:
        raise AssertionError(
            "Service did not prove cache-only startup without Hugging Face "
            f"metadata access; missing_markers={missing_markers!r}, "
            f"endpoint_seen={hf_endpoint in output}, endpoint={hf_endpoint!r}\n"
            f"Startup stages:\n{'\n'.join(stages)}\nService output:\n"
            f"{_service_diagnostics(log_path)}"
        )
    return (
        f"offline verification endpoint={hf_endpoint!r} metadata_requests=0 "
        f"markers={expected_markers!r}"
    )


@pytest.fixture
def isolated_lock(tmp_path: Path) -> Generator[Path]:
    """Provide and safely remove a test-owned machine-singleton lock path."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path / "qdrant-server" / "storage")
    reset_config()
    try:
        yield machine_lock_path()
    finally:
        try:
            release_machine_lock()
            path = machine_lock_path()
            live_holder = machine_lock_live_holder()
            if live_holder != 0:
                msg = (
                    "refusing to unlink test-owned machine lock while its real "
                    f"holder {live_holder} is still alive"
                )
                raise AssertionError(msg)
            path.unlink(missing_ok=True)
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
            reset_config()


@pytest.fixture(scope="session")
def rag_components_with_code(
    embedding_model: EmbeddingModel,
    tmp_path_factory: TempPathFactory,
) -> Generator[RagComponentsWithManifest]:
    """RAG components with vault + codebase indexed.

    Creates a synthetic vault and indexes both vault docs and any
    source files present under the synthetic project root.
    """
    root: Path = tmp_path_factory.mktemp("integ-code-vault")
    manifest = build_synthetic_vault(root, n_docs=24, seed=200)
    components = _index_corpus(root, embedding_model)

    code_indexer = components["code_indexer"]
    code_indexer.full_index(
        reporter=NullProgressReporter(),
        preflight=code_indexer.preflight_content(),
    )

    yield cast(
        "RagComponentsWithManifest",
        components.__class__(  # type: ignore[call-arg]
            **components,  # type: ignore[misc]
            manifest=manifest,
        ),
    )

    components["store"].close()


def _startup_failure_message(
    *,
    stage: str,
    started: float,
    budget: float,
    stages: list[str],
    log_path: Path,
    exc: BaseException,
) -> str:
    """Render one diagnostic envelope for every startup-stage failure."""
    elapsed = time.monotonic() - started
    remaining = max(0.0, budget - elapsed)
    detail = "\n".join(stages) or "<no completed startup stages>"
    return (
        "Service startup failed\n"
        f"stage={stage}\n"
        f"deadline={budget:.3f}s elapsed={elapsed:.3f}s "
        f"remaining={remaining:.3f}s\n"
        f"cause={exc.__class__.__name__}: {exc}\n"
        f"Startup stages:\n{detail}\n"
        f"Service output:\n{_service_diagnostics(log_path)}"
    )


def _wait_for_qdrant_publication(
    *,
    service_pid: int,
    service_port: int,
    timeout: float,
) -> dict[str, object]:
    """Wait boundedly for the authoritative pre-warmup Qdrant status."""
    from ...cli import _is_pid_alive, _read_service_status

    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        status = _read_service_status()
        if status is not None:
            last = cast("dict[str, object]", status)
            daemon_pid = status.get("pid")
            if (
                isinstance(daemon_pid, int)
                and not isinstance(daemon_pid, bool)
                and _is_pid_alive(daemon_pid)
                and status.get("port") == service_port
                and isinstance(status.get("qdrant_pid"), int)
                and isinstance(status.get("qdrant_port"), int)
                and isinstance(status.get("qdrant_start_time"), int | float)
                and bool(status.get("qdrant_version"))
            ):
                return last
        if not _is_pid_alive(service_pid):
            break
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    raise TimeoutError(
        "Qdrant status was not authoritatively published before model warmup; "
        f"last_status={last!r}"
    )


def _resolve_owned_pids(*, port: int, fallback_pid: int) -> tuple[int, int | None]:
    """Resolve the daemon and qdrant pids the status file attributes to *port*.

    The daemon pid comes from the status file only when it records a valid
    integer pid for this exact port; otherwise it falls back to
    ``fallback_pid`` (the spawned process). The qdrant pid is returned when the
    status file records a valid integer, else ``None``.
    """
    from ...cli import _read_service_status

    status = _read_service_status()
    raw_daemon_pid = (
        status.get("pid") if status is not None and status.get("port") == port else None
    )
    daemon_pid = (
        raw_daemon_pid
        if isinstance(raw_daemon_pid, int)
        and not isinstance(raw_daemon_pid, bool)
        and raw_daemon_pid > 0
        else fallback_pid
    )
    raw_qdrant_pid = status.get("qdrant_pid") if status else None
    qdrant_pid = (
        raw_qdrant_pid
        if isinstance(raw_qdrant_pid, int) and not isinstance(raw_qdrant_pid, bool)
        else None
    )
    return daemon_pid, qdrant_pid


def _cleanup_service_process(
    *,
    pid: int,
    port: int,
    log_path: Path,
    timeout: float,
) -> None:
    """Terminate and verify one test-owned service inside the supplied budget."""
    from ...cli import _terminate_pid
    from ._helpers import _wait_for_exit

    daemon_pid, qdrant_pid = _resolve_owned_pids(port=port, fallback_pid=pid)
    started = time.monotonic()

    def _budget_left() -> float:
        return max(0.0, timeout - (time.monotonic() - started))

    def _graceful_window() -> float:
        # The graceful Windows CTRL_BREAK is addressed to the group leader
        # ``pid`` in the hope it propagates to the serving daemon. But a
        # stub-relaunched daemon is a descendant that is not the console group
        # leader, so the event frequently never reaches it and the daemon never
        # begins shutting down. Waiting the whole budget for a graceful exit
        # that cannot happen would starve the pid-targeted force-kill and its
        # confirmation, spuriously failing teardown. So the graceful wait is a
        # short courtesy only, and never longer than what leaves the force-kill
        # reserve intact - otherwise a small budget (the failed-startup cleanup
        # hands in only the startup reserve) is entirely consumed by the
        # courtesy and the force-kill is starved again. Force-killing is safe
        # here: state is a per-test tmp dir, the machine lock is OS-advisory
        # (freed on exit), and the Qdrant child dies with the daemon via its
        # kill-on-close job.
        return max(
            0.0,
            min(
                _TEARDOWN_GRACEFUL_COURTESY_SECONDS,
                _budget_left() - _TEARDOWN_FORCE_KILL_RESERVE_SECONDS,
            ),
        )

    # Send the bare graceful signal (as an operator-driven stop does), then
    # escalate to a pid-targeted force-kill that never touches a console group.
    with suppress(OSError):
        if sys.platform == "win32":
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
    if not _wait_for_exit(daemon_pid, timeout=_graceful_window()):
        _terminate_pid(
            daemon_pid,
            timeout=_budget_left(),
            console_group_signal=False,
        )
        if not _wait_for_exit(daemon_pid, timeout=_budget_left()):
            raise AssertionError(
                f"Test-owned service process {daemon_pid} did not exit.\n"
                f"Service output:\n{_service_diagnostics(log_path)}"
            )
    if daemon_pid != pid and not _wait_for_exit(pid, timeout=_graceful_window()):
        _terminate_pid(
            pid,
            timeout=_budget_left(),
            console_group_signal=False,
        )
        if not _wait_for_exit(pid, timeout=_budget_left()):
            raise AssertionError(
                f"Test-owned service launcher {pid} did not exit with daemon "
                f"{daemon_pid}.\nService output:\n{_service_diagnostics(log_path)}"
            )
    if qdrant_pid is not None and not _wait_for_exit(
        qdrant_pid, timeout=_budget_left()
    ):
        raise AssertionError(
            f"Test-owned Qdrant process {qdrant_pid} did not exit with its "
            f"service {pid}.\nService output:\n"
            f"{_service_diagnostics(log_path)}"
        )


def _cleanup_failed_startup(
    *,
    pid: int,
    port: int,
    log_path: Path,
    startup_started: float,
    budget: float,
    stages: list[str],
) -> None:
    """Attempt startup-failure teardown and append its bounded diagnostic.

    Cleanup always gets at least the originally-reserved window
    (``_startup_cleanup_reserve(budget)``), never less. A bounded wait's
    nominal timeout is not a wall-clock guarantee: under heavy concurrent
    machine load every stage before this one can genuinely overrun its own
    deadline by some margin (OS scheduling delay on a saturated box, not a
    logic bug), which would otherwise eat directly into the reserve carved
    out for the one thing that must not be starved - actually terminating
    the process this test spawned.
    """
    cleanup_started = time.monotonic()
    cleanup_error = ""
    try:
        _cleanup_service_process(
            pid=pid,
            port=port,
            log_path=log_path,
            timeout=max(
                _startup_cleanup_reserve(budget),
                budget - (cleanup_started - startup_started),
            ),
        )
    except BaseException as exc:
        cleanup_error = f" cleanup_error={exc.__class__.__name__}: {exc}"
    remaining = max(0.0, budget - (time.monotonic() - startup_started))
    stages.append(
        "startup failure teardown "
        f"elapsed={time.monotonic() - cleanup_started:.3f}s "
        f"remaining={remaining:.3f}s{cleanup_error}"
    )


@contextmanager
def _live_service_context(
    tmp_path: Path,
    *,
    startup_budget: float | None = None,
    model_ids: tuple[str, ...] | None = None,
    watch: bool = False,
) -> Generator[tuple[int, Path]]:
    """Start the real service under one model-to-readiness deadline envelope."""
    from ...cli import _spawn_service, _write_service_status
    from ._helpers import (
        _get_ephemeral_port,
        _poll_health,
        _service_env,
    )

    startup_started = time.monotonic()
    budget = _resolve_startup_budget(startup_budget)
    cleanup_reserve = _startup_cleanup_reserve(budget)
    work_budget = budget - cleanup_reserve
    stages: list[str] = []
    log_path = tmp_path / "service.log"
    current_stage = "online environment entry"
    yielded = False

    def remaining_budget(stage: str) -> float:
        return _remaining_startup_budget(
            started=startup_started,
            budget=work_budget,
            stages=stages,
            stage=stage,
        )

    try:
        online_acquisition_env = {
            EnvVar.HF_HUB_OFFLINE.value: None,
            EnvVar.TRANSFORMERS_OFFLINE.value: None,
        }
        stage_started = time.monotonic()
        with _service_env(tmp_path, env_overrides=online_acquisition_env):
            stages.append(
                "online environment entry "
                f"elapsed={time.monotonic() - stage_started:.3f}s "
                f"remaining={remaining_budget('model acquisition'):.3f}s"
            )
            current_stage = "model acquisition"
            eager_model_ids = model_ids or configured_service_model_ids()
            warm_cache = models_are_cached(eager_model_ids)
            stage_started = time.monotonic()
            ensure_model_snapshots(
                eager_model_ids,
                timeout_seconds=remaining_budget(current_stage),
            )
            stages.append(
                "model acquisition "
                f"state={'warm' if warm_cache else 'repaired'} "
                f"elapsed={time.monotonic() - stage_started:.3f}s "
                f"remaining={remaining_budget('offline environment entry'):.3f}s "
                f"models={list(eager_model_ids)!r} "
                f"offline_env_cleared={list(online_acquisition_env)!r}"
            )

        offline_env = {
            EnvVar.HF_HUB_OFFLINE.value: "1",
            EnvVar.TRANSFORMERS_OFFLINE.value: "1",
        }
        current_stage = "offline environment entry"
        stage_started = time.monotonic()
        with _service_env(tmp_path, env_overrides=offline_env):
            stages.append(
                "offline environment entry "
                f"elapsed={time.monotonic() - stage_started:.3f}s "
                f"remaining={remaining_budget('service spawn'):.3f}s "
                f"offline_env={offline_env!r}"
            )
            port = _get_ephemeral_port()
            current_stage = "service spawn"
            stage_started = time.monotonic()
            pid = _spawn_service(
                port,
                log_path,
                watch=watch,
                timeout=remaining_budget(current_stage),
                cleanup_timeout=cleanup_reserve,
            )
            try:
                stages.append(
                    "service spawn "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"remaining={remaining_budget('status publication'):.3f}s "
                    f"pid={pid} port={port}"
                )
                current_stage = "status publication"
                stage_started = time.monotonic()
                _write_service_status(
                    pid,
                    port,
                    timeout=remaining_budget(current_stage),
                )
                published = _wait_for_qdrant_publication(
                    service_pid=pid,
                    service_port=port,
                    timeout=remaining_budget(current_stage),
                )
                stages.append(
                    "status publication "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"remaining={remaining_budget('health readiness'):.3f}s "
                    f"qdrant_pid={published.get('qdrant_pid')} "
                    f"qdrant_port={published.get('qdrant_port')} "
                    f"qdrant_version={published.get('qdrant_version')!r}"
                )
                current_stage = "health readiness"
                stage_started = time.monotonic()
                _poll_health(
                    port,
                    timeout=remaining_budget(current_stage),
                )
                stages.append(
                    "health readiness "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"total={time.monotonic() - startup_started:.3f}s"
                )
                stages.append(_verify_offline_service_startup(log_path, stages))
            except BaseException:
                _cleanup_failed_startup(
                    pid=pid,
                    port=port,
                    log_path=log_path,
                    startup_started=startup_started,
                    budget=budget,
                    stages=stages,
                )
                raise

            yielded = True
            try:
                yield port, tmp_path
            finally:
                _cleanup_service_process(
                    pid=pid,
                    port=port,
                    log_path=log_path,
                    timeout=15.0,
                )
    except BaseException as exc:
        if yielded:
            raise
        raise AssertionError(
            _startup_failure_message(
                stage=current_stage,
                started=startup_started,
                budget=budget,
                stages=stages,
                log_path=log_path,
                exc=exc,
            )
        ) from exc


@pytest.fixture
def live_service(
    tmp_path: Path,
) -> Generator[tuple[int, Path]]:
    """Provide a cache-prepared, offline real service with bounded startup."""
    with _live_service_context(tmp_path) as service:
        yield service


@pytest.fixture
def live_service_with_watch(
    tmp_path: Path,
) -> Generator[tuple[int, Path]]:
    """Provide a real service spawned with the file watcher enabled.

    ``live_service`` spawns with ``watch=False``; tests that exercise
    watcher-dependent behavior (``watch_enabled`` in ``server updates
    status``, start/stop/reconfigure) need a daemon where
    ``_ensure_watcher`` actually admits a watcher, which requires the
    watcher enabled at spawn.
    """
    with _live_service_context(tmp_path, watch=True) as service:
        yield service
