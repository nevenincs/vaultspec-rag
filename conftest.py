"""Root conftest for all vaultspec tests.

RAG test constants and fixtures live in
src/vaultspec_rag/tests/conftest.py and src/vaultspec_rag/tests/constants.py.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

# Identify pytest before importing project modules or collecting test modules.
# Until pytest_configure pins the session root, guarded effects fail closed.
_PYTEST_SINGLETON_BOOTSTRAP_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"
_PRIOR_PYTEST_SINGLETON_BOOTSTRAP = os.environ.get(_PYTEST_SINGLETON_BOOTSTRAP_ENV)
os.environ[_PYTEST_SINGLETON_BOOTSTRAP_ENV] = "1"

import pytest  # noqa: E402  # bootstrap sentinel must precede project imports

_PYTEST_SINGLETON_ACTIVE_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"
_PYTEST_SINGLETON_ROOT_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT"
_STATUS_DIR_ENV = "VAULTSPEC_RAG_STATUS_DIR"
_QDRANT_STORAGE_DIR_ENV = "VAULTSPEC_RAG_QDRANT_STORAGE_DIR"
_SINGLETON_ENV_NAMES = (
    _PYTEST_SINGLETON_ACTIVE_ENV,
    _PYTEST_SINGLETON_ROOT_ENV,
    _STATUS_DIR_ENV,
    _QDRANT_STORAGE_DIR_ENV,
)
_singleton_prior_env: dict[str, str | None] | None = None
_singleton_root: Path | None = None
_singleton_root_owned = False
_singleton_pair_owned = False
#: Set by pytest_sessionfinish. Teardown keeps this session's basetemp when a
#: test failed, so ``tmp_path_retention_policy = "failed"`` actually delivers.
_session_failed = False

if TYPE_CHECKING:
    from collections.abc import Iterator

    from vaultspec_rag.cli._gpu_lease import BorrowerServiceTarget

_gpu_borrower_target: BorrowerServiceTarget | None = None

# The tier vocabulary and its collection-time gate live in the package, at
# vaultspec_rag.tests._tier_gate, so they can be exercised by ordinary tests.
# They are imported inside the hooks below rather than here: this module runs
# before the pytest session pins its root, and the guarded effects above must
# stay the first thing that happens.


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


def _suppressed_fsync(descriptor: int) -> None:
    """Count the call and return, unless a `durable` test asked for the real one."""
    if _fsync_restored_depth:
        _real_fsync(descriptor)
        return
    global _fsync_suppressed
    _fsync_suppressed += 1


def _suppressed_fdatasync(descriptor: int) -> None:
    """The data-only variant, suppressed on the same terms."""
    if _fsync_restored_depth and _real_fdatasync is not None:
        _real_fdatasync(descriptor)
        return
    global _fsync_suppressed
    _fsync_suppressed += 1


os.fsync = _suppressed_fsync
if _real_fdatasync is not None:
    os.fdatasync = _suppressed_fdatasync


@pytest.fixture(autouse=True)
def _durable_writes(request: pytest.FixtureRequest) -> Iterator[None]:
    """Give a `durable`-marked test the real ``fsync`` back for its duration."""
    if request.node.get_closest_marker("durable") is None:
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
        _fsync_from_workers += int(output.get(_FSYNC_KEY, 0))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Report how many calls the suppression absorbed, across every process."""
    total = _fsync_suppressed + _fsync_from_workers
    terminalreporter.write_line(
        f"fsync: {total} call(s) suppressed this session."
    )


def _load_dotenv_if_available() -> None:
    """Load .env file from project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


_load_dotenv_if_available()


def _capture_host_provisioned_qdrant() -> tuple[Path, Path] | None:
    """Capture the real managed Qdrant install before pytest redirects it.

    ``pytest_configure`` replaces the status directory before session fixtures
    run. Resolve the production-managed install now, while the ambient config
    still names it, and retain only its binary and manifest paths. The binary
    is still re-verified from the copied manifest before execution.
    """
    from vaultspec_rag.qdrant_runtime._constants import (
        MANIFEST_FILENAME,
        QDRANT_SERVER_VERSION,
    )
    from vaultspec_rag.qdrant_runtime._provision import file_sha256
    from vaultspec_rag.qdrant_runtime._resolve import resolve_binary

    resolved = resolve_binary(QDRANT_SERVER_VERSION)
    if resolved is None or resolved.source != "provisioned" or not resolved.sha256:
        return None
    manifest = resolved.path.parent / MANIFEST_FILENAME
    if not manifest.is_file():
        return None
    if file_sha256(resolved.path).lower() != resolved.sha256.lower():
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


def _reset_singleton_config_caches() -> None:
    """Make early environment containment visible to both config layers."""
    from vaultspec_core.config import reset_config

    from vaultspec_rag.config._settings import reset_config as reset_rag_config

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

    from vaultspec_rag.tests._tier_gate import (
        MPS,
        enforce_serial_gpu_lane,
        selectable_slow_tiers,
    )

    enforce_serial_gpu_lane(config.option)

    global _gpu_borrower_target, _singleton_prior_env
    global _singleton_root, _singleton_root_owned, _singleton_pair_owned
    if _singleton_root is not None:
        return

    raw_markexpr = config.option.markexpr
    markexpr = raw_markexpr if isinstance(raw_markexpr, str) else ""
    if set(selectable_slow_tiers(markexpr)) - {MPS}:
        from vaultspec_rag.cli._gpu_lease import capture_borrower_service_target

        _gpu_borrower_target = capture_borrower_service_target()

    _singleton_prior_env = {name: os.environ.get(name) for name in _SINGLETON_ENV_NAMES}
    inherited_root = os.environ.get(_PYTEST_SINGLETON_ROOT_ENV)
    inherited_active = os.environ.get(_PYTEST_SINGLETON_ACTIVE_ENV) == "1"
    if inherited_active and inherited_root:
        root = Path(inherited_root).expanduser().resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="vaultspec-rag-pytest-")).resolve()
        _singleton_root_owned = True

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    pytest_temp_name = "pytest-temp" if not worker else f"pytest-temp-{worker}"
    config.option.basetemp = str(root / pytest_temp_name)
    base_name = "machine-singleton" if not worker else f"machine-singleton-{worker}"
    base = root / base_name
    # A nested pytest subprocess inherits the root and PYTEST_XDIST_WORKER, so
    # it derives the same directory pair as the live parent that spawned it.
    # Only the process that created the pair may reclaim it; otherwise the
    # child's teardown deletes the parent's basetemp mid-session.
    _singleton_pair_owned = not base.exists()
    status_dir = base / "status"
    qdrant_storage_dir = base / "qdrant-server" / "storage"
    status_dir.mkdir(parents=True, exist_ok=True)
    qdrant_storage_dir.mkdir(parents=True, exist_ok=True)

    os.environ[_PYTEST_SINGLETON_ACTIVE_ENV] = "1"
    os.environ[_PYTEST_SINGLETON_ROOT_ENV] = str(root)
    os.environ[_STATUS_DIR_ENV] = str(status_dir)
    os.environ[_QDRANT_STORAGE_DIR_ENV] = str(qdrant_storage_dir)

    from vaultspec_rag._test_isolation import (
        register_pytest_singleton_root,
        sweep_orphaned_singleton_roots,
    )

    _singleton_root = register_pytest_singleton_root(root)
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

    global _gpu_borrower_target, _singleton_prior_env, _singleton_root
    prior = _singleton_prior_env
    root = _singleton_root
    if prior is not None:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset_singleton_config_caches()
    if _PRIOR_PYTEST_SINGLETON_BOOTSTRAP is None:
        os.environ.pop(_PYTEST_SINGLETON_BOOTSTRAP_ENV, None)
    else:
        os.environ[_PYTEST_SINGLETON_BOOTSTRAP_ENV] = _PRIOR_PYTEST_SINGLETON_BOOTSTRAP
    if root is not None:
        from vaultspec_rag._test_isolation import (
            reclaim_singleton_paths,
            singleton_child_names,
        )

        worker = os.environ.get("PYTEST_XDIST_WORKER")
        reclaim_singleton_paths(
            root,
            owned_root=_singleton_root_owned,
            owned_pair=_singleton_pair_owned,
            keep_diagnostics=_session_failed,
            worker=worker,
        )
        if _session_failed:
            _, basetemp = singleton_child_names(worker)
            print(
                f"pytest: retained failure artifacts under {root / basetemp}",
                file=sys.stderr,
            )
    _singleton_prior_env = None
    _singleton_root = None
    _gpu_borrower_target = None


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
        from vaultspec_rag._test_isolation import reclaim_singleton_paths

        reclaim_singleton_paths(
            root,
            owned_root=_singleton_root_owned,
            owned_pair=_singleton_pair_owned,
            keep_diagnostics=_session_failed,
            worker=os.environ.get("PYTEST_XDIST_WORKER"),
        )


def _has_hf_token() -> bool:
    """Return True when Hugging Face auth is available to test code."""
    if os.environ.get("HF_TOKEN"):
        return True
    try:
        from huggingface_hub import get_token
    except ImportError:
        return False
    return bool(get_token())


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


def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Run every selected GPU tier inside one acknowledged borrower lease.

    Runs after deselection so only *selected* items are checked, which keeps a
    unit-only run free of every device precondition. A distributed session never
    reaches this hook - the plugin owns the run loop in the launched process and
    in each worker - which costs nothing, because a distributed GPU selection is
    already refused before collection.
    """
    from vaultspec_rag.cli._gpu_lease import BorrowGPUError, run_with_borrowed_gpu
    from vaultspec_rag.tests._tier_gate import (
        GPU_MARKERS,
        MPS,
        SLOW_TIERS,
        SUBPROCESS_GPU,
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
    if tiers & (GPU_MARKERS | {SUBPROCESS_GPU}) and not _has_hf_token():
        pytest.exit(
            "Hugging Face authentication is required for GPU "
            "tests (gated model naver/splade-v3). Set HF_TOKEN, "
            "put it in .env, or run `hf auth login` before running "
            "tests.",
            returncode=1,
        )
    if not tiers & SLOW_TIERS:
        return
    if any(
        "required_host_provisioned_qdrant_source" in item.fixturenames
        for item in cast("list[pytest.Function]", session.items)
    ):
        _require_host_provisioned_qdrant_for_gpu_tier()
    target = _gpu_borrower_target
    if target is None:
        pytest.exit(
            "No ready compatible machine-pointer service was captured before "
            "pytest isolated its managed paths. Start the runner's resident "
            "service before selecting a GPU tier.",
            returncode=1,
        )

    def run_selected_items() -> None:
        from vaultspec_rag._gpu_admission import (
            device_refusal_message,
            evaluate_device_admission,
        )

        admission = evaluate_device_admission()
        if not admission.admitted:
            pytest.exit(device_refusal_message(admission), returncode=1)
        for index, item in enumerate(session.items):
            nextitem = (
                session.items[index + 1] if index + 1 < len(session.items) else None
            )
            item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
            if session.shouldfail:
                raise session.Failed(session.shouldfail)
            if session.shouldstop:
                raise session.Interrupted(session.shouldstop)

    try:
        run_with_borrowed_gpu(
            requested_port=None,
            work=run_selected_items,
            target=target,
        )
    except BorrowGPUError as exc:
        pytest.exit(str(exc), returncode=1)
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
