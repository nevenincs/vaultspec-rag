"""One root's code workload measurement and its enforced memory budget.

A support-profile limit is checked against the running measurement on every
update, and the memory budget's checkpoints feed the same measurement's
resource high-water. Splitting the two would leave the limit check and the
high-water merge racing to stay in sync with each other, so one collaborator
owns both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._job_errors import JobError, JobErrorKind
from ..index_profiles import SupportMeasurement, get_index_support_profile

if TYPE_CHECKING:
    import contextlib
    import pathlib
    from collections.abc import Iterable, Iterator

    from ..embeddings import EmbeddingModel
    from ..index_profiles import SupportProfileLimits
    from ..memory_probe import MemoryBudget, MemoryBudgetSnapshot
    from ._streaming_types import CodeFileSegment


class CodeSupportBudget:
    """Own one root's support measurement and enforced memory budget."""

    def __init__(self, model: EmbeddingModel) -> None:
        """Bind the budget to the model whose ceilings it enforces.

        Args:
            model: Embedding model measured for GPU ceiling admission.
        """
        self._model = model
        self._support_measurement = SupportMeasurement(0, 0)
        self._support_limits: SupportProfileLimits | None = None
        self._support_profile_name: str | None = None
        self._memory_budget: MemoryBudget | None = None

    @property
    def measurement(self) -> SupportMeasurement:
        """Return the latest immutable code workload measurement snapshot."""
        return self._support_measurement

    @property
    def memory_budget(self) -> MemoryBudget | None:
        """Return the admitted memory budget, or ``None`` before admission."""
        return self._memory_budget

    def begin_memory_budget(self) -> None:
        """Freeze and sample one production memory budget before dispatch."""
        from ..memory_probe import MemoryBudget
        from ._resource_ceilings import admit_index_ceilings

        ceilings = admit_index_ceilings(self._model, self._support_limits)
        self._memory_budget = MemoryBudget(
            rss_ceiling_mib=ceilings.rss_ceiling_mib,
            cuda_ceiling_mib=ceilings.enforced_cuda_ceiling_mib,
            cuda_baseline_mib=ceilings.cuda_baseline_mib,
        )
        self.sample_memory_budget("before code dispatch")

    def forward_peak_recording(self) -> contextlib.AbstractContextManager[None]:
        """Route this thread's forward-peak captures into the job budget."""
        import contextlib

        from ..memory_probe import record_forward_peaks

        budget = self._memory_budget
        if budget is None:
            return contextlib.nullcontext()
        return record_forward_peaks(budget.record_forward_peak_mib)

    def sample_memory_budget(self, label: str) -> MemoryBudgetSnapshot:
        """Enforce the current budget and retain its resource high-water."""
        from ..memory_probe import snapshot_resource_bytes

        budget = self._memory_budget
        if budget is None:
            raise RuntimeError("code memory budget was not admitted")
        snapshot = budget.sample(label)
        rss_bytes, cuda_bytes = snapshot_resource_bytes(snapshot)
        self._record_resource_measurement(
            rss_bytes=rss_bytes,
            cuda_bytes=cuda_bytes,
        )
        return snapshot

    def fail_cuda_oom(self, label: str, exc: BaseException) -> None:
        """Translate allocator exhaustion through the admitted budget latch."""
        budget = self._memory_budget
        if budget is None:
            raise RuntimeError("code memory budget was not admitted") from exc
        budget.fail_cuda_oom(label=label, detail=str(exc))

    def begin_support_measurement(
        self,
        paths: Iterable[pathlib.Path],
    ) -> None:
        """Measure source dimensions by streaming path metadata only."""
        from ..config._settings import get_config

        source_files = 0
        source_bytes = 0
        for path in paths:
            try:
                size = path.stat().st_size
            except OSError:
                # A tree under active edit loses files between the walk that
                # enumerated them and this measurement. This pass only sizes
                # the run; a file that is already gone contributes nothing to
                # it and will never be read. Ending an entire index here - on
                # a stat, before a single chunk is produced - is the same
                # defect the chunk sink converges for a vanished source, and
                # on a tree somebody is working in it repeats indefinitely.
                continue
            source_files += 1
            source_bytes += size
        profile = get_index_support_profile(get_config().index_support_profile)
        self._support_limits = profile.code
        self._support_profile_name = profile.name
        self._set_support_measurement(
            SupportMeasurement(
                source_files=source_files,
                source_bytes=source_bytes,
                queue_bytes=int(get_config().index_queue_max_bytes),
            )
        )

    def record_extracted_bytes(self, extracted_bytes: int) -> None:
        """Add extractor output bytes without retaining output beyond one file."""
        if extracted_bytes <= 0:
            return
        current = self.measurement
        self._set_support_measurement(
            SupportMeasurement(
                source_files=current.source_files,
                source_bytes=current.source_bytes,
                generated_chunks=current.generated_chunks,
                weighted_bytes=current.weighted_bytes,
                extracted_bytes=current.extracted_bytes + extracted_bytes,
                queue_bytes=current.queue_bytes,
                rss_bytes=current.rss_bytes,
                cuda_bytes=current.cuda_bytes,
            )
        )

    def _record_resource_measurement(
        self,
        *,
        rss_bytes: int,
        cuda_bytes: int,
    ) -> None:
        """Merge observed process and CUDA high-water dimensions."""
        current = self.measurement
        self._set_support_measurement(
            SupportMeasurement(
                source_files=current.source_files,
                source_bytes=current.source_bytes,
                generated_chunks=current.generated_chunks,
                weighted_bytes=current.weighted_bytes,
                extracted_bytes=current.extracted_bytes,
                queue_bytes=current.queue_bytes,
                rss_bytes=max(current.rss_bytes, rss_bytes),
                cuda_bytes=max(current.cuda_bytes, cuda_bytes),
            )
        )

    def _set_support_measurement(self, measured: SupportMeasurement) -> None:
        """Publish one snapshot and reject its first exceeded dimension."""
        self._support_measurement = measured
        limits = self._support_limits
        exceeded = limits.exceeded_by(measured) if limits is not None else None
        if exceeded is None:
            return
        dimension, actual, limit = exceeded
        raise JobError(
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
            f"code {dimension} is {actual}; profile "
            f"{self._support_profile_name!r} permits {limit}",
        )

    def measure_code_segments(
        self,
        segments: Iterable[CodeFileSegment],
    ) -> Iterator[CodeFileSegment]:
        """Measure generated workload while retaining one bounded segment."""
        for segment in segments:
            current = self.measurement
            self._set_support_measurement(
                SupportMeasurement(
                    source_files=current.source_files,
                    source_bytes=current.source_bytes,
                    generated_chunks=current.generated_chunks + len(segment.chunks),
                    weighted_bytes=current.weighted_bytes + segment.estimated_bytes,
                    extracted_bytes=current.extracted_bytes,
                    queue_bytes=current.queue_bytes,
                    rss_bytes=current.rss_bytes,
                    cuda_bytes=current.cuda_bytes,
                )
            )
            yield segment
