"""Guard tests for judging the on-disk store format before opening it.

A server binary upgrade can leave a storage directory the new binary cannot
read. Upstream guarantees compatibility only between consecutive minor
versions, forbids skipping a minor, and does not support downgrading at all.
Nothing on the spawn path used to compare versions, and the collection-load
failure parser keys on collection names appearing beside a failure marker -
exactly the shape an incompatible-format abort produces - so such an abort read
as a run of independently corrupt collections and each was moved aside in turn.

These tests defend the gate that refuses that start instead, and the surfacing
that stops quarantined data from sitting behind a ready status.

Every test here is a guard, so each has been observed failing for its intended
reason; the mutation each one catches is named in its own docstring.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from ..cli._status_labels import (
    QUARANTINE_FAMILY,
    STORE_FORMAT_FAMILY,
    VECTOR_SERVICE_FAMILY,
    degradation_findings,
)
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..qdrant_runtime._constants import QdrantRuntimeState
from ..qdrant_runtime._resolve import QdrantIdentity
from ..qdrant_runtime._store_format import (
    judge_store_format,
    list_quarantined_collections,
    read_store_format,
    store_format_path,
    write_store_format,
)
from ..qdrant_runtime._supervise import (
    QdrantSupervisor,
    _corrupt_collection_from_output,  # pyright: ignore[reportPrivateUsage]
    start_supervised_from_config,
)
from ..server._lifespan import (
    _service_health_status,  # pyright: ignore[reportPrivateUsage]
)
from ..store_schema import CONFORMING, NONCONFORMING, UNVERIFIABLE
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

    from ..service import ServiceHealth

pytestmark = [pytest.mark.unit]


def _make_collection(storage: Path, name: str) -> Path:
    """Create a non-empty collection directory under ``collections/``."""
    col = storage / "collections" / name
    col.mkdir(parents=True, exist_ok=True)
    (col / "segment.bin").write_bytes(b"data")
    return col


def _identity_for(storage: Path, version: str) -> QdrantIdentity:
    """An identity sidecar record naming *storage* and *version*."""
    return QdrantIdentity(
        storage_path=str(storage),
        version=version,
        owner_pid=1234,
        http_port=6333,
    )


class TestStampRoundTrip:
    """The stamp lives inside the storage dir and survives a round trip."""

    def test_stamp_is_written_inside_the_storage_dir(self, tmp_path: Path) -> None:
        """The stamp must travel with the data, not sit beside it.

        Mutation it catches: resolving the stamp path as a sibling of the
        storage dir (as the identity sidecar is). A sibling does not survive
        copying, archiving, or restoring the store, which is exactly when the
        format provenance matters most.
        """
        written = write_store_format(tmp_path, "1.18.2")

        assert written.parent == tmp_path
        assert written == store_format_path(tmp_path)

    def test_written_version_reads_back(self, tmp_path: Path) -> None:
        write_store_format(tmp_path, "1.18.2")
        stamp = read_store_format(tmp_path)
        assert stamp is not None
        assert stamp.version == "1.18.2"

    def test_absent_stamp_reads_as_no_record(self, tmp_path: Path) -> None:
        assert read_store_format(tmp_path) is None

    def test_malformed_stamp_reads_as_no_record(self, tmp_path: Path) -> None:
        """A corrupt forensic file must not fail a start.

        Mutation it catches: letting the JSON decode error escape. The stamp is
        an advisory record; raising here would turn a damaged sidecar into an
        unstartable service.
        """
        store_format_path(tmp_path).write_text("{not json", encoding="utf-8")
        assert read_store_format(tmp_path) is None

    def test_stamp_without_a_version_reads_as_no_record(self, tmp_path: Path) -> None:
        store_format_path(tmp_path).write_text(json.dumps({}), encoding="utf-8")
        assert read_store_format(tmp_path) is None


class TestJudgementPermits:
    """Starts that upstream supports, and that must not be refused."""

    def test_empty_store_is_permitted(self, tmp_path: Path) -> None:
        """A first-ever start has nothing to be incompatible with.

        Mutation it catches: dropping the empty-store branch, which would make
        every fresh install unverifiable and disable the automatic
        single-collection recovery from its very first start.
        """
        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == CONFORMING
        assert verdict.provenance == "empty"
        assert verdict.may_spawn
        assert verdict.may_auto_quarantine

    def test_same_version_is_permitted(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.18.2")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == CONFORMING
        assert verdict.provenance == "stamp"
        assert verdict.may_auto_quarantine

    def test_patch_upgrade_is_permitted(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.18.1")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == CONFORMING

    def test_single_minor_upgrade_is_permitted(self, tmp_path: Path) -> None:
        """Upstream guarantees exactly this step, so it must not be refused.

        Mutation it catches: refusing on any minor difference. That would
        refuse the one upgrade path upstream actually supports and leave no way
        to move the store forward at all.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.17.4")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == CONFORMING
        assert verdict.may_spawn


class TestJudgementRefuses:
    """Starts that would strand data, and must be refused before spawning."""

    def test_downgrade_is_refused(self, tmp_path: Path) -> None:
        """A store migrated forward cannot be read by an older binary.

        Mutation it catches: dropping the ``new < old`` branch. Without it an
        operator who pins the version back starts a binary that aborts on the
        migrated store, and the load-failure parser moves the named
        collections aside one at a time.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.18.2")

        verdict = judge_store_format(tmp_path, spawning_version="1.17.4")

        assert verdict.verdict == NONCONFORMING
        assert not verdict.may_spawn
        assert not verdict.may_auto_quarantine
        assert "downgrading is not supported" in verdict.reason

    def test_skipped_minor_is_refused(self, tmp_path: Path) -> None:
        """Skipping a minor skips its storage migration.

        Mutation it catches: relaxing the ``> 1`` minor-gap test to allow any
        upgrade. Upstream runs migrations one minor at a time, so a skipped
        minor leaves the on-disk format unmigrated and the store unreadable.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.16.3")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == NONCONFORMING
        assert not verdict.may_spawn
        assert "skips at least one minor version" in verdict.reason

    def test_major_change_is_refused(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.18.2")

        verdict = judge_store_format(tmp_path, spawning_version="2.0.0")

        assert verdict.verdict == NONCONFORMING
        assert "major version change" in verdict.reason

    def test_refusal_names_the_stored_version(self, tmp_path: Path) -> None:
        """The operator needs to know which version to reinstall."""
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.16.3")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.stored_version == "1.16.3"


class TestJudgementAbstains:
    """A store whose provenance is unknown is neither passed nor failed."""

    def test_unstamped_store_is_unverifiable_but_may_open(self, tmp_path: Path) -> None:
        """An unknown store must open, yet must not be quarantined into.

        Mutation it catches: returning ``CONFORMING`` for a store with no
        provenance. That re-enables blaming a load failure on one collection
        when the failure is equally consistent with a whole-store
        incompatibility - the silent stranding this gate exists to prevent.
        Refusing instead would brick every host whose store predates stamping,
        which is why the verdict permits the open and only withholds the
        automatic quarantine.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == UNVERIFIABLE
        assert verdict.may_spawn
        assert not verdict.may_auto_quarantine

    def test_unparseable_stored_version_is_unverifiable(self, tmp_path: Path) -> None:
        """An unorderable version must not be guessed into a comparison.

        Mutation it catches: falling through to the ordering comparison with an
        unparsed version, which would compare against a default and invent a
        verdict from nothing.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "nightly")

        verdict = judge_store_format(tmp_path, spawning_version="1.18.2")

        assert verdict.verdict == UNVERIFIABLE
        assert verdict.may_spawn
        assert not verdict.may_auto_quarantine


class TestIdentityFallbackProvenance:
    """The sidecar answers for a store written before stamping existed."""

    def test_identity_supplies_provenance_for_an_unstamped_store(
        self, tmp_path: Path
    ) -> None:
        """The first start after an upgrade is the one that most needs the gate.

        Mutation it catches: dropping the identity fallback. Without it every
        store predating the stamp is unverifiable on exactly the start where a
        downgrade or a skipped minor would strand it, so the refusal never
        fires when it matters.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")

        verdict = judge_store_format(
            tmp_path,
            spawning_version="1.16.3",
            identity=_identity_for(tmp_path, "1.18.2"),
        )

        assert verdict.verdict == NONCONFORMING
        assert verdict.provenance == "identity"
        assert verdict.stored_version == "1.18.2"

    def test_identity_for_a_different_store_is_ignored(self, tmp_path: Path) -> None:
        """The sidecar is machine-global and may describe another directory.

        Mutation it catches: using the sidecar version without comparing its
        recorded storage path. A record for an unrelated directory would then
        decide this one's fate, refusing a start over a store it never
        described.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")
        other = tmp_path / "elsewhere"

        verdict = judge_store_format(
            tmp_path,
            spawning_version="1.16.3",
            identity=_identity_for(other, "1.18.2"),
        )

        assert verdict.verdict == UNVERIFIABLE
        assert verdict.provenance == ""

    def test_stamp_wins_over_the_identity_sidecar(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        write_store_format(tmp_path, "1.18.2")

        verdict = judge_store_format(
            tmp_path,
            spawning_version="1.18.2",
            identity=_identity_for(tmp_path, "1.16.3"),
        )

        assert verdict.verdict == CONFORMING
        assert verdict.provenance == "stamp"


class TestMisdiagnosisIsReal:
    """The parser really does finger a collection on an incompatibility abort."""

    def test_version_incompatibility_abort_names_a_collection(
        self, tmp_path: Path
    ) -> None:
        """Why the gate has to exist upstream of the quarantine heuristic.

        The parser cannot distinguish a whole-store format incompatibility from
        one corrupt collection: an abort that names the collection it was
        loading when the format check failed matches on the same line as a
        failure marker, so the collection is identified as the culprit and
        moved aside. This test pins that behaviour so the gate above it is not
        mistaken for redundant.
        """
        _make_collection(tmp_path, "r0abc_vault_docs")
        tail = (
            "thread 'main' panicked at collection_manager/src/segments.rs:412:\n"
            "Failed to load segment for collection r0abc_vault_docs: "
            "unsupported storage version 12, this build supports up to 10\n"
        )

        assert _corrupt_collection_from_output(tail, tmp_path) == "r0abc_vault_docs"


class TestSpawnGateRefusesBeforeSpawning:
    """The refusal happens on the spawn path, and touches nothing."""

    def test_incompatible_store_refuses_the_start_and_moves_nothing(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        """The whole point: an incompatible upgrade must not quarantine its way in.

        Mutation it catches: dropping the ``may_spawn`` refusal from
        ``start_supervised_from_config``. Without it the start proceeds, the
        binary aborts on the incompatible store, and the retry loop moves up to
        three named collections out of the active set - the silent
        data-availability loss this gate removes. Asserts the collection is
        still in the active set and no quarantine directory was created, so a
        refusal that fired only after touching the store would still fail.
        """
        _ = isolated_singleton_dirs
        storage = tmp_path / "qdrant" / "storage"
        storage.mkdir(parents=True, exist_ok=True)
        _make_collection(storage, "r0abc_vault_docs")
        write_store_format(storage, "1.16.3")
        binary = tmp_path / "qdrant-stub"
        binary.write_text("", encoding="utf-8")

        with managed_env(
            **{
                EnvVar.QDRANT_STORAGE_DIR.value: str(storage),
                EnvVar.QDRANT_BINARY.value: str(binary),
                EnvVar.QDRANT_PORT.value: str(free_loopback_port()),
            }
        ):
            reset_config()
            with pytest.raises(RuntimeError, match="skips at least one minor version"):
                start_supervised_from_config()
        reset_config()

        assert (storage / "collections" / "r0abc_vault_docs").is_dir()
        assert not (storage / "quarantine").exists()


class TestQuarantineReachesHealth:
    """Quarantined data must never sit behind a ready status."""

    @staticmethod
    def _health(**overrides: object) -> ServiceHealth:
        base: dict[str, object] = {
            "model_loaded": True,
            "reranker_loaded": True,
            "cuda": True,
            "project_count": 1,
            "projects": ["/proj"],
            "nonconforming": [],
        }
        base.update(overrides)
        return cast("ServiceHealth", base)

    @staticmethod
    def _server_qdrant(quarantined: list[str]) -> QdrantRuntimeState:
        return QdrantRuntimeState(
            mode="server",
            alive=True,
            port=6333,
            extra={"quarantined": quarantined},
        )

    def test_clean_store_stays_ready(self) -> None:
        status, reasons = _service_health_status(
            self._health(), self._server_qdrant([])
        )
        assert status == "ready"
        assert reasons == []

    def test_quarantined_collection_degrades_the_service(self) -> None:
        """The whole point: a live server over quarantined data is not healthy.

        Mutation it catches: dropping the quarantine branch from
        ``_service_health_status``. Without it the daemon reports ready while
        the affected roots return empty or partial results, with only a log
        line to say why - the silent failure behind a green light.
        """
        status, reasons = _service_health_status(
            self._health(),
            self._server_qdrant(["r0abc_vault_docs.20260725T101500Z"]),
        )

        assert status == "degraded"
        assert any("quarantined" in reason for reason in reasons)

    def test_quarantine_reason_is_paired_with_its_remediation(self) -> None:
        """A cause with no next move leaves the operator stuck.

        Mutation it catches: removing the quarantine entry from the degraded
        family registry. The cause would still be reported by the unpaired
        sweep, so this asserts the family and the command specifically - the
        parts that are actually lost.
        """
        status, reasons = _service_health_status(
            self._health(),
            self._server_qdrant(["r0abc_vault_docs.20260725T101500Z"]),
        )
        payload: dict[str, object] = {
            "status": status,
            "degraded_reasons": reasons,
            "qdrant": {
                "alive": True,
                "quarantined": ["r0abc_vault_docs.20260725T101500Z"],
            },
        }

        findings = degradation_findings(payload)
        quarantine = [f for f in findings if f.family == QUARANTINE_FAMILY]

        assert len(quarantine) == 1
        assert quarantine[0].command == "vaultspec-rag server qdrant quarantine"

    def test_a_dead_server_and_a_quarantine_are_reported_separately(self) -> None:
        """Coexistence coverage, not a guard: two problems, two findings.

        The quarantine reason names the vector store, so it is eligible for the
        broader ``vector`` stem. Claiming pops the stem and the vector reason is
        emitted first, so the two cannot compete for one entry today - this
        pins that outcome rather than the mechanism producing it, and no single
        mutation distinguishes it from the pairing test above.
        """
        qdrant = QdrantRuntimeState(
            mode="server",
            alive=False,
            port=6333,
            extra={"quarantined": ["r0abc_vault_docs.20260725T101500Z"]},
        )
        status, reasons = _service_health_status(self._health(), qdrant)
        payload: dict[str, object] = {
            "status": status,
            "degraded_reasons": reasons,
            "qdrant": {
                "alive": False,
                "quarantined": ["r0abc_vault_docs.20260725T101500Z"],
            },
        }

        families = {f.family for f in degradation_findings(payload)}

        assert QUARANTINE_FAMILY in families
        assert VECTOR_SERVICE_FAMILY in families


class TestRuntimeStateCarriesQuarantine:
    """The supervisor is the one producer of the quarantine signal."""

    def test_state_reports_the_quarantine_listing(self, tmp_path: Path) -> None:
        """The signal has to reach health from the supervisor, not be recomputed.

        Mutation it catches: dropping ``extra`` from ``state()``. The health
        author would then see no quarantine on any surface, and the degradation
        above could never fire in production however well it tests in isolation.
        """
        storage = tmp_path / "storage"
        (storage / "quarantine" / "r0abc_vault_docs.20260725T101500Z").mkdir(
            parents=True
        )
        supervisor = QdrantSupervisor(
            tmp_path / "qdrant-stub",
            http_port=6333,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
        )

        state = supervisor.state()

        assert state.extra.get("quarantined") == ["r0abc_vault_docs.20260725T101500Z"]
        assert state.to_dict().get("quarantined") == [
            "r0abc_vault_docs.20260725T101500Z"
        ]

    def test_listing_is_empty_without_a_quarantine_dir(self, tmp_path: Path) -> None:
        assert list_quarantined_collections(tmp_path) == []

    def test_listing_names_every_entry(self, tmp_path: Path) -> None:
        for name in ("b_vault_docs.20260725T101500Z", "a_vault_code.20260725T101500Z"):
            (tmp_path / "quarantine" / name).mkdir(parents=True)

        assert list_quarantined_collections(tmp_path) == [
            "a_vault_code.20260725T101500Z",
            "b_vault_docs.20260725T101500Z",
        ]


class TestPermittedUpgradeIsRecordedAsAMigration:
    """A permitted upgrade is still a one-way door, and says so."""

    def test_single_minor_upgrade_records_a_migration(self, tmp_path: Path) -> None:
        """The permitted crossing has to be distinguishable from a plain open.

        Mutation it catches: dropping ``migrates_store=True`` from the
        conforming return in ``_judge_parsed``. The upgrade would still be
        permitted and every other assertion here would still hold, but nothing
        downstream could tell that the store had been carried forward, which is
        the only fact this signal exists to carry.
        """
        storage = tmp_path / "storage"
        _make_collection(storage, "r0abc_vault_docs")
        write_store_format(storage, "1.15.4")

        verdict = judge_store_format(storage, spawning_version="1.16.0")

        assert verdict.verdict == CONFORMING
        assert verdict.migrates_store is True
        assert verdict.stored_version == "1.15.4"

    def test_patch_upgrade_records_a_migration(self, tmp_path: Path) -> None:
        storage = tmp_path / "storage"
        _make_collection(storage, "r0abc_vault_docs")
        write_store_format(storage, "1.15.4")

        assert judge_store_format(storage, spawning_version="1.15.5").migrates_store

    def test_same_version_is_not_a_migration(self, tmp_path: Path) -> None:
        """Reopening a store must not be reported as carrying it forward.

        Mutation it catches: deriving the signal from ``stored_version`` being
        set rather than from the upgrade branch. Every ordinary restart would
        then report a version change that never happened, and an operator who
        sees that on every start stops reading it.
        """
        storage = tmp_path / "storage"
        _make_collection(storage, "r0abc_vault_docs")
        write_store_format(storage, "1.15.4")

        verdict = judge_store_format(storage, spawning_version="1.15.4")

        assert verdict.verdict == CONFORMING
        assert verdict.migrates_store is False

    def test_empty_store_is_not_a_migration(self, tmp_path: Path) -> None:
        storage = tmp_path / "storage"
        storage.mkdir(parents=True)

        verdict = judge_store_format(storage, spawning_version="1.16.0")

        assert verdict.migrates_store is False

    def test_refusal_is_not_a_migration(self, tmp_path: Path) -> None:
        """A refused start moved nothing, so it carried nothing forward.

        Mutation it catches: setting the flag before the compatibility window is
        applied. A downgrade would then be reported as a completed migration
        while the start was actually refused - a degradation describing an event
        that did not happen.
        """
        storage = tmp_path / "storage"
        _make_collection(storage, "r0abc_vault_docs")
        write_store_format(storage, "1.16.0")

        verdict = judge_store_format(storage, spawning_version="1.15.4")

        assert verdict.verdict == NONCONFORMING
        assert verdict.migrates_store is False

    def test_unverifiable_store_is_not_a_migration(self, tmp_path: Path) -> None:
        storage = tmp_path / "storage"
        _make_collection(storage, "r0abc_vault_docs")

        verdict = judge_store_format(storage, spawning_version="1.16.0")

        assert verdict.verdict == UNVERIFIABLE
        assert verdict.migrates_store is False


class TestMigrationReachesHealth:
    """A migrated store must not sit silently behind a ready status."""

    @staticmethod
    def _health(**overrides: object) -> ServiceHealth:
        base: dict[str, object] = {
            "model_loaded": True,
            "reranker_loaded": True,
            "cuda": True,
            "project_count": 1,
            "projects": ["/proj"],
            "nonconforming": [],
        }
        base.update(overrides)
        return cast("ServiceHealth", base)

    @staticmethod
    def _server_qdrant(migrated_from: str) -> QdrantRuntimeState:
        return QdrantRuntimeState(
            mode="server",
            alive=True,
            port=6333,
            version="1.16.0",
            extra={"quarantined": [], "migrated_from": migrated_from},
        )

    def test_unmigrated_store_stays_ready(self) -> None:
        status, reasons = _service_health_status(
            self._health(), self._server_qdrant("")
        )

        assert status == "ready"
        assert reasons == []

    def test_migrated_store_degrades_the_service(self) -> None:
        """The gap this closes: a one-way migration with no operator signal.

        Mutation it catches: dropping the migration branch from
        ``_service_health_status``. The upgrade is permitted, every probe stays
        green, and nothing anywhere records that the binary which wrote the
        store can no longer read it - which is what an operator needs before
        attempting to go back.
        """
        status, reasons = _service_health_status(
            self._health(), self._server_qdrant("1.15.4")
        )

        assert status == "degraded"
        assert any("carried across" in reason for reason in reasons)

    def test_reason_names_both_versions(self) -> None:
        """Naming only one version leaves the operator unable to act.

        Mutation it catches: dropping either version from the reason text. The
        degradation would still fire and still be paired, but the operator could
        not tell which binary to reinstall to read the store as it was.
        """
        _, reasons = _service_health_status(
            self._health(), self._server_qdrant("1.15.4")
        )
        migration = [r for r in reasons if "carried across" in r]

        assert len(migration) == 1
        assert "1.15.4" in migration[0]
        assert "1.16.0" in migration[0]

    def test_migration_reason_is_paired_with_its_remediation(self) -> None:
        """A cause with no next move leaves the operator stuck.

        Mutation it catches: removing the store-format entry from the degraded
        family registry. The cause would still reach the operator through the
        unpaired sweep, so this asserts the family and the command specifically
        - the parts that are actually lost.
        """
        status, reasons = _service_health_status(
            self._health(), self._server_qdrant("1.15.4")
        )
        payload: dict[str, object] = {
            "status": status,
            "degraded_reasons": reasons,
            "qdrant": {"alive": True, "quarantined": [], "migrated_from": "1.15.4"},
        }

        findings = degradation_findings(payload)
        migration = [f for f in findings if f.family == STORE_FORMAT_FAMILY]

        assert len(migration) == 1
        assert migration[0].command == "vaultspec-rag server status"
        assert "1.15.4" in migration[0].detail

    def test_a_migration_and_a_quarantine_are_reported_separately(self) -> None:
        """Coexistence coverage, not a guard: two problems, two findings.

        Both reasons name the vector store, so both are eligible for the
        broader ``vector`` stem. This pins the outcome rather than the
        mechanism, and no single mutation distinguishes it from the pairing
        tests above.
        """
        qdrant = QdrantRuntimeState(
            mode="server",
            alive=True,
            port=6333,
            version="1.16.0",
            extra={
                "quarantined": ["r0abc_vault_docs.20260725T101500Z"],
                "migrated_from": "1.15.4",
            },
        )
        status, reasons = _service_health_status(self._health(), qdrant)
        payload: dict[str, object] = {
            "status": status,
            "degraded_reasons": reasons,
            "qdrant": {
                "alive": True,
                "quarantined": ["r0abc_vault_docs.20260725T101500Z"],
                "migrated_from": "1.15.4",
            },
        }

        families = {f.family for f in degradation_findings(payload)}

        assert QUARANTINE_FAMILY in families
        assert STORE_FORMAT_FAMILY in families


class TestRuntimeStateCarriesTheMigration:
    """The supervisor is the one producer of the migration signal."""

    def test_state_reports_the_version_migrated_from(self, tmp_path: Path) -> None:
        """The signal has to survive the open that erases its evidence.

        Mutation it catches: dropping ``migrated_from`` from ``state()``. The
        successful open rewrites the stamp to the running version, so nothing
        on disk records the crossing afterwards; without the held value the
        health author sees nothing and the degradation can never fire in
        production however well it tests in isolation.
        """
        supervisor = QdrantSupervisor(
            tmp_path / "qdrant-stub",
            http_port=6333,
            storage_dir=tmp_path / "storage",
            log_path=tmp_path / "qdrant.log",
            migrated_from="1.15.4",
        )

        state = supervisor.state()

        assert state.extra.get("migrated_from") == "1.15.4"
        assert state.to_dict().get("migrated_from") == "1.15.4"

    def test_state_reports_no_migration_by_default(self, tmp_path: Path) -> None:
        supervisor = QdrantSupervisor(
            tmp_path / "qdrant-stub",
            http_port=6333,
            storage_dir=tmp_path / "storage",
            log_path=tmp_path / "qdrant.log",
        )

        assert supervisor.state().extra.get("migrated_from") == ""
