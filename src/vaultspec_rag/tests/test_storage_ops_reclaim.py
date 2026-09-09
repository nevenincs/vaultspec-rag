"""test storage ops: the reclaim half."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import root_collection_prefix
from ..storage_identity import load_identity, record_identity
from ..storage_migration import MigrateResult, carry_migrated_identity
from ..storage_reclamation import (
    ReclaimPolicy,
    evaluate_reclaim,
)
from ..storage_reconciliation import GeometryEntry, plan_reconcile
from ..store_schema import (
    CODE_COLLECTION,
    SERVER_SEGMENT_NUMBER,
)
from .test_storage_ops import (
    _NOW,
    _POLICY,
    _collection_of,
    _CycleClient,
    _identity,
    _orphaned_namespace,
    _outcome_for,
    _run_cycle,
    _ScriptedClient,
    _survey,
    _temp_survey,
)

if TYPE_CHECKING:
    from pathlib import Path

    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.unit]


class TestMigrateCarriesIdentity:
    """A copied namespace inherits provenance, or honestly inherits none.

    Pure filesystem: the carry only touches the two identity homes and the
    migrate results it is handed, so it needs no server. The real copy is
    covered against a live daemon at the integration tier.
    """

    @staticmethod
    def _migrated(source: str, target: str) -> list[MigrateResult]:
        return [MigrateResult(source, target, "migrated", 1)]

    def test_local_to_server_carries_the_source_stamp(self, tmp_path: Path) -> None:
        """The source's own record moves onto the remapped target name.

        Mutation it catches: stamping the destination with
        ``current_identity()`` instead of the loaded source identity, which
        asserts that this process produced vectors it only copied - the exact
        laundering that lets a namespace claim conformance it never
        established. The asserted model is one no running configuration would
        ever produce, so a restamp cannot accidentally satisfy it.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"
        record_identity(
            root,
            backend="local",
            collection="vault_docs",
            identity=_identity(dense_model="superseded/dense"),
            local_dir=local_dir,
        )

        carried = carry_migrated_identity(
            root,
            name_map={"vault_docs": target},
            to_backend="server",
            local_dir=local_dir,
            results=self._migrated("vault_docs", target),
        )

        assert carried == [target]
        got = load_identity(root, backend="server", collection=target)
        assert got is not None
        assert got.dense_model == "superseded/dense"

    def test_server_to_local_carries_into_the_sidecar(self, tmp_path: Path) -> None:
        """The reverse direction lands in the other home, keyed by bare name.

        Mutation it catches: writing both directions to one home, which leaves
        the destination of a server-to-local migrate unverifiable because local
        reads never consult the manifest.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        source = f"{prefix}vault_docs"
        record_identity(
            root,
            backend="server",
            collection=source,
            identity=_identity(dense_model="superseded/dense"),
        )

        carried = carry_migrated_identity(
            root,
            name_map={source: "vault_docs"},
            to_backend="local",
            local_dir=local_dir,
            results=self._migrated(source, "vault_docs"),
        )

        assert carried == ["vault_docs"]
        got = load_identity(
            root, backend="local", collection="vault_docs", local_dir=local_dir
        )
        assert got is not None
        assert got.dense_model == "superseded/dense"

    def test_an_unstamped_source_leaves_the_target_unverifiable(
        self, tmp_path: Path
    ) -> None:
        """Copying provenance nobody recorded must invent none.

        Mutation it catches: falling back to ``current_identity()`` when the
        source carries no stamp, which manufactures the very claim the record
        exists to prove and scores a pre-stamping namespace as conforming the
        moment it is moved.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"

        carried = carry_migrated_identity(
            root,
            name_map={"vault_docs": target},
            to_backend="server",
            local_dir=local_dir,
            results=self._migrated("vault_docs", target),
        )

        assert carried == []
        assert load_identity(root, backend="server", collection=target) is None

    def test_a_copy_that_did_not_happen_carries_nothing(self, tmp_path: Path) -> None:
        """Only an applied copy earns provenance.

        Mutation it catches: iterating ``name_map`` without consulting the
        migrate results, which stamps a target that a skipped or failed copy
        never wrote - a namespace claiming provenance for data that is not
        there.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"
        record_identity(
            root,
            backend="local",
            collection="vault_docs",
            identity=_identity(),
            local_dir=local_dir,
        )

        carried = carry_migrated_identity(
            root,
            name_map={"vault_docs": target},
            to_backend="server",
            local_dir=local_dir,
            results=[
                MigrateResult("vault_docs", target, "skipped", 1, "target_exists")
            ],
        )

        assert carried == []
        assert load_identity(root, backend="server", collection=target) is None


class TestEvaluateReclaim:
    """The stacked safety gates, tier windows, and per-cycle cap."""

    def test_unstamped_orphan_is_pending(self) -> None:
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")], {}, now=_NOW, policy=_POLICY
        )
        assert [d.action for d in decisions] == ["pending"]
        assert decisions[0].reason == "grace_started"

    def test_young_orphan_is_pending(self) -> None:
        stamp = (_NOW - timedelta(hours=23)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")],
            {"r000000000001_": stamp},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "pending"
        assert (decisions[0].reason or "").startswith("grace_remaining")

    def test_aged_empty_orphan_is_eligible(self) -> None:
        stamp = (_NOW - timedelta(hours=25)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")],
            {"r000000000001_": stamp},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "reclaim_empty"
        assert decisions[0].tier == "empty"

    def test_data_tier_needs_the_longer_window(self) -> None:
        # Old enough for the empty tier but not for the data tier.
        stamp = (_NOW - timedelta(hours=48)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_", points=42)],
            {"r000000000001_": stamp},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "pending"
        old = (_NOW - timedelta(hours=169)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_", points=42)],
            {"r000000000001_": old},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "reclaim_data"
        assert decisions[0].tier == "data"

    def test_non_orphaned_statuses_never_appear(self) -> None:
        surveys = [
            _survey("r000000000001_", status="live"),
            _survey("r000000000002_", status="unknown"),
            _survey("r000000000003_", status="unverifiable"),
        ]
        assert evaluate_reclaim(surveys, {}, now=_NOW, policy=_POLICY) == []

    def test_cycle_cap_defers_and_empties_go_first(self) -> None:
        old = (_NOW - timedelta(hours=1000)).isoformat()
        surveys = [
            _survey("r000000000001_", points=42),
            _survey("r000000000002_"),
            _survey("r000000000003_"),
        ]
        stamps = {s.prefix: old for s in surveys}
        policy = ReclaimPolicy(
            grace_hours=24.0,
            grace_hours_data=168.0,
            max_per_cycle=2,
            archive_retention_days=30.0,
            archive_max_bytes=10_000,
        )
        decisions = evaluate_reclaim(surveys, stamps, now=_NOW, policy=policy)
        by_prefix = {d.prefix: d for d in decisions}
        # The riskless empty tier fills the cap before the data tier.
        assert by_prefix["r000000000002_"].action == "reclaim_empty"
        assert by_prefix["r000000000003_"].action == "reclaim_empty"
        assert by_prefix["r000000000001_"].action == "deferred"
        assert by_prefix["r000000000001_"].reason == "over_cycle_cap"

    def test_garbage_stamp_restarts_the_window(self) -> None:
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")],
            {"r000000000001_": "not-a-timestamp"},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "pending"

    def test_provenance_is_not_a_reclamation_input(self) -> None:
        """Reachability decides a reclaim; what produced the vectors never does.

        Two classifications share the word ``unverifiable`` and this pins them
        apart in both directions, because wiring either one into the other
        breaks something silently.

        Mutation the first assertion catches: gating a reclaim on the namespace
        carrying a stamped model. That reads as caution and is a leak - every
        namespace written before stamping existed would be exempt forever, and
        an orphan's root is already gone, so it can never be rebuilt into a
        stamp.

        Mutation the second catches: admitting a namespace whose root could not
        be confirmed absent because its provenance is known. Full provenance
        says nothing about whether the volume is merely offline.
        """
        aged = (_NOW - timedelta(hours=25)).isoformat()

        unstamped_orphan = _survey("r000000000001_", models={})
        decisions = evaluate_reclaim(
            [unstamped_orphan],
            {"r000000000001_": aged},
            now=_NOW,
            policy=_POLICY,
        )
        assert [d.action for d in decisions] == ["reclaim_empty"]

        stamped_unreachable = _survey(
            "r000000000002_",
            status="unverifiable",
            models={"r000000000002_vault_docs": "acme/dense-v1"},
        )
        assert (
            evaluate_reclaim(
                [stamped_unreachable],
                {"r000000000002_": aged},
                now=_NOW,
                policy=_POLICY,
            )
            == []
        )


class TestEphemeralOrphanWindow:
    """Ephemerality picks the orphan window; point count still picks the tier.

    Every assertion below is pinned to an hour count only one window can
    produce. The two windows are 24 and 168 hours apart in effect, so a stamp
    placed between them is admitted by exactly one of them and the remaining
    hours reported by the other cannot be mistaken for it. Asserting merely
    that something was reclaimed would pass under either window given a stamp
    old enough, which is the whole failure this class exists to detect.
    """

    def test_a_torn_down_sandbox_draws_the_ephemeral_window(self) -> None:
        """A temp-rooted orphan holding points reclaims on the short window.

        25 hours is past the ephemeral window and nowhere near the data one,
        so ``reclaim_data`` here can only have come from the ephemeral
        window. The tier is asserted alongside it because the shorter window
        must not also demote the namespace out of the archived tier: the
        waiting period is the only thing ephemerality is allowed to change.
        """
        prefix = "rbbbbbbbbbbb1_"
        stamp = (_NOW - timedelta(hours=25)).isoformat()

        decisions = evaluate_reclaim(
            [_temp_survey(prefix, points=42, status="orphaned")],
            {prefix: stamp},
            now=_NOW,
            policy=_POLICY,
        )

        assert [d.action for d in decisions] == ["reclaim_data"]
        assert decisions[0].tier == "data"

    def test_the_ephemeral_window_is_a_window_and_not_a_licence(self) -> None:
        """Inside the short window the same namespace is still pending.

        The reported remainder is asserted whole rather than by prefix: one
        hour left is the ephemeral window's arithmetic and only its own. The
        data window would report 145 through the identical message, so a
        prefix match would accept the defect this class is written against.
        """
        prefix = "rbbbbbbbbbbb2_"
        stamp = (_NOW - timedelta(hours=23)).isoformat()

        decisions = evaluate_reclaim(
            [_temp_survey(prefix, points=42, status="orphaned")],
            {prefix: stamp},
            now=_NOW,
            policy=_POLICY,
        )

        assert decisions[0].action == "pending"
        assert decisions[0].reason == "grace_remaining_h=1.0"

    def test_a_non_temp_orphan_still_draws_the_full_data_window(self) -> None:
        """A deleted worktree is not a sandbox and keeps the seven days.

        This is the over-broad-match detector. Were the window selected
        without consulting the root - every orphan drawing the ephemeral
        window - this namespace would be ``reclaim_data`` at 25 hours and the
        first assertion would fail; the 143 remaining hours then pin which
        window actually ran, because no other window in the policy produces
        that number from this stamp.
        """
        prefix = "rbbbbbbbbbbb3_"
        stamp = (_NOW - timedelta(hours=25)).isoformat()

        decisions = evaluate_reclaim(
            [_survey(prefix, points=42)],
            {prefix: stamp},
            now=_NOW,
            policy=_POLICY,
        )

        assert decisions[0].action == "pending"
        assert decisions[0].reason == "grace_remaining_h=143.0"

    def test_the_full_data_window_still_expires(self) -> None:
        """Positive control: the long window is longer, not unreachable."""
        prefix = "rbbbbbbbbbbb4_"
        stamp = (_NOW - timedelta(hours=169)).isoformat()

        decisions = evaluate_reclaim(
            [_survey(prefix, points=42)],
            {prefix: stamp},
            now=_NOW,
            policy=_POLICY,
        )

        assert [d.action for d in decisions] == ["reclaim_data"]


class TestConvergenceDetection:
    """The convergence contract, driven deterministically.

    These pin the behaviour the whole feature rests on: a reclaim figure is
    published only for a merge that was watched from start to finish. The
    real-server integration tests prove reclamation happens; only a scripted
    timeline can prove the *timing* rules, because a live optimizer cannot be
    told to stall.
    """

    @staticmethod
    def _wait(client: object, path: Path, budget_s: float = 60.0):
        from ..storage_reconciliation import await_convergence

        clock = {"t": 0.0}

        def _monotonic() -> float:
            return clock["t"]

        def _sleep(seconds: float) -> None:
            clock["t"] += seconds

        return await_convergence(
            cast("QdrantClient", client),
            "rfeedfacefeed_vault_docs",
            path,
            budget_s=budget_s,
            poll_s=1.0,
            sleep=_sleep,
            monotonic=_monotonic,
        )

    def test_queued_merge_is_not_mistaken_for_a_converged_one(
        self, tmp_path: Path
    ) -> None:
        """A merge waiting on a busy optimizer is perfectly stable too.

        `optimizer_status` has no busy state, so if convergence were judged
        on stability alone, a collection sitting in the optimizer queue -
        unchanged segments, unchanged size - would be measured before it
        ever merged and its untouched footprint published as a reclaim.
        """
        path = tmp_path / "coll"
        # Pending forever: qdrant reports grey ("possible but not triggered").
        client = _ScriptedClient(path, [(8, "grey", 8)])

        assert self._wait(client, path, budget_s=30.0) is None

    def test_mid_merge_inflation_never_returns_early(self, tmp_path: Path) -> None:
        """The measurement must be the settled one, not the peak."""
        path = tmp_path / "coll"
        client = _ScriptedClient(
            path,
            [
                (8, "yellow", 8),  # merge starts
                (9, "yellow", 12),  # inflates past where it began
                (9, "yellow", 12),  # ... and holds there for a while
                (9, "yellow", 12),
                (9, "yellow", 12),
                (9, "yellow", 12),
                (2, "green", 3),  # merge lands
                (2, "green", 3),
                (2, "green", 3),
                (2, "green", 3),
                (2, "green", 3),
            ],
        )

        result = self._wait(client, path)

        assert result is not None
        segments, size = result
        assert segments == 2, "returned a mid-flight segment count"
        assert size is not None
        # 3 blocks * 2 MiB, not the 12-block inflated peak.
        assert size < 8 * 1024 * 1024, "published the inflated mid-merge size"

    def test_never_settling_collection_reports_no_measurement(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(9, "yellow", 12)])

        assert self._wait(client, path, budget_s=30.0) is None

    def test_collection_with_no_work_settles_without_waiting_out_the_budget(
        self, tmp_path: Path
    ) -> None:
        """Green throughout means there was no merge to watch.

        Reporting its unchanged size is honest - it reclaimed nothing - and
        it must not burn the whole budget to say so.
        """
        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(2, "green", 2)])

        result = self._wait(client, path, budget_s=600.0)

        assert result is not None
        assert result[0] == 2
        # Bounded by the start window, not the full convergence budget.
        assert client.samples < 60

    def test_shutdown_event_abandons_the_wait(self, tmp_path: Path) -> None:
        import threading

        from ..storage_reconciliation import await_convergence

        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(9, "yellow", 12)])
        stop = threading.Event()
        stop.set()

        result = await_convergence(
            cast("QdrantClient", client),
            "rfeedfacefeed_vault_docs",
            path,
            budget_s=600.0,
            poll_s=1.0,
            sleep=lambda _: None,
            monotonic=time.monotonic,
            stop=stop,
        )

        assert result is None
        assert client.samples == 0, "sampled despite shutdown"


class TestPlanReconcile:
    """Selection logic for the geometry reconcile pass.

    Pure decision logic, so it is exercised directly: which collections
    count as drifted, how the per-pass cap applies, and what is left over.
    The client-coupled reconcile itself is covered at the integration tier
    against a real server, because only a real optimizer can prove the
    reclamation and the convergence behaviour.
    """

    @staticmethod
    def _entry(
        name: str,
        *,
        target: int,
        segments: int = 8,
        size: int | None = 1000,
    ) -> GeometryEntry:
        return GeometryEntry(
            collection=name,
            segment_target=target,
            segments=segments,
            footprint_bytes=size,
        )

    def test_collection_already_at_target_is_not_drifted(self) -> None:
        entries = [self._entry("at_target", target=SERVER_SEGMENT_NUMBER)]

        selected, remaining = plan_reconcile(entries, cap=10)

        assert selected == []
        assert remaining == 0

    def test_actual_segment_count_does_not_imply_drift(self) -> None:
        """A big collection legitimately grows segments past the target.

        The setting is what drifts, not the outcome: the optimizer is
        supposed to add segments as real data arrives, and reconciling
        such a collection every cycle would be perpetual pointless work.
        """
        entries = [
            self._entry("busy", target=SERVER_SEGMENT_NUMBER, segments=32),
        ]

        selected, _ = plan_reconcile(entries, cap=10)

        assert selected == []

    def test_server_default_zero_target_is_drifted(self) -> None:
        """``0`` means derive-from-CPU-count - the pre-bound geometry."""
        entries = [self._entry("legacy", target=0)]

        selected, remaining = plan_reconcile(entries, cap=10)

        assert [e.collection for e in selected] == ["legacy"]
        assert remaining == 0

    def test_cap_defers_the_remainder(self) -> None:
        entries = [
            self._entry("a", target=0, size=300),
            self._entry("b", target=0, size=200),
            self._entry("c", target=0, size=100),
        ]

        selected, remaining = plan_reconcile(entries, cap=2)

        assert [e.collection for e in selected] == ["a", "b"]
        assert remaining == 1

    def test_largest_footprint_is_reconciled_first(self) -> None:
        """A capped pass should reclaim the most bytes it can."""
        entries = [
            self._entry("small", target=0, size=10),
            self._entry("huge", target=0, size=9_000),
            self._entry("mid", target=0, size=500),
        ]

        selected, _ = plan_reconcile(entries, cap=3)

        assert [e.collection for e in selected] == ["huge", "mid", "small"]

    def test_unmeasured_footprint_sorts_last_without_being_dropped(self) -> None:
        entries = [
            self._entry("unmeasured", target=0, size=None),
            self._entry("measured", target=0, size=5),
        ]

        selected, remaining = plan_reconcile(entries, cap=5)

        assert [e.collection for e in selected] == ["measured", "unmeasured"]
        assert remaining == 0

    def test_zero_cap_selects_nothing_and_defers_everything(self) -> None:
        entries = [self._entry("a", target=0), self._entry("b", target=0)]

        selected, remaining = plan_reconcile(entries, cap=0)

        assert selected == []
        assert remaining == 2


def _read_timeout() -> Exception:
    """Build the object a qdrant REST call really raises when it times out.

    Not a stand-in for one: every server call in the reclaim path goes through
    the client's own send path, which catches whatever ``httpx`` raised and
    re-raises it wrapped in ``ResponseHandlingException``. That wrapper is a
    plain ``Exception``, which is precisely why guards naming only ``OSError``
    and ``RuntimeError`` never saw it.
    """
    import httpx
    from qdrant_client.http.exceptions import ResponseHandlingException

    return ResponseHandlingException(httpx.ReadTimeout("timed out"))


def _server_refusal(status_code: int = 503) -> Exception:
    """Build the object a qdrant REST call really raises on a non-2xx status.

    The other half of the class, and the half a guard is likeliest to miss.
    The client wraps only what ``httpx`` raised; a response that ARRIVED and
    carried an error status never reaches that wrapper, and is reported as
    ``UnexpectedResponse`` instead - a plain ``Exception`` again, and not a
    ``ResponseHandlingException``. Same call, same send path, same
    consequence for a loop that is already destroying.
    """
    from httpx import Headers
    from qdrant_client.http.exceptions import UnexpectedResponse

    return UnexpectedResponse(
        status_code=status_code,
        reason_phrase="Service Unavailable",
        content=b'{"status":{"error":"service unavailable"}}',
        headers=Headers(),
    )


@dataclass(frozen=True)
class _TransportFaults:
    """Which of a cycle client's server calls fail, and with what.

    One value rather than a keyword per call, so a test names only the call it
    is faulting and every other call is visibly untouched.

    ``listing_error`` and ``delete_error`` default to a transport timeout.
    Naming something else is how a test asks what a guard really covers: a
    server that answered with an error must be absorbed exactly as a server
    that never answered is, and a failure outside the class entirely has to
    keep escaping rather than be reported as a slow server.
    """

    snapshots: frozenset[str] = frozenset()
    recounts: frozenset[str] = frozenset()
    deletes: frozenset[str] = frozenset()
    delete_error: Exception | None = None
    listing_on_call: int | None = None
    listing_error: Exception | None = None


#: No fault at all - the stand-in behaves as the plain cycle client.
_NO_FAULTS = _TransportFaults()


class _TimeoutClient(_CycleClient):
    """A cycle client whose named collections time out on one call each.

    Fault injection at the transport boundary only - the one condition a live
    server cannot be asked to reproduce on demand. Enumeration, counting,
    snapshot files on disk and deletes stay the real ``_CycleClient``
    behaviour, so a namespace that does not time out is reclaimed exactly as
    it would be without this subclass, and the surviving candidate is
    therefore evidence about the cycle rather than about the stand-in.
    """

    def __init__(
        self,
        counts: dict[str, int],
        *,
        snapshots_dir: Path | None = None,
        faults: _TransportFaults = _NO_FAULTS,
    ) -> None:
        super().__init__(counts, snapshots_dir=snapshots_dir)
        self._faults = faults
        self._counted: dict[str, int] = {}
        self.listings = 0
        #: What the cycle had destroyed and archived at the moment the faulted
        #: listing raised. Read by the generation-pass test to place that
        #: listing before any orphan work, which is the ordering the whole
        #: claim rests on.
        self.state_at_listing_fault: tuple[tuple[str, ...], tuple[str, ...]] | None = (
            None
        )

    def get_collections(self) -> object:
        self.listings += 1
        if self.listings == self._faults.listing_on_call:
            self.state_at_listing_fault = (
                tuple(self.deleted),
                tuple(self.snapshotted),
            )
            raise self._faults.listing_error or _read_timeout()
        return super().get_collections()

    def count(self, *, collection_name: str) -> object:
        seen = self._counted.get(collection_name, 0) + 1
        self._counted[collection_name] = seen
        # The survey counts each collection once and the pre-drop re-count is
        # the second visit, so only the second is failed. Failing the survey's
        # count instead would degrade the namespace to zero points long before
        # the gate under test was ever consulted.
        if collection_name in self._faults.recounts and seen > 1:
            raise _read_timeout()
        return super().count(collection_name=collection_name)

    def create_snapshot(self, *, collection_name: str, wait: bool = True) -> object:
        if collection_name in self._faults.snapshots:
            # Recorded before raising: the attempt is what the ordering
            # assertions read, and a snapshot that timed out was still asked
            # for.
            self.snapshotted.append(collection_name)
            raise _read_timeout()
        return super().create_snapshot(collection_name=collection_name, wait=wait)

    def delete_collection(self, *, collection_name: str) -> None:
        # Nothing is recorded for a delete that raised: unlike a snapshot,
        # whose attempt is the interesting event, a delete either removed the
        # collection or it did not, and ``deleted`` is what the partial-drop
        # assertions read as the destruction that really happened.
        if collection_name in self._faults.deletes:
            raise self._faults.delete_error or _read_timeout()
        super().delete_collection(collection_name=collection_name)


def _two_orphans(tmp_path: Path) -> tuple[str, str]:
    """Return two aged data-tier orphans in the order the cycle applies them.

    Same-tier orphans are ordered by prefix, so sorting here names which
    namespace the cycle reaches first. Continuation is only a meaningful
    claim about the one queued behind the failure, never about one already
    processed before it.
    """
    first, second = sorted(
        (
            _orphaned_namespace(tmp_path, now=_NOW, name="vanished-a"),
            _orphaned_namespace(tmp_path, now=_NOW, name="vanished-b"),
        )
    )
    return first, second


class TestTransportTimeoutIsolation:
    """One slow server call defers one namespace, never the whole cycle.

    The reclaim gates promise a per-namespace skip carrying a reported reason.
    A read timeout arrives as a plain ``Exception`` rather than an ``OSError``,
    so guards naming only the builtin types propagated it out of the cycle
    entirely: the tick died reporting a timeout and reclaimed nothing,
    including from every candidate it had not reached yet.
    """

    def test_a_snapshot_timeout_fails_one_namespace_and_the_cycle_goes_on(
        self, tmp_path: Path
    ) -> None:
        """A timed-out archive marks that namespace failed; the next still runs.

        Mutation it catches: narrowing the archive guard back to
        ``(OSError, RuntimeError)``, which lets the wrapped read timeout escape
        ``_apply_reclaim`` and unwind ``run_maintenance_cycle`` before the
        second candidate is reached. The reason is asserted whole rather than
        by prefix because a torn archive reports ``archive_failed:`` too, and a
        prefix match would pass on whichever of the two branches fired.
        """
        first, second = _two_orphans(tmp_path)
        stalled, healthy = _collection_of(first), _collection_of(second)
        client = _TimeoutClient(
            {stalled: 10, healthy: 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(snapshots=frozenset({stalled})),
        )

        result = _run_cycle(client, tmp_path)

        failed, survivor = _outcome_for(result, first), _outcome_for(result, second)
        assert failed.action == "failed"
        assert failed.reason == "archive_failed: timed out"
        # Sequence, not mere survival: the failing namespace is reached first,
        # so the second one's snapshot and delete are what prove the cycle
        # carried on past the failure instead of never meeting it.
        assert survivor.action == "archived_removed"
        assert client.snapshotted == [stalled, healthy]
        assert client.deleted == [healthy]

    def test_a_recount_timeout_defers_one_namespace_and_the_cycle_goes_on(
        self, tmp_path: Path
    ) -> None:
        """A timed-out re-count is unverifiable, never zero, and never fatal.

        Mutation it catches: narrowing the ``_prefix_points`` guard back to
        ``(OSError, RuntimeError)``, which lets the wrapped read timeout escape
        the pre-drop gate and abort the cycle. ``points_unverifiable`` is
        asserted exactly because it is the only reason meaning the count could
        not be established - the movement branches report their own strings,
        and matching loosely would accept a namespace deferred for having been
        counted successfully at a different number.
        """
        first, second = _two_orphans(tmp_path)
        stalled, healthy = _collection_of(first), _collection_of(second)
        client = _TimeoutClient(
            {stalled: 10, healthy: 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(recounts=frozenset({stalled})),
        )

        result = _run_cycle(client, tmp_path)

        held, survivor = _outcome_for(result, first), _outcome_for(result, second)
        assert held.action == "deferred"
        assert held.reason == "points_unverifiable"
        assert survivor.action == "archived_removed"
        # The gate precedes the archive, so the deferred namespace is never
        # snapshotted at all; the entry that IS here belongs to the candidate
        # behind it, which is the continuation this test exists for.
        assert client.snapshotted == [healthy]
        assert client.deleted == [healthy]

    def test_a_drop_timeout_records_the_partial_destruction_and_the_cycle_goes_on(
        self, tmp_path: Path
    ) -> None:
        """A timeout part-way through a drop is reported, not raised away.

        The severe one. The drop is a per-collection loop, so a server that
        stops answering in the middle of it has ALREADY destroyed part of the
        namespace. Before the guard was widened the wrapped read timeout
        escaped ``delete_prefix``, escaped ``_apply_reclaim`` and unwound the
        tick, leaving a half-deleted namespace with its manifest entry intact
        and no outcome recorded anywhere - destruction with no record of it.

        The stalled namespace is given two collections so the partial state is
        observable at all: with one, a failed drop removes nothing and the
        interesting case never arises. ``codebase_docs`` sorts before
        ``vault_docs``, so the drop loop provably destroys the first before
        the second raises.

        Three mutations, each run alone against this test.

        Narrowing the drop guard in ``delete_prefix`` back to
        ``(OSError, RuntimeError)`` fails
        ``assert failed.reason == "delete_failed after 1/2: timed out"``,
        observed reporting ``drop_failed: timed out``. The apply path's own
        guard stops the escape, but it stands outside the loop and so knows
        nothing about what the loop had already destroyed - the namespace is
        recorded as failed while the fact that half of it is gone is not
        recorded at all, which is the whole of what makes a partial drop
        worse than a missed reclaim.

        Swallowing the failure broadly instead - continuing the loop past it,
        as any handler that merely stops the exception would - fails
        ``assert failed.action == "failed"``, observed reporting
        ``archived_removed``: the namespace is reported reclaimed while half
        of it still exists and its manifest entry has been forgotten.

        Removing both guards, the state before either of them existed, does
        not land on an assertion at all: the wrapped timeout escapes
        ``run_maintenance_cycle`` and the test errors with
        ``ResponseHandlingException: timed out``. That is the production
        failure being closed rather than a proof about this test, which is
        why the two mutations above are the ones it is trusted on.
        """
        first, second = _two_orphans(tmp_path)
        stalled_code = first + CODE_COLLECTION
        stalled_vault = _collection_of(first)
        healthy = _collection_of(second)
        client = _TimeoutClient(
            {stalled_code: 5, stalled_vault: 5, healthy: 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(deletes=frozenset({stalled_vault})),
        )

        result = _run_cycle(client, tmp_path)

        failed, survivor = _outcome_for(result, first), _outcome_for(result, second)
        assert failed.action == "failed"
        # Asserted whole. The counts are the whole point: an operator reading
        # this has to learn that one of the two collections is gone, and a
        # reason that said only "timed out" would read as a namespace nothing
        # happened to.
        assert failed.reason == "delete_failed after 1/2: timed out"
        # The destruction that really happened, and the continuation past it.
        assert client.deleted == [stalled_code, healthy]
        assert survivor.action == "archived_removed"

    def test_a_generation_listing_timeout_still_lets_the_orphan_pass_run(
        self, tmp_path: Path
    ) -> None:
        """The pass that runs first cannot suppress the pass that runs second.

        ``run_maintenance_cycle`` runs the superseded-generation pass before
        the orphan apply loop, and both reach the same server. An escape from
        the generation pass therefore aborted the tick before a single orphan
        had been considered - the reclamation the cycle exists to do,
        suppressed by a pass that only clears residue.

        The faulted call is the cycle's SECOND collection listing. The first
        belongs to the survey, nothing between the survey and the apply loop
        lists collections except the generation pass, and the state captured
        at fault time pins it: no orphan had been archived or dropped yet.

        The second act is what stops this from being a "nothing raised" test.
        The guard is deliberately narrow, so a failure outside the transport
        class must still escape the cycle; asserting that a ``TypeError``
        does is what distinguishes a guard placed on the listing from a
        blanket handler wrapped around the pass, which would absorb both and
        satisfy every assertion in the first act.

        Three mutations, each run alone against this test.

        Removing the listing guard entirely, the state before it existed,
        does not land on an assertion: the wrapped timeout escapes
        ``run_maintenance_cycle`` and the test errors with
        ``ResponseHandlingException: timed out``. That is the production
        failure being closed rather than a proof about this test.

        Moving ``_reclaim_generations_for_cycle`` to after the orphan apply
        loop fails ``assert outcome.action == "archived_removed"``, observed
        reporting ``deferred``: the second listing then belongs to the
        pre-drop re-count, which holds the namespace as unverifiable. The
        fault-time state assertion survives that move - the re-count also
        precedes every delete - so it pins the fault ahead of any destruction
        rather than to the generation pass alone, and the outcome assertion is
        what carries the ordering claim.

        Swallowing broadly instead - widening that guard to ``Exception`` -
        fails the second act's ``pytest.raises(TypeError)`` with DID NOT
        RAISE, which is the only assertion here a blanket handler cannot
        satisfy.
        """
        orphan = _orphaned_namespace(tmp_path, now=_NOW, name="vanished-a")
        collection = _collection_of(orphan)
        client = _TimeoutClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(listing_on_call=2),
        )

        result = _run_cycle(client, tmp_path)

        # The fault landed after the survey and before any orphan work, which
        # is where and only where the generation pass runs.
        assert client.state_at_listing_fault == ((), ())
        assert result.surveys, "the survey's own listing must have succeeded"
        assert result.generations == []
        # The consequence the finding names: the orphan pass ran anyway.
        outcome = _outcome_for(result, orphan)
        assert outcome.action == "archived_removed"
        assert client.deleted == [collection]

        # Same fault site, a failure the guard does not name. A cycle that
        # absorbed this would be reporting a programming error as a namespace
        # the server was too slow to reach.
        second = _orphaned_namespace(tmp_path, now=_NOW, name="vanished-b")
        strict = _TimeoutClient(
            {_collection_of(second): 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(
                listing_on_call=2,
                listing_error=TypeError("not a transport failure"),
            ),
        )

        with pytest.raises(TypeError):
            _run_cycle(strict, tmp_path)


class TestServerRefusalIsolation:
    """A server that answers with an error is the same failure as one that does not.

    The transport class was first widened around the wrapper the client uses
    for what never reached the server: a refused connection, a read timeout, a
    dropped socket. A response that ARRIVES carrying 500 or 503 does not go
    through that wrapper at all - it is reported as ``UnexpectedResponse``,
    which descends from neither the builtins nor that wrapper - so the same
    hole reopened one type over, on the same calls, with the same
    consequence.

    The drop loop is where that consequence is severe, and it is the
    ambiguous side of the boundary: unlike a ``TypeError``, a non-2xx status
    is a statement by the server rather than a mistake by this code, so
    nothing about the guard's narrowness argues for letting it escape.
    """

    def test_a_refused_drop_records_the_partial_destruction_and_the_cycle_goes_on(
        self, tmp_path: Path
    ) -> None:
        """A 503 part-way through a drop is reported, not raised away.

        The stalled namespace is given two collections so the partial state is
        observable at all: with one, a failed drop removes nothing and the
        interesting case never arises. ``codebase_docs`` sorts before
        ``vault_docs``, so the drop loop provably destroys the first before
        the second is refused.

        The reason is split rather than matched whole. Everything before the
        separator is this codebase's own claim and is asserted exactly,
        because the counts are the point: an operator has to learn that one of
        the two collections is gone. Everything after it is the client's
        rendering of its own exception, so only the status line it documents
        is asserted - copying the raw body bytes into an expected value would
        pin the client's formatting rather than this branch.

        Three mutations, each run alone against this test.

        Narrowing the drop guard in ``delete_prefix`` back to the timeout
        wrapper alone fails ``assert head == "delete_failed after 1/2"``,
        observed reporting ``drop_failed``. The apply path's own guard stops
        the escape, but it stands outside the loop and so knows nothing about
        what the loop had already destroyed - the namespace is recorded as
        failed while the fact that half of it is gone is not recorded at all,
        which is the whole of what makes a partial drop worse than a missed
        reclaim.

        Narrowing BOTH guards the same way does not land on an assertion: the
        refusal escapes ``run_maintenance_cycle`` and the test errors with
        ``UnexpectedResponse: 503``. That is the production failure being
        closed rather than a proof about this test, which is why the two
        mutations that do land are the ones it is trusted on.

        Swallowing broadly instead - continuing the loop past the refusal, as
        any handler that merely stops the exception would - fails
        ``assert failed.action == "failed"``, observed reporting
        ``archived_removed``: the namespace is reported reclaimed while half
        of it still exists and its manifest entry has been forgotten.

        Dropping the destroyed names on the way to the outcome, which is what
        an outcome carrying only a reason string does, fails
        ``assert failed.removed_collections == (stalled_code,)`` with an empty
        tuple.
        """
        first, second = _two_orphans(tmp_path)
        stalled_code = first + CODE_COLLECTION
        stalled_vault = _collection_of(first)
        healthy = _collection_of(second)
        client = _TimeoutClient(
            {stalled_code: 5, stalled_vault: 5, healthy: 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(
                deletes=frozenset({stalled_vault}),
                delete_error=_server_refusal(),
            ),
        )

        result = _run_cycle(client, tmp_path)

        failed, survivor = _outcome_for(result, first), _outcome_for(result, second)
        assert failed.action == "failed"
        assert failed.reason is not None
        head, separator, detail = failed.reason.partition(": ")
        assert separator, failed.reason
        assert head == "delete_failed after 1/2"
        assert detail.startswith("Unexpected Response: 503 (Service Unavailable)")
        # Which half is gone, not only how many. An operator who has to go and
        # finish this by hand cannot act on a count.
        assert failed.removed_collections == (stalled_code,)
        # The destruction that really happened, and the continuation past it.
        assert client.deleted == [stalled_code, healthy]
        assert survivor.action == "archived_removed"

    def test_a_programming_error_on_the_same_drop_still_escapes(
        self, tmp_path: Path
    ) -> None:
        """The boundary is still a boundary at its unambiguous side.

        Same fault site as the test above, a failure the class does not name.
        This is what stops the widening from being a blanket handler: a guard
        that absorbed this would be reporting a mistake in this code as a
        namespace the server refused, and would satisfy every assertion the
        first test makes.

        Mutation it catches: widening either drop guard to ``Exception``.
        Observed this fail with DID NOT RAISE, the cycle completing and
        reporting the namespace as merely failed.
        """
        orphan = _orphaned_namespace(tmp_path, now=_NOW, name="vanished-a")
        collection = _collection_of(orphan)
        client = _TimeoutClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
            faults=_TransportFaults(
                deletes=frozenset({collection}),
                delete_error=TypeError("not a transport failure"),
            ),
        )

        with pytest.raises(TypeError):
            _run_cycle(client, tmp_path)


@pytest.mark.usefixtures("isolated_status_dir")
class TestPartialDropNarrowsTheRecord:
    """The entry a partial drop leaves standing stops naming what is gone.

    The entry itself has to survive: part of the namespace does, and forgetting
    it would leave the survivors unattributable and so unreclaimable. Its
    inventory is a separate claim. ``collections`` is read as the record of
    which kinds a namespace holds, and the donor search asks exactly that
    question of it, so an entry left whole keeps offering a destroyed
    collection as a source of vectors nobody can read. The identity map is the
    same claim about provenance.
    """

    def test_a_partial_drop_stops_the_entry_naming_what_it_destroyed(
        self, tmp_path: Path
    ) -> None:
        """The destroyed name leaves the inventory; the survivor stays.

        Both halves are asserted, and the second is what makes the first mean
        anything: an entry narrowed to nothing, or forgotten outright, would
        satisfy a test that only checked the destroyed name was gone while
        making the surviving collections unattributable.

        Two mutations, each run alone against this test.

        Removing the narrowing - the state where the entry outlives what it
        claims - fails ``assert code not in after.collections``, observed with
        the entry still naming a collection the drop had destroyed.

        Narrowing to the empty tuple instead, as a caller that passed the
        targets rather than what it actually removed would, fails
        ``assert vault in after.collections``: the surviving half of the
        namespace loses the record that attributes it.
        """
        from ..storage_manifest import (
            load_manifest,
            record_collection_identity,
            record_root,
        )
        from ..storage_survey_ops import delete_prefix
        from ..store_schema import VAULT_COLLECTION

        root = tmp_path / "namespace"
        root.mkdir()
        prefix = record_root(root, backend="server").prefix
        code, vault = prefix + CODE_COLLECTION, prefix + VAULT_COLLECTION
        for collection in (code, vault):
            record_collection_identity(
                root, backend="server", collection=collection, identity=_identity()
            )
        client = _TimeoutClient(
            {code: 5, vault: 7},
            faults=_TransportFaults(deletes=frozenset({vault})),
        )

        result = delete_prefix(cast("QdrantClient", client), prefix, dry_run=False)

        assert result.status == "failed"
        assert result.collections == [code]
        after = load_manifest()[prefix]
        assert code not in after.collections
        assert vault in after.collections
        assert code not in after.collection_identity
        assert vault in after.collection_identity
