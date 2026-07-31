"""Characterise the memory ceilings the indexers freeze at job admission.

This is the derivation that decides whether a running index job is killed for
memory. The two indexers reached it by separate routes, so every assertion here
is written against observed behaviour rather than against either implementation:
an expectation that has to be edited to accommodate a later refactor means job
admission changed, and that is never a silent move.

Host independence is deliberate. The device-derived CUDA branch reads real free
and total memory, so these tests exercise the ceiling paths that do not: an
absent CUDA device, and a positive operator ceiling, which is authoritative and
short-circuits the device read entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from .._units import bytes_to_mib, mib_to_bytes
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..index_profiles import SupportProfileLimits

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ..memory_probe import MemoryBudget

pytestmark = [pytest.mark.unit]

# Every ceiling here sits far above a test process's real RSS, because
# admission samples the live process once the budget is frozen: a ceiling
# chosen low enough to be crossed would fail on enforcement and never reach
# the derivation under test.
CONFIG_RSS_MIB = 16384.0
PROFILE_RSS_BELOW_CONFIG_MIB = 8192.0
PROFILE_RSS_ABOVE_CONFIG_MIB = 32768.0
PROFILE_CUDA_MIB = 6144.0
CONFIGURED_CUDA_MIB = 4096.0

type BudgetFactory = Callable[[Path, SupportProfileLimits | None, bool], "MemoryBudget"]


def _limits(*, rss_mib: float, cuda_mib: float) -> SupportProfileLimits:
    """Build real profile limits carrying the two enforced dimensions.

    The remaining dimensions are corpus counters that admission never reads;
    they only have to satisfy the profile's own positive-integer contract.
    """
    return SupportProfileLimits(
        source_files=10_000,
        source_bytes=1_000_000_000,
        generated_chunks=1_000_000,
        weighted_bytes=1_000_000_000,
        extracted_bytes=1_000_000_000,
        queue_bytes=1_000_000_000,
        rss_bytes=mib_to_bytes(rss_mib),
        cuda_bytes=mib_to_bytes(cuda_mib),
    )


def _model(uses_cuda: bool) -> Any:
    """Return what admission reads as the encoding device.

    Admission consumes exactly one thing from the model - ``device`` - so no
    weights are loaded here. The CUDA case still binds to the real
    ``EmbeddingModel`` and its real ``device`` property rather than to an
    ad-hoc object, so renaming that attribute breaks this test the same way it
    would break admission. The non-CUDA case is a genuine production shape: an
    indexer constructed before its model is resident reads ``device`` off
    ``None`` through ``getattr``.
    """
    if not uses_cuda:
        return None
    from ..embeddings import EmbeddingModel

    model = object.__new__(EmbeddingModel)
    model._device = "cuda"
    return model


def _code_budget(
    root: Path,
    limits: SupportProfileLimits | None,
    uses_cuda: bool,
) -> MemoryBudget:
    """Freeze one code-indexing budget and return it."""
    from ..indexer import CodebaseIndexer

    indexer = CodebaseIndexer(root, _model(uses_cuda), cast("Any", None))
    indexer._support_budget._support_limits = limits
    indexer._support_budget.begin_memory_budget()
    budget = indexer._support_budget._memory_budget
    assert budget is not None
    return budget


def _document_budget(
    root: Path,
    limits: SupportProfileLimits | None,
    uses_cuda: bool,
) -> MemoryBudget:
    """Freeze one document-indexing budget and return it.

    The document path takes its limits as an argument and has no ``None``
    case, so a caller passing ``None`` is a bug in the test rather than a
    behaviour to characterise.
    """
    from ..indexer import DocumentIndexer

    assert limits is not None
    indexer = DocumentIndexer(root, _model(uses_cuda), cast("Any", None))
    return indexer._begin_resource_budget(limits).memory_budget


BUDGETS: list[tuple[str, BudgetFactory]] = [
    ("code", _code_budget),
    ("document", _document_budget),
]
BOTH_INDEXERS = pytest.mark.parametrize(
    "derive",
    [factory for _, factory in BUDGETS],
    ids=[name for name, _ in BUDGETS],
)


@pytest.fixture
def pinned_ceilings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the configured ceilings so the derivation is host-independent.

    The CUDA ceiling is pinned to the auto-derive sentinel; the tests that
    characterise an operator override set it themselves.
    """
    monkeypatch.setenv(EnvVar.INDEX_RSS_CEILING_MIB.value, str(CONFIG_RSS_MIB))
    monkeypatch.setenv(EnvVar.INDEX_CUDA_CEILING_MIB.value, "0")
    monkeypatch.setenv(EnvVar.INDEX_CUDA_HEADROOM_MIB.value, "2048")
    reset_config()
    yield
    reset_config()


@pytest.mark.usefixtures("pinned_ceilings")
class TestAdmittedRssCeiling:
    """The admitted RSS ceiling is the tighter of the two declared bounds."""

    @BOTH_INDEXERS
    def test_profile_below_config_wins(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            False,
        )
        assert budget.rss_ceiling_mib == PROFILE_RSS_BELOW_CONFIG_MIB

    @BOTH_INDEXERS
    def test_config_below_profile_wins(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_ABOVE_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            False,
        )
        assert budget.rss_ceiling_mib == CONFIG_RSS_MIB

    def test_code_without_profile_limits_takes_the_configured_ceiling(
        self, tmp_path: Path
    ) -> None:
        """Admission before the profile resolves falls back to config alone.

        The code path measures its corpus before freezing the budget, so in a
        completed run the limits are always present. This is the defensive
        branch behind that ordering, and it must stay a real ceiling rather
        than becoming unbounded or zero.
        """
        budget = _code_budget(tmp_path, None, False)
        assert budget.rss_ceiling_mib == CONFIG_RSS_MIB

    def test_profile_bytes_convert_through_mebibytes(self, tmp_path: Path) -> None:
        """The profile bound is bytes and the ceiling is MiB.

        Pinned against a non-round byte count because a decimal-megabyte
        divisor would still pass every round-number assertion above while
        admitting roughly 5% more memory than the profile permits.
        """
        odd_bytes = 7_654_321_000
        limits = _limits(
            rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB
        )
        budget = _code_budget(
            tmp_path,
            SupportProfileLimits(
                source_files=limits.source_files,
                source_bytes=limits.source_bytes,
                generated_chunks=limits.generated_chunks,
                weighted_bytes=limits.weighted_bytes,
                extracted_bytes=limits.extracted_bytes,
                queue_bytes=limits.queue_bytes,
                rss_bytes=odd_bytes,
                cuda_bytes=limits.cuda_bytes,
            ),
            False,
        )
        assert budget.rss_ceiling_mib == bytes_to_mib(odd_bytes)


@pytest.mark.usefixtures("pinned_ceilings")
class TestCudaEnforcementGate:
    """A model that is not on CUDA admits no CUDA ceiling at all."""

    @BOTH_INDEXERS
    def test_no_cuda_device_admits_no_cuda_ceiling(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        """Off the GPU path the budget must not carry a CUDA ceiling.

        A frozen ceiling would be enforced against readings that are
        structurally zero, and the derived figure off-device is the profile
        default rather than anything the host can honour.
        """
        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            False,
        )
        assert budget.cuda_ceiling_mib is None

    @BOTH_INDEXERS
    def test_no_cuda_device_admits_no_baseline(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        """The resident-model baseline is meaningless without a device.

        Asserted separately from the ceiling because the two travel by
        different routes into the budget, and a consolidation that carried one
        across but not the other would still satisfy the ceiling assertion.
        """
        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            False,
        )
        assert budget.cuda_baseline_mib is None


class TestConfiguredCudaCeiling:
    """A positive operator ceiling is authoritative on both paths."""

    @pytest.fixture(autouse=True)
    def _operator_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        monkeypatch.setenv(EnvVar.INDEX_RSS_CEILING_MIB.value, str(CONFIG_RSS_MIB))
        monkeypatch.setenv(
            EnvVar.INDEX_CUDA_CEILING_MIB.value, str(CONFIGURED_CUDA_MIB)
        )
        monkeypatch.setenv(EnvVar.INDEX_CUDA_HEADROOM_MIB.value, "2048")
        reset_config()
        yield
        reset_config()

    @BOTH_INDEXERS
    def test_operator_ceiling_overrides_the_profile_figure(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        """The configured figure wins in either direction, profile included.

        Pinned with a configured ceiling BELOW the profile bound so a
        reintroduced one-way ``min`` clamp against the profile would still
        pass, and with the assertion on equality so a clamp in the other
        direction cannot.
        """
        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            True,
        )
        assert budget.cuda_ceiling_mib == CONFIGURED_CUDA_MIB

    @BOTH_INDEXERS
    def test_cuda_device_admits_the_resident_baseline(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        """On the GPU path the budget carries the resident-model baseline.

        Enforcement compares peaks net of this figure, so a budget that froze
        ``None`` here would charge every job for memory the resident models
        hold and reject work that fits.
        """
        from ..memory_probe import resident_cuda_baseline_mib

        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            True,
        )
        assert budget.cuda_baseline_mib == resident_cuda_baseline_mib()

    @BOTH_INDEXERS
    def test_rss_ceiling_is_unaffected_by_the_cuda_override(
        self, derive: BudgetFactory, tmp_path: Path
    ) -> None:
        """The two ceilings are independent; one knob must not move the other."""
        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            True,
        )
        assert budget.rss_ceiling_mib == PROFILE_RSS_BELOW_CONFIG_MIB


@pytest.mark.usefixtures("pinned_ceilings")
class TestAdmissionSamplesBeforeDispatch:
    """Freezing a budget also takes the pre-dispatch reading."""

    def test_code_admission_publishes_a_snapshot(self, tmp_path: Path) -> None:
        from ..indexer import CodebaseIndexer

        indexer = CodebaseIndexer(tmp_path, _model(False), cast("Any", None))
        indexer._support_budget._support_limits = _limits(
            rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB
        )
        assert indexer.memory_budget_snapshot is None

        indexer._support_budget.begin_memory_budget()

        snapshot = indexer.memory_budget_snapshot
        assert snapshot is not None
        assert snapshot.label == "before code dispatch"
        assert snapshot.rss_ceiling_mib == PROFILE_RSS_BELOW_CONFIG_MIB

    def test_document_admission_publishes_a_snapshot(self, tmp_path: Path) -> None:
        from ..indexer import DocumentIndexer

        indexer = DocumentIndexer(tmp_path, _model(False), cast("Any", None))

        budget = indexer._begin_resource_budget(
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB)
        )

        snapshot = budget.snapshot
        assert snapshot is not None
        assert snapshot.label == "before document dispatch"
        assert snapshot.rss_ceiling_mib == PROFILE_RSS_BELOW_CONFIG_MIB
        # The document run also publishes the same budget on the indexer, which
        # is what the service reads for its live memory reporting.
        assert indexer._memory_budget is budget.memory_budget


class TestNoHeadroomIsRefusedAtAdmission:
    """A ceiling that admits no forward is refused before dispatch.

    Enforcement compares peak and ceiling net of the resident baseline, so a
    ceiling at or below that baseline can never admit anything. Enforcing it
    produced a run's worth of mid-forward failures each reporting a "0.0 MiB
    ceiling" - a figure that named neither the baseline that consumed it nor
    the knob that would restore it.

    The refusal wiring is exercised where a real resident baseline exists, in
    the integration suite; this module has no models loaded, so its baseline is
    structurally zero and no ceiling can be pinned beneath it. What lives here
    is the decision itself and the CPU-path exemption.
    """

    @BOTH_INDEXERS
    def test_the_cpu_path_is_not_refused(
        self,
        derive: BudgetFactory,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Off the GPU the ceiling is inert, so an empty one costs nothing.

        Every reading it would be compared against is structurally zero there.
        Refusing would ground a CPU-side run on a device figure that never
        applies to it.
        """
        monkeypatch.setenv(EnvVar.INDEX_CUDA_CEILING_MIB.value, "0.5")
        monkeypatch.setenv(EnvVar.INDEX_RSS_CEILING_MIB.value, str(CONFIG_RSS_MIB))
        reset_config()

        budget = derive(
            tmp_path,
            _limits(rss_mib=PROFILE_RSS_BELOW_CONFIG_MIB, cuda_mib=PROFILE_CUDA_MIB),
            False,
        )

        assert budget.cuda_ceiling_mib is None

    def test_an_exhausted_device_names_the_device_not_the_knob(self) -> None:
        """A collapsed DERIVED ceiling reports free memory, not configuration.

        Driven at the decision rather than through admission: reaching this
        branch for real means holding the device at zero free memory, and this
        suite shares its GPU. The two branches differ only in which detail they
        raise, so the decision is where that difference lives.
        """
        from .._job_errors import JobError, JobErrorKind
        from ..indexer._resource_ceilings import _require_cuda_headroom

        with pytest.raises(JobError) as refused:
            _require_cuda_headroom(
                ceiling_mib=0.0,
                baseline_mib=6301.1,
                configured_mib=0.0,
            )

        assert refused.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
        assert "6301.1 MiB resident model baseline" in refused.value.detail
        assert "free device memory" in refused.value.detail
        assert "configured" not in refused.value.detail

    def test_any_positive_headroom_is_admitted(self) -> None:
        """The threshold is no-headroom-at-all, never a minimum size.

        A deliberately tiny budget is a legitimate configuration, and the tests
        that prove the ceiling still FIRES pin exactly that: a hair above the
        measured reading. A floor with any positive width would refuse them at
        admission and destroy the mid-run coverage they exist for.
        """
        from ..indexer._resource_ceilings import _require_cuda_headroom

        _require_cuda_headroom(
            ceiling_mib=6301.1 + 0.001,
            baseline_mib=6301.1,
            configured_mib=6301.1 + 0.001,
        )
