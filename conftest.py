"""Root conftest for all vaultspec tests.

RAG test constants and fixtures live in
src/vaultspec_rag/tests/conftest.py and src/vaultspec_rag/tests/constants.py.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from vaultspec_rag.config._types import EnvVar
from vaultspec_rag.tests._singleton_root_fixtures import (
    PYTEST_SESSION_ACTIVE_ENV,
    PYTEST_SESSION_ROOT_ENV,
)

#: Set by the process that took the borrower lease, on the pytest process it
#: starts inside that borrow. It says "somebody above you already borrowed the
#: GPU" and nothing more: the session still proves the loan reaches it by
#: asking the owner anchor, so this marker cannot authorise a device.
_PYTEST_GPU_BORROWED_ENV = "_VAULTSPEC_RAG_PYTEST_GPU_BORROWED"
#: Set on the collect-only child that answers "does this invocation actually
#: select a GPU tier". Honoured only together with ``--collect-only``, so a
#: marker left in an environment cannot end an ordinary session.
_PYTEST_GPU_TIER_PROBE_ENV = "_VAULTSPEC_RAG_PYTEST_GPU_TIER_PROBE"

#: The probe child's two answers. Outside pytest's own 0-5 range, so a status
#: this harness did not choose is never read as one of them.
_PROBE_GPU_TIER_SELECTED = 70
_PROBE_NO_GPU_TIER = 71
#: uv's own name for where a project's environment lives. Every uv process in
#: the session's tree reads it, including the ones started by a child, which
#: is the reach the audit hook does not have.
_UV_PROJECT_ENVIRONMENT_ENV = "UV_PROJECT_ENVIRONMENT"
_SINGLETON_ENV_NAMES = (
    PYTEST_SESSION_ACTIVE_ENV,
    PYTEST_SESSION_ROOT_ENV,
    EnvVar.STATUS_DIR.value,
    EnvVar.QDRANT_STORAGE_DIR.value,
    _UV_PROJECT_ENVIRONMENT_ENV,
)
_singleton_prior_env: dict[str, str | None] | None = None
_singleton_root: Path | None = None
_singleton_root_owned = False
_singleton_pair_owned = False
_singleton_participant: str | None = None
#: Set by pytest_sessionfinish. Teardown keeps this session's basetemp when a
#: test failed, so ``tmp_path_retention_policy = "failed"`` actually delivers.
_session_failed = False

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _typeshed import HasFileno

# The tier vocabulary and its collection-time gate live in the package, at
# vaultspec_rag.tests._tier_gate, so they can be exercised by ordinary tests.
# They are imported inside the hooks below rather than here, because the gate
# reaches the CLI and this module is loaded by every invocation.


# ===========================================================================
#  fsync suppression
#
#  WHY THIS IS HERE AND NOT A CONFIGURATION KNOB. Roughly twenty modules
#  publish state by writing a temp file and replacing the destination. A
#  handful of them ask for DURABILITY too - the bytes and the rename forced to
#  disk - which is an `os.fsync` on the way through, and `vaultspec-core`'s
#  own `atomic_write`, which this package calls to seed the framework tree,
#  fsyncs every single file it writes.
#
#  ATOMICITY IS NOT WHAT FSYNC BUYS. It comes from the exclusively-created
#  temp file and the rename; a reader sees the old bytes or the new ones and
#  never a partial write, fsync or no fsync. What fsync buys is survival
#  across power loss, and NO TEST IN THIS SUITE ASSERTS THAT. It cannot: a
#  test process that is still running has not lost power.
#
#  WORSE THAN THE COST IS ITS SHAPE. An fsync serialises at the DEVICE. Add
#  workers and the wall-clock does not fall, because the queue they are all
#  waiting on is one disk - which is what makes a suite refuse to
#  parallelise, and why this is the single largest lever on the runtime.
#
#  THE NARROW EXCEPTION. A test that can genuinely OBSERVE the suppression
#  carries `@pytest.mark.durable` and gets the real call back for its
#  duration. The bar for that mark is a measured difference between a
#  suppressed run and a restored one, recorded where the mark is applied - not
#  a hunch that a test looks timing-sensitive. A marker handed out for
#  flakiness hollows out the rule it is an exception to.
#
#  WHAT IT IS WORTH HERE. Three alternating pairs of the accelerator-free lane
#  on one Windows workstation, twelve workers, warm caches: 197.9s / 208.6s /
#  224.1s with the real call, against 157.0s / 150.8s / 160.0s with it
#  suppressed. Every suppressed run beat every restored one, and 5083 calls
#  went - the same count all three times. That is about a quarter of the
#  runtime, which is real and is also far less than the same change is worth
#  elsewhere, for a reason worth knowing: this package already separates
#  DURABLE writes from merely atomic ones, and only a handful of call sites
#  ask for durability. Most of what remains arrives from a dependency whose
#  own atomic write fsyncs unconditionally.
#
#  NOTHING CARRIES THE MARKER TODAY, and that is a finding rather than an
#  omission. Two wall-clock-bounded tests do go red under suppression - a
#  force-close bounded at 5s taking 5.9s, and an HTTP deadline of 120ms
#  measured at 126ms. Neither is an observation of the missing fsync: run
#  alone, both still fail intermittently, so what changed is the SHAPE of the
#  load. The lane was disk-bound and is now CPU-bound, and twelve workers that
#  used to wait on one device now compete for cores. Marking those `durable`
#  would restore an fsync inside a test whose failure came from outside it - a
#  marker that fixes nothing while spending the exception. Their bounds are
#  the thing to revisit.
#
#  Production never learns about any of this: the substitution lives in this
#  file, `dev/guards/test_production_never_imports_pytest.py` holds that line,
#  and the count is announced in the run header so no reader has to know the
#  mechanism to know it happened.
# ===========================================================================

_real_fsync = os.fsync
_real_fdatasync = getattr(os, "fdatasync", None)
_fsync_suppressed = 0
#: Non-zero while a `durable`-marked test is running, so nested calls made by
#: its own fixtures are covered too.
_fsync_restored_depth = 0


def _suppressed_fsync(fd: int | HasFileno) -> None:
    """Count the call and return, unless a `durable` test asked for the real one."""
    if _fsync_restored_depth:
        _real_fsync(fd)
        return
    global _fsync_suppressed
    _fsync_suppressed += 1


def _suppressed_fdatasync(fd: int | HasFileno) -> None:
    """The data-only variant, suppressed on the same terms."""
    if _fsync_restored_depth and _real_fdatasync is not None:
        _real_fdatasync(fd)
        return
    global _fsync_suppressed
    _fsync_suppressed += 1


cast("dict[str, object]", vars(os))["fsync"] = _suppressed_fsync
if _real_fdatasync is not None:
    cast("dict[str, object]", vars(os))["fdatasync"] = _suppressed_fdatasync


@pytest.fixture(autouse=True)
def _durable_writes(request: pytest.FixtureRequest) -> Iterator[None]:
    """Give a `durable`-marked test the real ``fsync`` back for its duration."""
    node = cast("pytest.Item", request.node)
    assert isinstance(node, pytest.Item)
    if node.get_closest_marker("durable") is None:
        yield
        return
    global _fsync_restored_depth
    _fsync_restored_depth += 1
    try:
        yield
    finally:
        _fsync_restored_depth -= 1


#: Counts shipped back from xdist workers. The suppression happens in whichever
#: process does the writing, and under `-n auto` that is never the process that
#: prints the summary - so a controller reporting only its OWN counter reports
#: zero while thousands of calls are being absorbed in the workers beside it. A
#: substitution that announces itself and then understates its own reach by
#: three orders of magnitude is worse than one that says nothing.
_FSYNC_KEY = "vaultspec_rag_fsync_suppressed"
_fsync_from_workers = 0


def pytest_report_header() -> str:
    """Announce the substitution, so nobody has to find it to know it is on."""
    return (
        "fsync: SUPPRESSED for this session (atomicity comes from the O_EXCL "
        "temp plus the rename; durability across power loss is asserted by no "
        "test). Tests marked `durable` run with the real call."
    )


def pytest_testnodedown(node: object, error: object) -> None:
    """Collect a finished xdist worker's suppression count."""
    del error
    global _fsync_from_workers
    output = getattr(node, "workeroutput", None)
    if isinstance(output, dict):
        count = cast("dict[str, object]", output).get(_FSYNC_KEY, 0)
        assert isinstance(count, int)
        _fsync_from_workers += count


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Report how many calls the suppression absorbed, across every process."""
    total = _fsync_suppressed + _fsync_from_workers
    terminalreporter.write_line(f"fsync: {total} call(s) suppressed this session.")


def _capture_host_provisioned_qdrant() -> tuple[Path, Path] | None:
    """Capture the real managed Qdrant install before pytest redirects it.

    ``pytest_configure`` replaces the status directory before session fixtures
    run. Resolve the production-managed install now, while the ambient config
    still names it, and retain only its binary and manifest paths. Only a
    downloaded install that passes the production pre-execution check is
    captured, and the supervisor checks the mirrored copy again at every spawn.
    """
    from vaultspec_rag.qdrant_runtime._constants import (
        MANIFEST_FILENAME,
        QDRANT_SERVER_VERSION,
        BinarySource,
    )
    from vaultspec_rag.qdrant_runtime._resolve import (
        QdrantBinaryError,
        resolve_binary,
    )
    from vaultspec_rag.qdrant_runtime._spawn_trust import verify_resolved_binary

    try:
        resolved = resolve_binary(QDRANT_SERVER_VERSION)
        if resolved is None or resolved.source is not BinarySource.MANAGED_DOWNLOAD:
            return None
        verify_resolved_binary(resolved)
    except QdrantBinaryError:
        # An ambient operator setting that names an unusable path, or an
        # install that fails its digest, is refused. Neither is a managed
        # install worth mirroring - and collection must not die on it.
        return None
    manifest = resolved.path.parent / MANIFEST_FILENAME
    if not manifest.is_file():
        return None
    return resolved.path, manifest


_HOST_PROVISIONED_QDRANT = _capture_host_provisioned_qdrant()


@pytest.fixture(scope="session")
def host_provisioned_qdrant_source() -> tuple[Path, Path] | None:
    """Return the manifest-backed host install captured before isolation."""
    return _HOST_PROVISIONED_QDRANT


@pytest.fixture(scope="session")
def required_host_provisioned_qdrant_source(
    host_provisioned_qdrant_source: tuple[Path, Path] | None,
) -> tuple[Path, Path]:
    """Require the captured managed install for real daemon tests."""
    if host_provisioned_qdrant_source is None:
        pytest.fail(
            "The runner image has no manifest-verified provisioned Qdrant binary. "
            "Install the pinned binary in the runner image before this lifecycle test."
        )
    return host_provisioned_qdrant_source


def _require_host_provisioned_qdrant_for_gpu_tier() -> None:
    """Require the runner image's verified Qdrant prerequisite without provisioning."""
    if _HOST_PROVISIONED_QDRANT is not None:
        return
    pytest.exit(
        "The selected GPU pytest tier requires a manifest-verified provisioned "
        "Qdrant binary in the runner image. Install the pinned binary in the "
        "runner image before running this tier.",
        returncode=1,
    )


# ===========================================================================
#  Borrowing the GPU for a device tier
#
#  A device tier runs on the machine's one GPU, which the resident service
#  owns. The product already has the way to take it: `run_with_borrowed_gpu`,
#  the call `index --borrow-gpu` makes - resolve the service, take the machine
#  borrower lease, pause, work, resume, release. The harness makes that same
#  call, with no argument of its own, and that is the whole mechanism.
#
#  WHY THE SESSION RUNS IN A CHILD. The call has to see the operator's real
#  service, and the session must not. Those are not reconcilable in one
#  process: `pytest_configure` points the managed directories at a temporary
#  root and installs the audit hook that refuses every mutation of the real
#  ones for the rest of the process - the borrow's own resume and release
#  included.
#
#  So the borrow is taken BEFORE any of that exists. This hook runs ahead of
#  `pytest_configure` (the default `pytest_cmdline_main` is what calls it), and
#  returning a status from here means `pytest_configure` is never reached in
#  this process at all: no redirection, no guard, the operator's own
#  configuration still ambient. The suite then runs as a child pytest, which
#  does its own isolation and installs its own guard, while this process holds
#  the lease and does nothing else. The loan the service records covers the
#  borrower's whole process tree, so the child is inside it; its own check
#  proves that rather than assuming it.
#
#  WHAT DECIDES. Only a selection that actually holds a GPU-tier test may
#  pause the operator's service, and the marker expression cannot answer that:
#  with no `-m` at all it admits every tier, so deciding on it alone would
#  pause the service - and refuse the whole run when no service is reachable -
#  for `pytest one_unit_test.py`. Only collection knows what was selected, and
#  collecting here would pin this process's root. So the question goes to a
#  collect-only child, which answers with one status and nothing else: it
#  borrows nothing, runs nothing, and reaches no service. An answer that is
#  neither of its two statuses is a collection fault, and this process stands
#  aside so the ordinary in-process run reports it exactly as it always did.
# ===========================================================================

#: Options that collect, list or explain and then stop. None of them reaches a
#: device, so none of them may pause the operator's service.
_NO_TEST_RUN_OPTIONS = (
    "collectonly",
    "help",
    "version",
    "showfixtures",
    "show_fixtures_per_test",
    "markers",
    "setupplan",
)


def _session_borrows_the_gpu(config: pytest.Config) -> bool:
    """Whether this process should take the borrower lease for its session."""
    if os.environ.get(_PYTEST_GPU_BORROWED_ENV) == "1":
        return False
    if os.environ.get(PYTEST_SESSION_ACTIVE_ENV) == "1":
        # Inherited containment: an outer pytest session owns this process
        # tree, so the borrow - if the tier needs one - is already held above.
        return False
    option = config.option
    if any(getattr(option, name, None) for name in _NO_TEST_RUN_OPTIONS):
        return False

    from vaultspec_rag.tests._tier_gate import (
        MPS,
        distributed_worker_count,
        selectable_slow_tiers,
    )

    if distributed_worker_count(option) > 0:
        # A distributed GPU selection is refused outright in pytest_configure.
        # Let the session reach that refusal instead of pausing a service for
        # a run that will not start.
        return False
    raw_markexpr = getattr(option, "markexpr", "")
    markexpr = raw_markexpr if isinstance(raw_markexpr, str) else ""
    # The MPS tier owns its own backend and never enters this protocol.
    return bool(set(selectable_slow_tiers(markexpr)) - {MPS})


def _run_pytest_child(
    config: pytest.Config,
    *,
    marker: str,
    extra_args: tuple[str, ...] = (),
    quiet: bool = False,
) -> int:
    """Run this invocation again as a child under *marker*, and return its status.

    The same argument vector, working directory and environment serve both
    children: the probe adds ``--collect-only`` and keeps its output to
    itself, and the suite inherits this process's streams so its report is
    the one the operator reads.
    """
    environment = dict(os.environ)
    environment[marker] = "1"
    child = subprocess.Popen(
        [sys.executable, "-m", "pytest", *config.invocation_params.args, *extra_args],
        cwd=str(config.invocation_params.dir),
        env=environment,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )
    return _wait_out_the_child(child)


def _selection_holds_a_gpu_tier(config: pytest.Config) -> bool | None:
    """Ask a collect-only child whether this selection reaches a GPU tier.

    ``None`` means it answered neither way - a collection error, a usage
    refusal, anything this harness did not choose - and the caller must leave
    the session to run in process, where that outcome is reported once.
    """
    status = _run_pytest_child(
        config,
        marker=_PYTEST_GPU_TIER_PROBE_ENV,
        extra_args=("--collect-only", "-q"),
        quiet=True,
    )
    if status == _PROBE_GPU_TIER_SELECTED:
        return True
    if status == _PROBE_NO_GPU_TIER:
        return False
    return None


def _answer_a_gpu_tier_probe(session: pytest.Session) -> None:
    """End a probe child with the status its parent is waiting for.

    Runs where the selection is final and nothing has been executed, so the
    answer is about the tests that would actually run. The marker is honoured
    only alongside ``--collect-only``, which is how the parent always spawns
    it: one left behind in an environment then changes nothing.
    """
    if os.environ.get(_PYTEST_GPU_TIER_PROBE_ENV) != "1":
        return
    if not session.config.option.collectonly:
        return

    from vaultspec_rag.tests._tier_gate import MPS, SLOW_TIERS, selected_tiers

    tiers = (selected_tiers(session.items) & SLOW_TIERS) - {MPS}
    pytest.exit(
        "gpu tier probe answered",
        returncode=_PROBE_GPU_TIER_SELECTED if tiers else _PROBE_NO_GPU_TIER,
    )


def _wait_out_the_child(child: subprocess.Popen[bytes]) -> int:
    """Wait for the child to exit, whatever interrupts arrive meanwhile.

    A console Ctrl+C is delivered to every process in the group, so the first
    one is the operator stopping pytest - which the child is already handling.
    Returning here on it would resume the service while the child still had
    the device. A second one is the operator saying the child is not stopping,
    and terminates it through the project's own termination path; either way
    the wait only ends when the child is gone.
    """
    from vaultspec_rag.cli._process import _terminate_pid

    interrupts = 0
    while True:
        try:
            return child.wait()
        except KeyboardInterrupt:
            interrupts += 1
            if interrupts == 1:
                print(
                    "pytest: interrupt delivered; waiting for the test session "
                    "to stop before the service is resumed. Interrupt again to "
                    "terminate it.",
                    file=sys.stderr,
                )
                continue
            print("pytest: terminating the test session.", file=sys.stderr)
            _terminate_pid(child.pid, console_group_signal=False)


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> int | None:
    """Hold the GPU borrow around a device-tier session, or stand aside.

    Returning ``None`` leaves pytest's own implementation to run the session
    in this process, which is every unit, collection and MPS invocation.
    """
    if not _session_borrows_the_gpu(config):
        return None
    if not _selection_holds_a_gpu_tier(config):
        return None

    from vaultspec_rag.cli._gpu_lease import BorrowGPUError, run_with_borrowed_gpu

    print(
        "pytest: borrowing the GPU from the resident service for this "
        "session; the tests run in a child process.",
        file=sys.stderr,
    )
    status = 1

    def run_the_suite() -> None:
        nonlocal status
        status = _run_pytest_child(config, marker=_PYTEST_GPU_BORROWED_ENV)

    try:
        run_with_borrowed_gpu(requested_port=None, work=run_the_suite)
    except BorrowGPUError as exc:
        print(f"pytest: {exc}", file=sys.stderr)
        return 1
    return status


def _require_the_session_runs_inside_a_gpu_loan() -> None:
    """Refuse a device tier whose process the service has not lent the GPU to.

    The marker the parent sets says only that somebody above took the lease.
    Whether the loan actually reaches this process is a question the owner
    anchor answers, and it is the same answer every model load will get.
    """
    from vaultspec_rag._gpu_owner import GpuOwnerState, observe_gpu_owner

    ownership = observe_gpu_owner()
    if ownership.state is GpuOwnerState.LENT_HERE:
        return
    pytest.exit(
        "This GPU tier is not running inside a borrow of the resident "
        f"service's GPU (owner state: {ownership.state.value}). Start the "
        "runner's resident service before selecting a GPU tier.",
        returncode=1,
    )


def _reset_singleton_config_caches() -> None:
    """Make early environment containment visible to both config layers."""
    from vaultspec_core.config import reset_config

    from vaultspec_rag.tests._config_fixtures import reset_config as reset_rag_config

    reset_config()
    reset_rag_config()


def pytest_configure(config: pytest.Config) -> None:
    """Refuse a distributed GPU session, then pin singleton containment.

    The refusal comes first and before collection because the process holding
    the distribution decision is the only one that can make it: once the plugin
    is distributing, it collects in its workers and calls neither the collection
    nor the run-loop hooks here, and a worker that refuses its own collection is
    reported as an internal scheduling fault whose text the operator never sees.

    Raises:
        pytest.UsageError: When this session would distribute GPU-bound tests
            across worker processes.
    """
    _enable_ci_report(config)

    from vaultspec_rag.tests._tier_gate import enforce_serial_gpu_lane

    enforce_serial_gpu_lane(config.option)

    global _singleton_prior_env
    global _singleton_root, _singleton_root_owned, _singleton_pair_owned
    global _singleton_participant
    if _singleton_root is not None:
        return

    _singleton_prior_env = {name: os.environ.get(name) for name in _SINGLETON_ENV_NAMES}
    inherited_root = os.environ.get(PYTEST_SESSION_ROOT_ENV)
    inherited_active = os.environ.get(PYTEST_SESSION_ACTIVE_ENV) == "1"

    # Before the redirection below, while the ambient configuration still names
    # the operator's own directories. This hook runs for the rest of the
    # process and is the backstop for a managed path the redirection misses.
    # It is installed here rather than at import so the GPU-borrowing parent -
    # which runs no test, keeps the operator's configuration and deliberately
    # drives the production borrow against the real service - never reaches it:
    # returning from pytest_cmdline_main means this hook is never called there.
    from vaultspec_rag.tests._operator_directory_guard import (
        install_operator_directory_guard,
        operator_managed_roots,
    )

    install_operator_directory_guard(
        operator_managed_roots(inherited_isolation=inherited_active)
    )

    if inherited_active and inherited_root:
        root = Path(inherited_root).expanduser().resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="vaultspec-rag-pytest-")).resolve()
        _singleton_root_owned = True

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    from vaultspec_rag.tests._singleton_root_fixtures import singleton_child_names

    _singleton_participant = (
        f"{worker}-pid{os.getpid()}" if worker else f"pid{os.getpid()}"
    )
    base_name, pytest_temp_name = singleton_child_names(_singleton_participant)
    config.option.basetemp = str(root / pytest_temp_name)
    base = root / base_name
    # Nested sessions inherit containment and worker identity, but own distinct
    # process-qualified pairs: pytest clears an explicit basetemp on first use.
    # Separating only teardown ownership cannot protect the live parent.
    _singleton_pair_owned = not base.exists()
    status_dir = base / "status"
    qdrant_storage_dir = base / "qdrant-server" / "storage"
    status_dir.mkdir(parents=True, exist_ok=True)
    qdrant_storage_dir.mkdir(parents=True, exist_ok=True)

    os.environ[PYTEST_SESSION_ACTIVE_ENV] = "1"
    os.environ[PYTEST_SESSION_ROOT_ENV] = str(root)
    os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
    os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(qdrant_storage_dir)

    from vaultspec_rag.tests._operator_directory_guard import canonical_path
    from vaultspec_rag.tests._singleton_root_fixtures import (
        sweep_orphaned_singleton_roots,
        uv_project_environment_redirect,
    )

    # The path is named and not created: uv builds an environment there the
    # first time something asks for one, and refuses a directory it finds
    # occupied by anything else.
    uv_environment = uv_project_environment_redirect(
        prefix=sys.prefix,
        rootdir=config.rootpath,
        configured=os.environ.get(_UV_PROJECT_ENVIRONMENT_ENV),
        scratch=base,
    )
    if uv_environment is not None:
        os.environ[_UV_PROJECT_ENVIRONMENT_ENV] = str(uv_environment)

    _singleton_root = canonical_path(root)
    _reset_singleton_config_caches()
    if _singleton_root_owned:
        # Register an atexit backstop so a soft exit that bypasses
        # pytest_unconfigure still reclaims this run's ~100MB root, and reclaim
        # leftover roots from prior runs killed before any cleanup ran. A hard
        # external kill skips atexit too; its leftover is reclaimed by the next
        # run's sweep here.
        atexit.register(_atexit_reclaim_singleton_root)
        sweep_orphaned_singleton_roots(keep=root, now=time.time())


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Record whether this session failed, before teardown decides what to keep."""
    del exitstatus
    global _session_failed
    _session_failed = bool(getattr(session, "testsfailed", 0))
    # `workeroutput` exists only in an xdist worker; this is how its count
    # reaches the process that prints the summary.
    output = getattr(session.config, "workeroutput", None)
    if isinstance(output, dict):
        output[_FSYNC_KEY] = _fsync_suppressed


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore ambient configuration after the complete pytest session."""
    del config

    global _singleton_prior_env, _singleton_root
    global _singleton_root_owned, _singleton_pair_owned, _singleton_participant
    global _session_failed
    prior = _singleton_prior_env
    root = _singleton_root
    if prior is not None:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset_singleton_config_caches()
    if root is not None:
        from vaultspec_rag.tests._singleton_root_fixtures import (
            reclaim_singleton_paths,
            singleton_child_names,
        )

        reclaim_singleton_paths(
            root,
            owned_root=_singleton_root_owned,
            owned_pair=_singleton_pair_owned,
            keep_diagnostics=_session_failed,
            worker=_singleton_participant,
        )
        if _session_failed:
            _, basetemp = singleton_child_names(_singleton_participant)
            print(
                f"pytest: retained failure artifacts under {root / basetemp}",
                file=sys.stderr,
            )
    _singleton_prior_env = None
    _singleton_root = None
    _singleton_root_owned = False
    _singleton_pair_owned = False
    _singleton_participant = None
    _session_failed = False


def _atexit_reclaim_singleton_root() -> None:
    """Reclaim the owned session root if pytest_unconfigure did not run.

    pytest_unconfigure is the normal-exit cleanup and clears ``_singleton_root``
    once it removes the root; this backstop covers a pytest process that exits
    without it (an aborted or errored session), so the root is not leaked. It is
    idempotent - a no-op once pytest_unconfigure has cleared the root - and a
    hard external kill bypasses it, leaving the next run's startup sweep to
    reclaim the leftover.
    """
    root = _singleton_root
    if root is not None:
        from vaultspec_rag.tests._singleton_root_fixtures import (
            reclaim_singleton_paths,
        )

        reclaim_singleton_paths(
            root,
            owned_root=_singleton_root_owned,
            owned_pair=_singleton_pair_owned,
            keep_diagnostics=_session_failed,
            worker=_singleton_participant,
        )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Refuse any collected test that declares no tier, or two lanes.

    Every collected test is checked, not only the selected ones: a run narrowed
    by a marker expression deselects exactly the tests that declare nothing, so
    checking the selection would let an untiered test through every run that
    could have caught it.

    Raises:
        pytest.UsageError: When a collected test declares no tier, or declares
            the fast tier alongside a slow one.
    """
    from vaultspec_rag.tests._tier_gate import enforce_tiers

    enforce_tiers(items)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Refuse a selection holding both device tiers at once.

    Judged here rather than beside the tier gate above because the two hooks
    need opposite halves of collection: that one has to see every collected
    test, before a marker expression removes the ones declaring nothing, while
    this one has to see only what will actually run. Two tiers both present in
    the suite are not a fault; the two of them in one session's selection are.
    So the check waits until the selection is final, which is what this hook
    means.

    Raises:
        pytest.UsageError: When the selection holds subprocess-tier and
            resident-tier tests at once.
    """
    from vaultspec_rag.tests._tier_gate import enforce_device_tier_isolation

    enforce_device_tier_isolation(session.items)
    # After the refusals, so a probe inherits them rather than answering over
    # a selection the session would not have run anyway.
    _answer_a_gpu_tier_probe(session)


def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Run every selected GPU tier inside the loan this process was started in.

    Runs after deselection so only *selected* items are checked, which keeps a
    unit-only run free of every device precondition. A distributed session never
    reaches this hook - the plugin owns the run loop in the launched process and
    in each worker - which costs nothing, because a distributed GPU selection is
    already refused before collection.
    """
    from vaultspec_rag.tests._tier_gate import (
        MPS,
        SLOW_TIERS,
        selected_tiers,
    )

    if session.testsfailed and not session.config.option.continue_on_collection_errors:
        raise session.Interrupted(
            f"{session.testsfailed} error{'s' if session.testsfailed != 1 else ''} "
            "during collection"
        )
    if session.config.option.collectonly:
        return True

    tiers = selected_tiers(session.items)
    if MPS in tiers:
        # The MPS guard owns its backend and cache preconditions. It must not
        # enter the CUDA runner's resident-service borrower protocol.
        return None
    if not tiers & SLOW_TIERS:
        return
    if any(
        "required_host_provisioned_qdrant_source" in item.fixturenames
        for item in cast("list[pytest.Function]", session.items)
    ):
        _require_host_provisioned_qdrant_for_gpu_tier()
    _require_the_session_runs_inside_a_gpu_loan()

    from vaultspec_rag._gpu_admission import (
        device_refusal_message,
        evaluate_device_admission,
    )

    admission = evaluate_device_admission()
    if not admission.admitted:
        pytest.exit(device_refusal_message(admission), returncode=1)
    for index, item in enumerate(session.items):
        nextitem = session.items[index + 1] if index + 1 < len(session.items) else None
        item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
        if session.shouldfail:
            raise session.Failed(session.shouldfail)
        if session.shouldstop:
            raise session.Interrupted(session.shouldstop)
    return True


# --- machine-readable CI reports -------------------------------------------
#
# A test lane's result is human-readable text and nothing else, so CI can only
# learn "the process exited non-zero" and has to scrape scrollback for what
# actually failed. `VAULTSPEC_CI_REPORTS` names a directory to write a JUnit
# XML report into; when it is UNSET - every local run, and any CI job that does
# not opt in - nothing changes and no artifact is produced.
#
# The junitxml plugin reads `xmlpath` in its own `pytest_configure`. A conftest
# is registered after the builtin plugins and pytest calls hook implementations
# last-registered-first, so this conftest's configure runs BEFORE the plugin
# reads the option - which is what makes setting it here take effect.
#
# The filename distinguishes lanes: `VAULTSPEC_CI_REPORT_NAME` when the caller
# names one, otherwise a short digest of the invocation, so two lanes in one
# job do not overwrite each other's report. An explicit `--junitxml` on the
# command line always wins.
_CI_REPORTS_ENV = "VAULTSPEC_CI_REPORTS"
_CI_REPORT_NAME_ENV = "VAULTSPEC_CI_REPORT_NAME"


def _ci_report_path(args: tuple[str, ...] | list[str]) -> str | None:
    """Return the JUnit path this run should write, or ``None`` to write none.

    Args:
        args: The pytest command-line arguments for this run.

    Returns:
        The report path, or ``None`` when reporting is not enabled or the
        caller already named a report.
    """
    directory = os.environ.get(_CI_REPORTS_ENV, "").strip()
    if not directory:
        return None
    if any(arg == "--junitxml" or arg.startswith("--junitxml=") for arg in args):
        return None
    name = os.environ.get(_CI_REPORT_NAME_ENV, "").strip()
    if not name:
        digest = hashlib.sha256(" ".join(args).encode("utf-8")).hexdigest()[:8]
        name = f"pytest-{digest}"
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    return str(target / f"{name}.xml")


def _enable_ci_report(config: pytest.Config) -> None:
    """Point the junitxml plugin at this run's report, when one is asked for."""
    if getattr(config.option, "xmlpath", None):
        return
    path = _ci_report_path(list(config.invocation_params.args))
    if path is not None:
        config.option.xmlpath = path
