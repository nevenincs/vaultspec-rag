"""Device-load admission: refuse a model load onto a card without room.

This project is GPU-only and runs on one device. Nothing about a CUDA device
being *present* says there is room on it: a second process that loads the
embedding and reranker stacks onto an already-full card starves every tenant on
it and can take the host down. So a model load is admitted rather than assumed -
one synchronous reading of device-wide free memory against a configured floor,
taken once per process before the first load and latched afterwards.

Two properties make the gate correct rather than merely present:

- **The reading is only meaningful before the first load.** Once this process's
  own models are resident, the device-wide figure counts that residency as
  pressure, so a gate that re-read it would eventually refuse the process it
  already admitted. The latch is therefore a correctness device, not an
  optimisation, and a declared release of the resident stack clears it so the
  next load is admitted against what the card actually has. Only a verdict that
  reached the floor comparison latches: latching one that never got a figure
  would retire the gate on a reading that was never taken.
- **Detection alone cannot close the race.** Two processes can read the same
  free figure, both find room, and both load. An OS advisory lock held across
  the check-and-load window makes that sequence atomic between processes: a
  concurrent loader is refused instantly instead of reading a figure that is
  about to change under it. The lock is never held across residency, so it
  cannot wedge anything, and process death releases it, so no state goes stale.

The verdict itself is a read-only predicate any surface may consume - operator
diagnostics and pre-flight included - so it never raises: a torch-free host, a
CPU-only build, and a driver that refuses the query all report a reason instead
of an exception. Every torch import stays inside the guarded device probe this
module delegates to, so importing this module pulls no torch and the call paths
that must stay torch-free do.

The lock file is anchored machine-globally in the system temp directory,
independent of every configured directory. That is deliberate: the device is
machine hardware rather than per-instance state, so a lock resolved through
configuration would be private to whichever tree the caller happened to be
pointed at and would exclude nothing.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from contextlib import AbstractContextManager

    from ._anchor_claim import AnchorClaim
    from .memory_probe import CudaDeviceMemory

logger = logging.getLogger(__name__)

__all__ = [
    "DEVICE_CONTENDED_MESSAGE",
    "REASON_BELOW_FLOOR",
    "REASON_LOAD_IN_PROGRESS",
    "REASON_NO_CUDA",
    "REASON_TORCH_ABSENT",
    "DeviceAdmission",
    "admission_from_reading",
    "admit_gpu_load",
    "clear_gpu_admission_latch",
    "device_contended_message",
    "device_load_reading",
    "device_load_window",
    "device_load_wire",
    "evaluate_device_admission",
    "load_window_lock_path",
]

# Stable machine-readable refusal causes. A consumer branches on these rather
# than on prose, so they are spelled once here and never restated at a call
# site: free memory sits below the floor; another process holds the load
# window; torch is installed but exposes no device; torch is absent entirely.
REASON_BELOW_FLOOR = "below_floor"
REASON_LOAD_IN_PROGRESS = "load_in_progress"
REASON_NO_CUDA = "no_cuda"
REASON_TORCH_ABSENT = "torch_absent"

#: The causes this gate refuses on. The other two are not its verdict to give:
#: an absent torch or an absent device is the loader's own typed failure, and
#: answering it here too would give one condition two messages.
_REFUSING_REASONS = frozenset({REASON_BELOW_FLOOR, REASON_LOAD_IN_PROGRESS})

DEVICE_CONTENDED_MESSAGE = (
    "CUDA device too contended to load models: vaultspec-rag is a GPU-only "
    "project and refuses to bring a model stack up on a card that cannot hold "
    "it, because doing so starves every consumer on the device rather than "
    "failing one of them. Wait for the other consumer to finish, stop it, or - "
    "if this card genuinely needs less headroom than the shipped floor - lower "
    "VAULTSPEC_RAG_GPU_ADMISSION_FLOOR_MIB."
)

#: The machine-global lock file's name. One name for the whole machine is the
#: point: the device it guards is singular.
_LOCK_FILENAME = "vaultspec-rag-gpu-load-window.lock"

_REASON_PHRASES = {
    REASON_BELOW_FLOOR: "free device memory is below the admission floor",
    REASON_LOAD_IN_PROGRESS: "another process holds the model-load window",
    REASON_NO_CUDA: "no CUDA device is available",
    REASON_TORCH_ABSENT: "torch is not installed",
}


@dataclass(frozen=True, slots=True)
class DeviceAdmission:
    """One verdict on whether the device can take a model load right now.

    ``reason`` is empty exactly when ``admitted`` is true; otherwise it carries
    one stable token naming the cause. ``free_mib`` and ``total_mib`` are
    ``None`` when the corresponding figure could not be read, which on a
    GPU-only path is itself disqualifying but is reported rather than raised so
    a torch-free host can still answer the question.
    """

    admitted: bool
    free_mib: int | None
    total_mib: int | None
    floor_mib: int
    reason: str


def device_contended_message(admission: DeviceAdmission) -> str:
    """Render one operator-facing refusal naming free, floor, and the way out.

    The reading belongs in the message because the alternative is an operator
    told only that the device is busy, with no figure to act on and no way to
    tell a card 200 MiB short from one 8 GiB short.
    """
    free = (
        "an unreadable amount"
        if admission.free_mib is None
        else f"{admission.free_mib} MiB"
    )
    total = (
        "" if admission.total_mib is None else f" of {admission.total_mib} MiB total"
    )
    phrase = _REASON_PHRASES.get(admission.reason, "the device did not admit a load")
    return (
        f"{DEVICE_CONTENDED_MESSAGE} Observed {free} free{total} against a "
        f"{admission.floor_mib} MiB floor ({phrase})."
    )


def device_load_wire(admission: DeviceAdmission) -> dict[str, object]:
    """Project one verdict into its stable wire shape.

    The health payload, the jobs listing, and the ``server preflight`` verb
    all publish a device-load reading over JSON, and every one of them must
    publish the same shape - a consumer reading one must not have to
    special-case another.
    """
    return {
        "free_mib": admission.free_mib,
        "total_mib": admission.total_mib,
        "floor_mib": admission.floor_mib,
        "admitted": admission.admitted,
        "reason": admission.reason,
    }


def _workload_floor_mib() -> int:
    """Derive the floor from what the configured workload actually demands.

    The floor answers "is there room for what this process is about to bring
    up", so it is a property of the workload rather than of the card: the model
    stack occupies what it occupies whether the device is 8 GiB or 48 GiB. The
    support profile already declares that demand per content domain, and the
    per-job CUDA ceiling is derived from the same figure, so taking it from
    there keeps one declaration behind both.

    The larger of the two domains, because either may be the one that runs and
    a floor sized to the smaller would admit a load the card cannot hold.

    A shipped absolute would have been a statement about one machine: pinned to
    a 16 GiB card it refuses every load on a smaller one - permanently, since
    free memory can never reach it - and under-protects a larger one, where the
    figure it names is reached with two stacks still able to collide.
    """
    from ._units import bytes_to_mib
    from .config._settings import get_config
    from .index_profiles import get_index_support_profile

    profile = get_index_support_profile(get_config().index_support_profile)
    demand_bytes = max(profile.code.cuda_bytes, profile.document.cuda_bytes)
    return int(bytes_to_mib(demand_bytes))


def _configured_floor_mib() -> int:
    """Return the admission floor in MiB. Never raises.

    A positive configured value is an authoritative operator override, in
    mebibytes, for a card whose owner knows it better than any default can -
    the same treatment the CUDA ceiling gives its own override. Unset (zero, or
    a value below it) means derive, so the shipped configuration states no
    device size anywhere.

    A malformed operator value must not make the gate unusable: the floor IS
    the predicate, so declining to answer would convert one bad environment
    variable into a blanket refusal of GPU work. A host on which even the
    derivation fails reports no floor, which admits everything - the behaviour
    that preceded this gate, and the right degradation for a process that
    cannot read its own configuration.
    """
    configured = 0
    try:
        from .config._settings import get_config

        configured = int(get_config().gpu_admission_floor_mib)
    except Exception:
        logger.warning(
            "the configured GPU admission floor is unusable; deriving it from "
            "the configured workload instead",
            exc_info=True,
        )
    if configured > 0:
        return configured
    try:
        return _workload_floor_mib()
    except Exception:
        logger.warning(
            "the GPU admission floor could not be derived; admitting every load",
            exc_info=True,
        )
        return 0


def admission_from_reading(
    reading: CudaDeviceMemory,
    *,
    floor_mib: int,
) -> DeviceAdmission:
    """Derive one verdict from one device reading and one floor.

    The measurement and the judgement are separate concerns: what a given pair
    of figures means for a load does not depend on how they were obtained.
    Keeping them apart means every outcome that matters - an absent torch, a
    CPU-only build, a driver that answered presence but refused the memory
    query, a figure exactly at the floor - is exercisable without a machine that
    happens to present it, and without initialising a CUDA context to ask.

    A figure exactly at the floor is admitted; only one below it is refused.

    The reading arrives as a float and the verdict carries a whole number of
    mebibytes, and the truncation between them cannot change the outcome: the
    floor is an integer, and for an integer bound a truncated value clears it if
    and only if the original did. So the comparison decides exactly what it
    would have decided on the float, and the reported figure never claims
    headroom the device did not have.
    """
    total_mib = None if reading.total_mib is None else int(reading.total_mib)
    if not reading.torch_present:
        return DeviceAdmission(
            admitted=False,
            free_mib=None,
            total_mib=total_mib,
            floor_mib=floor_mib,
            reason=REASON_TORCH_ABSENT,
        )
    if not reading.cuda_present:
        return DeviceAdmission(
            admitted=False,
            free_mib=None,
            total_mib=total_mib,
            floor_mib=floor_mib,
            reason=REASON_NO_CUDA,
        )
    if reading.free_mib is None:
        # The device answers as present but refused the memory query. Admitting
        # is the honest reading of "unmeasurable": the per-job CUDA ceiling and
        # the allocator's own backoff are both still in force, and turning a
        # driver hiccup into a refusal of all GPU work costs more than the
        # protection it would buy.
        logger.warning(
            "device free memory is unreadable; admitting the load on presence alone",
        )
        return DeviceAdmission(
            admitted=True,
            free_mib=None,
            total_mib=total_mib,
            floor_mib=floor_mib,
            reason="",
        )
    # Decision-preserving against an integer floor, and understating rather
    # than overstating free memory in the figure the operator is shown.
    free_mib = int(reading.free_mib)
    admitted = free_mib >= floor_mib
    return DeviceAdmission(
        admitted=admitted,
        free_mib=free_mib,
        total_mib=total_mib,
        floor_mib=floor_mib,
        reason="" if admitted else REASON_BELOW_FLOOR,
    )


def evaluate_device_admission() -> DeviceAdmission:
    """Return one verdict on the device's present capacity to take a load.

    The single predicate every surface reads. It never raises and never
    mutates: on a torch-free host, a CPU-only build, or a device whose driver
    refuses the memory query it reports a cause rather than propagating one, so
    the same call is safe from a diagnostics reporter and from the load gate.

    Reading free memory does initialise a CUDA context on a device that has
    one, which is why this belongs to load admission and operator pre-flight
    and not to a probe on a hot serving path.
    """
    try:
        from .memory_probe import cuda_device_memory

        return admission_from_reading(
            cuda_device_memory(),
            floor_mib=_configured_floor_mib(),
        )
    except Exception:
        logger.warning(
            "GPU admission could not be evaluated; reporting the device as unreadable",
            exc_info=True,
        )
        return DeviceAdmission(
            admitted=False,
            free_mib=None,
            total_mib=None,
            floor_mib=0,
            reason=REASON_NO_CUDA,
        )


def device_load_reading() -> dict[str, object] | None:
    """Take one device-load reading and project it, or ``None`` on failure.

    :func:`evaluate_device_admission` is documented never to raise, but this
    still guards the call: a caller here must never fail a request because a
    diagnostic reading could not be taken, so an unreadable probe is reported
    absent rather than surfacing as an error. Callers that poll this at a fast
    cadence (the jobs listing) cache the result themselves; this function
    always takes a fresh reading.
    """
    try:
        admission = evaluate_device_admission()
    except Exception:
        logger.warning(
            "device-load admission probe failed; reporting it absent",
            exc_info=True,
        )
        return None
    return device_load_wire(admission)


def load_window_lock_path() -> Path:
    """Path of the machine-global model-load window lock.

    Anchored in the system temp directory rather than through configuration,
    because the device is one piece of machine hardware: a lock relocated with
    a configured directory would be private to each caller's tree and would
    serialise nothing.
    """
    return Path(tempfile.gettempdir()) / _LOCK_FILENAME


def _warn_unserialised_window(claim: AnchorClaim) -> None:
    """Report a load window that could not be serialised, naming which fault.

    The window is not held after this, and the caller proceeds on the
    free-memory floor alone: the anchor is a coordination mechanism rather than
    evidence about the device, and turning a filesystem fault into a total
    refusal of GPU work costs more than the cross-process half of the
    protection it would buy. So it is logged rather than raised - but it is
    logged, because the remaining protection is weaker than the one an operator
    configured.
    """
    if isinstance(claim.fault, ImportError):
        logger.warning(
            "this platform ships no advisory-lock primitive; the GPU load "
            "window cannot be serialised and the free-memory floor stands "
            "alone",
            exc_info=claim.fault,
        )
        return
    logger.warning(
        "the GPU load-window lock at %s could not be opened; admitting on "
        "the free-memory floor alone",
        claim.anchor,
        exc_info=claim.fault,
    )


@contextmanager
def device_load_window(
    *,
    anchor: Path | None = None,
    reading: CudaDeviceMemory | None = None,
) -> Generator[DeviceAdmission]:
    """Yield one admission verdict with the load window held for its duration.

    The lock is taken without blocking and released on exit, so it brackets the
    check and the load that follows it and nothing else - never the residency
    that load establishes, which is what makes an open-ended hold impossible. A
    caller arriving while another process is inside the window is refused with
    ``load_in_progress`` rather than handed a free figure about to change under
    it.

    Exactly one thread of this process may be inside the window at a time.
    :func:`admit_gpu_load` guarantees that, and has to: the OS lock is taken per
    descriptor, so a second thread of the same process would be refused by this
    process's own hold and read it as foreign contention.

    *anchor* names the lock file, defaulting to the machine-global one, and
    *reading* supplies the device observation instead of probing for one. Both
    are parameters so the window's real locking and refusal behaviour stay
    exercisable - without contending for the machine's own anchor, which
    another tenant may legitimately be holding, and without initialising a CUDA
    context to ask a question whose answer is already known.
    """
    from ._anchor_claim import AnchorOutcome, claim_anchor, release_anchor_claim

    claim = claim_anchor(anchor or load_window_lock_path(), create_parent=True)
    if claim.outcome is AnchorOutcome.CONTENDED:
        yield DeviceAdmission(
            admitted=False,
            free_mib=None,
            total_mib=None,
            floor_mib=_configured_floor_mib(),
            reason=REASON_LOAD_IN_PROGRESS,
        )
        return
    if claim.outcome is AnchorOutcome.UNAVAILABLE:
        _warn_unserialised_window(claim)
    try:
        yield (
            evaluate_device_admission()
            if reading is None
            else admission_from_reading(reading, floor_mib=_configured_floor_mib())
        )
    finally:
        if claim.descriptor is not None:
            release_anchor_claim(claim.descriptor)


_admission_guard = threading.Lock()
_admitted = False
#: Whether a load has already run in this process under a verdict that never
#: reached the floor comparison. It is what stops the retry the latch rule
#: opens from refusing work on a figure it cannot attribute: once a load has gone
#: through, free memory reflects this process's own residency, and a reading
#: below the floor may be describing the models this process just brought up
#: rather than a foreign tenant.
_unattributable_load = False


def _floor_was_evaluated(admission: DeviceAdmission) -> bool:
    """Whether *admission* actually compared a free figure against the floor.

    The distinction the latch turns on. Three of the four verdicts this module
    produces never reach the comparison - an absent torch, an absent device,
    and a driver that answered presence but refused the memory query - and all
    three carry no free figure, so the figure's presence is the discriminator
    rather than a second flag that could disagree with it.
    """
    return admission.free_mib is not None


def clear_gpu_admission_latch() -> None:
    """Retire this process's standing admission after a resident release.

    A verdict is taken against the device as it was before this process loaded
    anything, so it stays honest only while that load is still resident. Once
    the resident stack has been released the verdict describes a device state
    that no longer exists, and a later reload has to be admitted against what
    the card actually holds. Clearing costs one extra reading on the next load;
    not clearing rides a stale verdict for the rest of the process's life.

    The unattributable-load flag is retired with it: a release is exactly the
    event that makes free memory attributable again, so carrying that flag
    across one would let the next load ride an allowance earned by residency
    that no longer exists.
    """
    global _admitted, _unattributable_load
    with _admission_guard:
        _admitted = False
        _unattributable_load = False


def admit_gpu_load[T](
    load: Callable[[], T],
    *,
    window: Callable[[], AbstractContextManager[DeviceAdmission]] = device_load_window,
) -> T:
    """Run *load* under one device admission per process, latched on success.

    The first call evaluates admission inside the load window and raises
    ``RuntimeError`` when the device is contended. Every later call runs *load*
    directly, so it costs exactly what it did before this gate existed - and,
    the load-bearing half, it takes no second reading, which is what stops the
    gate from mistaking this process's own residency for foreign pressure.

    The process-local guard is what makes the OS lock safe. Two threads racing
    the first load would otherwise have the second refused by this process's own
    hold, so exactly one thread ever enters the window; the other waits for its
    verdict and then finds the latch set.

    *load* is invoked at most once and its own failures propagate untouched: an
    absent torch or an absent device is the loader's verdict to give, and
    restating it here would give one condition two messages. *window* is the
    admission source, a parameter so the sequencing this function owns - the
    latch, the thread serialisation, the refusal mapping - is exercisable over a
    known verdict rather than only on a host with a real device.

    Only a verdict that reached the floor comparison latches. A verdict that
    never got a free figure - a driver that refused the memory query, or a probe
    that failed outright - is passed through to the loader as before, but
    latching it would retire the gate on the strength of a reading that was
    never taken: one transient probe failure on a working device would leave the
    floor unevaluated for the life of the process, with the gate still
    reporting itself present. An unverifiable observation must not shorten
    protection, and permanently is the worst way for it to do so.

    The retry that opens costs at most one further window entry per load site.
    ``load_torch`` is called once per model construction and each site is behind
    its own already-constructed guard, so a process makes a handful of these
    calls in total; the device probe caches its torch lookup, so a repeat costs
    a memory query and an uncontended lock claim rather than an import. On a
    host whose probe fails permanently the repeats are bounded by that call
    count, not by time, and the warning the unreadable reading emits repeats
    with them - a handful of lines per process, which is a signal rather than a
    flood, and the honest one to leave in place while the device cannot answer.
    """
    global _admitted, _unattributable_load
    if _admitted:
        return load()
    with _admission_guard:
        if _admitted:
            return load()
        with window() as admission:
            if admission.reason in _REFUSING_REASONS:
                if not _unattributable_load:
                    raise RuntimeError(device_contended_message(admission))
                # A load already went through here without an evaluated
                # verdict, so this process holds residency the figure below
                # cannot be separated from. Refusing now would report this
                # process's own models as foreign contention and fail the
                # second stack it needs - the very inversion the latch exists
                # to prevent. Reported rather than acted on, and the evaluated
                # verdict latches below, so this is said once per process.
                logger.warning(
                    "%s (a load already succeeded here without an evaluated "
                    "verdict, so this figure cannot be told apart from this "
                    "process's own residency; the load proceeds)",
                    device_contended_message(admission),
                )
            result = load()
            evaluated = _floor_was_evaluated(admission)
        if evaluated:
            _admitted = True
        else:
            _unattributable_load = True
        return result
