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
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest import TempPathFactory
    from sentence_transformers import CrossEncoder

    from ...embeddings import EmbeddingModel
    from ..conftest import RagComponentsWithManifest
    from ._frozen_corpus_evidence import FrozenCorpusEvidence

from ..._machine_lock import (
    machine_lock_live_holder,
    machine_lock_path,
    release_machine_lock,
)
from ...config._settings import get_config, reset_config
from ...config._types import EnvVar
from ...progress import NullProgressReporter
from .._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    model_setup_timeout_seconds,
    models_are_cached,
)
from ..conftest import _index_corpus, managed_env
from ..corpus import build_synthetic_vault

_MAX_STARTUP_CLEANUP_RESERVE_SECONDS = 15.0


@pytest.fixture(scope="session", autouse=True)
def pin_index_cuda_ceiling() -> Generator[None]:
    """Pin the indexing CUDA ceiling for every in-process integration test.

    ``_service_env`` pins the same figure for spawned daemons; this covers the
    tests that index inside the pytest process, where no child env is built.

    Without it the ceiling is derived from free device memory when the budget
    is built, so a neighbouring CUDA process decides whether these tests pass.
    See ``INTEGRATION_CUDA_CEILING_MIB`` for the measurements behind the value.

    Session-scoped and set before any config is cached, so a later
    ``reset_config()`` re-reads it rather than dropping back to derivation. An
    explicit setting already in the environment is left alone, which is what
    lets an operator reproduce a ceiling failure by exporting their own.
    """
    from ._helpers import INTEGRATION_CUDA_CEILING_MIB

    key = EnvVar.INDEX_CUDA_CEILING_MIB.value
    previous = os.environ.get(key)
    if previous is None:
        os.environ[key] = str(INTEGRATION_CUDA_CEILING_MIB)
        reset_config()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
            reset_config()


#: Upper bound on the graceful-exit courtesy wait during teardown before
#: escalating to a hard, pid-targeted force-kill, on the platforms where the
#: graceful signal can actually be delivered. The remainder of the teardown
#: budget is reserved so the force-kill and its confirmation always have time
#: to run.
_TEARDOWN_GRACEFUL_COURTESY_SECONDS = 5.0

#: Wall-clock always held back from the graceful courtesy so the pid-targeted
#: force-kill AND its exit confirmation can run no matter how small the total
#: teardown budget is. The failed-startup cleanup path hands in only the
#: startup reserve (a few seconds), so a fixed courtesy that consumed the whole
#: budget would re-create the very starvation the courtesy cap exists to avoid.
_TEARDOWN_FORCE_KILL_RESERVE_SECONDS = 4.0

#: Upper bound on the wait for the launching process to follow the daemon out.
#: The launcher is not the process the graceful signal was ever aimed at - on
#: Windows the venv ``python.exe`` is a trampoline that runs the interpreter as
#: a child, so it merely has to notice that child is gone. That takes a moment,
#: not a shutdown, and funding it out of the graceful courtesy charged a
#: multi-second window for a sub-second wait.
_TEARDOWN_LAUNCHER_EXIT_SECONDS = 2.0


def teardown_graceful_courtesy_seconds(platform: str) -> float:
    """Return the graceful-exit courtesy worth waiting out on *platform*.

    A daemon that can act on the termination signal exits on its own, and
    waiting for it is free whenever it happens: the wait returns the moment the
    process is gone. POSIX delivers ``SIGTERM`` to the daemon, so the courtesy
    is real there.

    Windows delivers nothing. The daemon is spawned with ``CREATE_NO_WINDOW``,
    which puts it on a console of its own, and ``GenerateConsoleCtrlEvent``
    only reaches processes sharing the sender's console - so the event never
    arrives, the daemon never begins shutting down, and the wait is spent in
    full, every time, before the force-kill that actually ends it. That is not
    headroom that goes unused when things are healthy; it is a fixed cost paid
    on every teardown. Windows therefore funds no courtesy and goes straight to
    the pid-targeted force-kill.

    The platform is an argument because the rule is about the platform, not
    about the host running the code: both branches are statable anywhere, and a
    host can only ever exercise one of them.
    """
    if platform == "win32":
        return 0.0
    return _TEARDOWN_GRACEFUL_COURTESY_SECONDS


@dataclass
class _LiveServiceStartup:
    """One service fixture's deadline, diagnostics, and current startup phase."""

    started: float
    budget: float
    work_budget: float
    stages: list[str]
    log_path: Path
    current_stage: str

    def remaining_budget(self, stage: str) -> float:
        return _remaining_startup_budget(
            started=self.started,
            budget=self.work_budget,
            stages=self.stages,
            stage=stage,
        )


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


@pytest.fixture(scope="session")
def frozen_corpus_evidence(
    embedding_model: EmbeddingModel,
    shared_reranker: CrossEncoder,
    tmp_path_factory: TempPathFactory,
) -> FrozenCorpusEvidence:
    """Real ranking observations over one shared index of the frozen vault.

    Every frozen-corpus gate consumes this one fixture, so the pinned vault is
    materialised and embedded exactly once per session rather than once per
    gate. Depending on the two model fixtures is what keeps this to one model
    set on the device: they own the session's dense, sparse and reranker
    weights, and they acquire any missing snapshot through the killable
    bounded worker before constructing anything cache-only.
    """
    from ._frozen_corpus_evidence import build_frozen_corpus_evidence

    return build_frozen_corpus_evidence(
        tmp_path_factory.mktemp("frozen-corpus"),
        embedding_model,
        shared_reranker,
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
    shared_reranker: CrossEncoder,
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
            **components,
            manifest=manifest,
            reranker=shared_reranker,
        ),
    )

    components["store"].close()


def _startup_failure_message(
    startup: _LiveServiceStartup,
    *,
    stage: str,
    exc: BaseException,
) -> str:
    """Render one diagnostic envelope for every startup-stage failure."""
    elapsed = time.monotonic() - startup.started
    remaining = max(0.0, startup.budget - elapsed)
    detail = "\n".join(startup.stages) or "<no completed startup stages>"
    return (
        "Service startup failed\n"
        f"stage={stage}\n"
        f"deadline={startup.budget:.3f}s elapsed={elapsed:.3f}s "
        f"remaining={remaining:.3f}s\n"
        f"cause={exc.__class__.__name__}: {exc}\n"
        f"Startup stages:\n{detail}\n"
        f"Service output:\n{_service_diagnostics(startup.log_path)}"
    )


def _wait_for_qdrant_publication(
    *,
    service_pid: int,
    service_port: int,
    timeout: float,
) -> dict[str, object]:
    """Wait boundedly for the authoritative pre-warmup Qdrant status."""
    from ..._process_probe import pid_alive
    from ...cli._service_status import read_service_status

    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        status = read_service_status()
        if status is not None:
            last = cast("dict[str, object]", status)
            daemon_pid = status.get("pid")
            if (
                isinstance(daemon_pid, int)
                and not isinstance(daemon_pid, bool)
                and pid_alive(daemon_pid)
                and status.get("port") == service_port
                and isinstance(status.get("qdrant_pid"), int)
                and isinstance(status.get("qdrant_port"), int)
                and isinstance(status.get("qdrant_start_time"), int | float)
                and bool(status.get("qdrant_version"))
            ):
                return last
        if not pid_alive(service_pid):
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
    from ...cli._service_status import read_service_status

    status = read_service_status()
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
    from ...cli._process import _terminate_pid
    from ._helpers import _wait_for_exit

    daemon_pid, qdrant_pid = _resolve_owned_pids(port=port, fallback_pid=pid)
    started = time.monotonic()

    def _budget_left() -> float:
        return max(0.0, timeout - (time.monotonic() - started))

    def _bounded(window: float) -> float:
        # Never longer than what leaves the force-kill reserve intact -
        # otherwise a small budget (the failed-startup cleanup hands in only
        # the startup reserve) is entirely consumed by the wait and the
        # force-kill that ends the process is starved.
        return max(
            0.0,
            min(window, _budget_left() - _TEARDOWN_FORCE_KILL_RESERVE_SECONDS),
        )

    graceful_window = teardown_graceful_courtesy_seconds(sys.platform)

    # Send the graceful signal (as an operator-driven stop does) only where it
    # can land; see ``teardown_graceful_courtesy_seconds`` for why Windows
    # cannot receive one. Then escalate to a pid-targeted force-kill that never
    # touches a console group. Force-killing is safe here: state is a per-test
    # tmp dir, the machine lock is OS-advisory (freed on exit), and the Qdrant
    # child dies with the daemon via its kill-on-close job.
    if graceful_window > 0.0:
        with suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    if not _wait_for_exit(daemon_pid, timeout=_bounded(graceful_window)):
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
    if daemon_pid != pid and not _wait_for_exit(
        pid, timeout=_bounded(_TEARDOWN_LAUNCHER_EXIT_SECONDS)
    ):
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
    startup: _LiveServiceStartup,
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
            log_path=startup.log_path,
            timeout=max(
                _startup_cleanup_reserve(startup.budget),
                startup.budget - (cleanup_started - startup.started),
            ),
        )
    except BaseException as exc:
        cleanup_error = f" cleanup_error={exc.__class__.__name__}: {exc}"
    remaining = max(0.0, startup.budget - (time.monotonic() - startup.started))
    startup.stages.append(
        "startup failure teardown "
        f"elapsed={time.monotonic() - cleanup_started:.3f}s "
        f"remaining={remaining:.3f}s{cleanup_error}"
    )


def _prepare_service_models(
    tmp_path: Path,
    startup: _LiveServiceStartup,
    model_ids: tuple[str, ...] | None,
) -> None:
    """Ensure model snapshots before the fixture switches the daemon offline."""
    from ._helpers import _service_env

    online_acquisition_env = {
        EnvVar.HF_HUB_OFFLINE.value: None,
        EnvVar.TRANSFORMERS_OFFLINE.value: None,
    }
    startup.current_stage = "online environment entry"
    stage_started = time.monotonic()
    with _service_env(tmp_path, env_overrides=online_acquisition_env):
        startup.stages.append(
            "online environment entry "
            f"elapsed={time.monotonic() - stage_started:.3f}s "
            f"remaining={startup.remaining_budget('model acquisition'):.3f}s"
        )
        startup.current_stage = "model acquisition"
        eager_model_ids = model_ids or configured_service_model_ids()
        warm_cache = models_are_cached(eager_model_ids)
        stage_started = time.monotonic()
        ensure_model_snapshots(
            eager_model_ids,
            timeout_seconds=startup.remaining_budget(startup.current_stage),
        )
        startup.stages.append(
            "model acquisition "
            f"state={'warm' if warm_cache else 'repaired'} "
            f"elapsed={time.monotonic() - stage_started:.3f}s "
            f"remaining={startup.remaining_budget('offline environment entry'):.3f}s "
            f"models={list(eager_model_ids)!r} "
            f"offline_env_cleared={list(online_acquisition_env)!r}"
        )


@contextmanager
def _live_service_context(
    tmp_path: Path,
    *,
    startup_budget: float | None = None,
    model_ids: tuple[str, ...] | None = None,
    watch: bool = False,
) -> Generator[tuple[int, Path, dict[str, str | None]]]:
    """Start the real service under one model-to-readiness deadline envelope.

    Yields the port, the isolated status dir, and the environment mapping the
    daemon was started under, so a caller outliving a single test can re-point
    each test's client at this exact daemon.
    """
    from ...cli._process import _spawn_service
    from ...cli._service_status import _write_service_status
    from .._ports import free_loopback_port
    from ._helpers import (
        _poll_health,
        _service_env,
    )

    budget = _resolve_startup_budget(startup_budget)
    cleanup_reserve = _startup_cleanup_reserve(budget)
    startup = _LiveServiceStartup(
        started=time.monotonic(),
        budget=budget,
        work_budget=budget - cleanup_reserve,
        stages=[],
        log_path=tmp_path / "service.log",
        current_stage="online environment entry",
    )
    yielded = False

    try:
        _prepare_service_models(tmp_path, startup, model_ids)

        offline_env = {
            EnvVar.HF_HUB_OFFLINE.value: "1",
            EnvVar.TRANSFORMERS_OFFLINE.value: "1",
        }
        startup.current_stage = "offline environment entry"
        stage_started = time.monotonic()
        with _service_env(tmp_path, env_overrides=offline_env) as applied_env:
            startup.stages.append(
                "offline environment entry "
                f"elapsed={time.monotonic() - stage_started:.3f}s "
                f"remaining={startup.remaining_budget('service spawn'):.3f}s "
                f"offline_env={offline_env!r}"
            )
            port = free_loopback_port()
            startup.current_stage = "service spawn"
            stage_started = time.monotonic()
            pid = _spawn_service(
                port,
                startup.log_path,
                watch=watch,
                timeout=startup.remaining_budget(startup.current_stage),
                cleanup_timeout=cleanup_reserve,
            )
            try:
                startup.stages.append(
                    "service spawn "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"remaining={startup.remaining_budget('status publication'):.3f}s "
                    f"pid={pid} port={port}"
                )
                startup.current_stage = "status publication"
                stage_started = time.monotonic()
                _write_service_status(
                    pid,
                    port,
                    timeout=startup.remaining_budget(startup.current_stage),
                )
                published = _wait_for_qdrant_publication(
                    service_pid=pid,
                    service_port=port,
                    timeout=startup.remaining_budget(startup.current_stage),
                )
                startup.stages.append(
                    "status publication "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"remaining={startup.remaining_budget('health readiness'):.3f}s "
                    f"qdrant_pid={published.get('qdrant_pid')} "
                    f"qdrant_port={published.get('qdrant_port')} "
                    f"qdrant_version={published.get('qdrant_version')!r}"
                )
                startup.current_stage = "health readiness"
                stage_started = time.monotonic()
                _poll_health(
                    port,
                    timeout=startup.remaining_budget(startup.current_stage),
                )
                startup.stages.append(
                    "health readiness "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"total={time.monotonic() - startup.started:.3f}s"
                )
                startup.stages.append(
                    _verify_offline_service_startup(startup.log_path, startup.stages)
                )
            except BaseException:
                _cleanup_failed_startup(
                    pid=pid,
                    port=port,
                    startup=startup,
                )
                raise

            yielded = True
            try:
                yield port, tmp_path, applied_env
            finally:
                # Re-assert the daemon's own environment before resolving what
                # to terminate. Entering this context set those variables, but
                # it does not keep re-asserting them, and a caller that outlives
                # one test hands control back to the autouse machine-singleton
                # re-arm, which restores the session-wide dirs at every test
                # boundary. Cleanup would then read the session status file,
                # find no record for this port, and fall back to the spawned pid
                # with no qdrant pid at all - terminating the daemon but never
                # confirming its Qdrant child followed it out.
                with managed_env(**applied_env):
                    _cleanup_service_process(
                        pid=pid,
                        port=port,
                        log_path=startup.log_path,
                        timeout=15.0,
                    )
    except BaseException as exc:
        if yielded:
            raise
        raise AssertionError(
            _startup_failure_message(
                startup,
                stage=startup.current_stage,
                exc=exc,
            )
        ) from exc


@contextmanager
def _shared_live_service(
    tmp_path_factory: TempPathFactory,
    name: str,
    *,
    watch: bool,
) -> Generator[tuple[int, Path, dict[str, str | None]]]:
    """Hold one real daemon for every test that asks for this daemon flavour.

    Spawning a daemon is by far the most expensive setup in the suite: a
    measured 17s, of which 13s is the production model set reaching health
    readiness and 3s is Qdrant publication. None of that is reducible without
    spawning the daemon under a weaker configuration than the one under test,
    so the only honest saving is to spawn fewer times. The consumers drive many
    tests against one unchanging daemon, so it is spawned once and each test is
    re-pointed at it (see ``_attach_live_service``) instead of paying for a
    private one.

    Per-test isolation is preserved where it does the work: every test still
    supplies its own project root, and the daemon's own state is the subject
    under test rather than a fixture the tests mutate destructively. That is
    what lets the spawn amortise across modules and not just within one -
    accumulated jobs and namespaces are visible to later tests, and every
    assertion over those views is written against a root-scoped or filtered
    query rather than a whole-daemon count.
    """
    with _live_service_context(
        tmp_path_factory.mktemp(name),
        watch=watch,
    ) as service:
        yield service


@contextmanager
def _attach_live_service(
    service: tuple[int, Path, dict[str, str | None]],
) -> Generator[tuple[int, Path]]:
    """Point this test's in-process clients at the shared running daemon.

    The autouse machine-singleton re-arm restores the session-wide status and
    storage dirs at every test boundary, which is exactly what stops a stray
    test from reaching the operator's real service. That same restore would
    strand a daemon that outlives one test: discovery would resolve the session
    dirs and simply not find it. Re-applying the daemon's own captured mapping
    inside each test reconciles the two - the re-arm still owns both boundaries,
    and the window in between resolves the daemon the run actually started.

    The mapping is replayed verbatim rather than rebuilt because rebuilding
    would allocate a fresh ephemeral Qdrant port the running daemon never bound.
    """
    port, status_dir, applied_env = service
    with managed_env(**applied_env):
        yield port, status_dir


@pytest.fixture(scope="session")
def _live_service_daemon(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: TempPathFactory,
) -> Generator[tuple[int, Path, dict[str, str | None]]]:
    """Hold one cache-prepared, offline real service for the session.

    Five modules in the serialized subprocess-GPU invocation request this
    daemon. Scoped per module they paid five full spawns for five identical
    daemons; scoped per session they share one.
    """
    with _shared_live_service(
        tmp_path_factory,
        "live-service",
        watch=False,
    ) as service:
        yield service


@pytest.fixture
def live_service(
    _live_service_daemon: tuple[int, Path, dict[str, str | None]],
) -> Generator[tuple[int, Path]]:
    """Provide a cache-prepared, offline real service with bounded startup."""
    with _attach_live_service(_live_service_daemon) as service:
        yield service


@pytest.fixture(scope="module")
def _live_service_with_watch_daemon(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: TempPathFactory,
) -> Generator[tuple[int, Path, dict[str, str | None]]]:
    """Hold one watcher-enabled real service for the module.

    Stays module-scoped where the plain daemon is session-scoped: exactly one
    module asks for a watcher-enabled daemon, so widening the scope would save
    no spawn and would instead hold a second full model set resident alongside
    the session daemon for the rest of the run.
    """
    with _shared_live_service(
        tmp_path_factory,
        "live-service-watch",
        watch=True,
    ) as service:
        yield service


@pytest.fixture
def live_service_with_watch(
    _live_service_with_watch_daemon: tuple[int, Path, dict[str, str | None]],
) -> Generator[tuple[int, Path]]:
    """Provide a real service spawned with the file watcher enabled.

    ``live_service`` spawns with ``watch=False``; tests that exercise
    watcher-dependent behavior (``watch_enabled`` in ``server updates
    status``, start/stop/reconfigure) need a daemon where
    ``_ensure_watcher`` actually admits a watcher, which requires the
    watcher enabled at spawn.
    """
    with _attach_live_service(_live_service_with_watch_daemon) as service:
        yield service
