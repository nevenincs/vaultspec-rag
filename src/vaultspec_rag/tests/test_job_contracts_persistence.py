"""test job contracts: the persistence half."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from .._atomic_write import write_json_atomically
from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobInitiator,
    JobMode,
    JobOperation,
    JobResourceSnapshot,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
    JobTimestamps,
    capabilities_for_state,
)
from ..job_persistence import (
    IdempotencyBinding,
    NewerStateVersionError,
    PersistedManagerState,
    PersistenceWriteError,
    load_persisted_state,
    save_persisted_state,
)
from ..service_quiesce import ServiceQuiesceController
from .test_job_contracts import (
    _REFUSED_AT_CONSTRUCTION,
    _ROUND_TRIP_CASES,
    _fully_populated_snapshot,
    _generation,
    _identical,
    _nested_past_the_encoders_limit,
    _runtime,
    _self_referential,
    _snapshot_in_state,
    _spec,
    _telemetry_of,
    _temporaries,
    _valid_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


pytestmark = [pytest.mark.unit]


class TestPersistedJobStateRoundTrip:
    """Anything the manager can hold must survive a write and read unchanged.

    A field that serializes but does not load again strands its job history in
    a file the next start refuses, one process removed from whatever produced
    it. Enumerating the shapes here is what keeps that from being discovered
    on an operator's machine.
    """

    @pytest.mark.parametrize(
        "snapshot",
        [snapshot for _, snapshot in _ROUND_TRIP_CASES],
        ids=[name for name, _ in _ROUND_TRIP_CASES],
    )
    def test_a_snapshot_survives_the_write_and_read_unchanged(
        self, tmp_path: Path, snapshot: JobSnapshot
    ) -> None:
        path = tmp_path / "jobs-state.json"
        state = _generation(snapshot)
        save_persisted_state(path, state)
        assert load_persisted_state(path) == state

    def test_a_whole_generation_of_distinct_jobs_survives_with_its_bindings(
        self, tmp_path: Path
    ) -> None:
        # Nonterminal jobs must name distinct work, so each takes its own root.
        running = _snapshot_in_state(
            JobState.RUNNING,
            job_id="job-running",
            spec=_spec(source=JobSource.VAULT, project_root=str(tmp_path / "a")),
        )
        queued = _snapshot_in_state(
            JobState.QUEUED,
            job_id="job-queued",
            spec=_spec(source=JobSource.DOCUMENT, project_root=str(tmp_path / "b")),
        )
        finished = _fully_populated_snapshot()
        state = PersistedManagerState(
            jobs=(running, queued, finished),
            bindings=(
                (
                    "key-running",
                    IdempotencyBinding(
                        signature=(running.spec, running.initiator, False),
                        job_id=running.id,
                    ),
                ),
                (
                    "键-unicode",
                    IdempotencyBinding(
                        signature=(queued.spec, queued.initiator, True),
                        job_id=queued.id,
                    ),
                ),
            ),
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, state)
        assert load_persisted_state(path) == state

    def _round_tripped_telemetry(
        self, tmp_path: Path, block: dict[str, object]
    ) -> dict[str, object]:
        snapshot = replace(_snapshot_in_state(JobState.SUCCEEDED), reuse=block)
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(snapshot))
        return _telemetry_of(load_persisted_state(path).jobs[0])

    def test_the_telemetry_a_run_actually_publishes_survives_intact(
        self, tmp_path: Path
    ) -> None:
        # The exact blocks the reuse and drift producers emit, spelled out
        # rather than sampled. These are what a real generation carries, so
        # they are what the round trip has to return unchanged - including the
        # value types, which plain equality would not notice losing.
        reuse: dict[str, object] = {
            "reuse_hits": 128,
            "reuse_misses": 32,
            "hit_rate": 0.8,
            "gpu_seconds_saved": 41.125,
            "donor_absent": False,
            "donor_collections": ["code_9f2a", "code_7b41"],
        }
        drift: dict[str, object] = {
            "superseded_paths": 3,
            "deferred_paths": ["src/pkg/a.py", "src/pkg/b.py"],
            "collisions_observed": 1,
            "retry_budget": 4,
        }
        snapshot = replace(
            _snapshot_in_state(JobState.SUCCEEDED), reuse=reuse, drift=drift
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(snapshot))
        loaded = load_persisted_state(path).jobs[0]
        assert _identical(loaded.reuse, reuse)
        assert _identical(loaded.drift, drift)

    def test_every_value_a_telemetry_block_may_carry_returns_identical(
        self, tmp_path: Path
    ) -> None:
        # The whole admitted value space in one block, at depth. A block is
        # free to name whatever counters a run measured, so what pins the
        # contract is the value space rather than any key list.
        block: dict[str, object] = {
            "absent": None,
            "on": True,
            "off": False,
            "zero": 0,
            "negative": -17,
            "beyond_double_precision": 2**53 + 1,
            "ratio": 0.5,
            "smallest_subnormal": 5e-324,
            "largest_finite": 1e308,
            "label": "reuse ✓ 索引 naïve",
            "empty_text": "",
            "empty_array": [],
            "empty_object": {},
            "mixed_array": [1, 1.0, "1", True, None, [2], {"k": "v"}],
            "nested_object": {"a": {"b": {"c": [{"d": 1}]}}},
        }
        assert _identical(self._round_tripped_telemetry(tmp_path, block), block)

    def test_key_order_is_the_one_thing_a_telemetry_block_does_not_keep(
        self, tmp_path: Path
    ) -> None:
        # A deliberate loss, kept and stated rather than closed. The state file
        # is written with sorted keys so two equal generations produce equal
        # bytes; insertion order is the price. Mappings compare without it, so
        # nothing downstream can observe the difference - but the exact
        # transformation is asserted here rather than left to be rediscovered.
        block: dict[str, object] = {"z": 1, "m": 2, "a": 3}
        loaded = self._round_tripped_telemetry(tmp_path, block)
        assert loaded == block
        assert list(block) == ["z", "m", "a"]
        assert list(loaded) == ["a", "m", "z"]

    def test_a_value_shared_by_two_keys_returns_as_two_equal_copies(
        self, tmp_path: Path
    ) -> None:
        # The other deliberate loss. JSON has no notion of a shared reference,
        # so a block naming one object under two keys gets two independent
        # objects back. They compare equal, so no reader can tell - but a
        # producer that expected to mutate one and see both would be wrong.
        shared: list[object] = ["code_9f2a"]
        block: dict[str, object] = {"donors": shared, "fallbacks": shared}
        assert block["donors"] is block["fallbacks"]
        loaded = self._round_tripped_telemetry(tmp_path, block)
        assert _identical(loaded, block)
        assert loaded["donors"] is not loaded["fallbacks"]

    def test_the_loader_accepts_every_telemetry_shape_a_decode_can_yield(
        self, tmp_path: Path
    ) -> None:
        # The contract on these blocks exists to stop a producer writing a
        # value that will not come back. It must never be what stops a start
        # reading one, so the accepted set covers the decoder's whole output
        # range: a block assembled straight in the file, through no model at
        # all, still loads. Narrowing the contract below this would strand a
        # generation of job history over a decorative field.
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.SUCCEEDED)))
        payload = cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )
        decoded = cast(
            "dict[str, object]",
            json.loads(
                '{"null":null,"true":true,"false":false,"big":-9007199254740993,'
                '"exp":1.5e-7,"text":"\\u7d22\\u5f15","deep":[1,[2,[3,[]]]],'
                '"object":{"nested":{"empty":{}}}}'
            ),
        )
        job = cast("list[dict[str, object]]", payload["jobs"])[0]
        job["reuse"] = decoded
        job["drift"] = decoded
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_persisted_state(path).jobs[0]
        assert _identical(loaded.reuse, decoded)
        assert _identical(loaded.drift, decoded)

    def test_the_writer_refuses_the_one_decodable_value_the_contract_rejects(
        self, tmp_path: Path
    ) -> None:
        # The premise the argument above rests on. A non-finite number is the
        # only thing a JSON decode can produce that the telemetry contract
        # turns away, so it is the only place the reader could end up stricter
        # than the writer. It does not: the single JSON writer refuses it too,
        # which is why no file this daemon wrote can hold one, and why
        # refusing it at construction cannot cost a start.
        probe = tmp_path / "probe.json"
        with pytest.raises(ValueError, match="Out of range float values"):
            write_json_atomically(probe, {"telemetry": {"hit_rate": math.nan}})
        assert not probe.exists()
        assert _temporaries(tmp_path) == []

    @pytest.mark.parametrize(
        "state", list(JobState), ids=[state.value for state in JobState]
    )
    def test_discarded_capabilities_always_match_what_was_written(
        self, tmp_path: Path, state: JobState
    ) -> None:
        # Capabilities are written but never read back - the loader derives
        # them again. That is only safe while the derivation reproduces the
        # written block exactly, so this asserts the identity rather than
        # trusting it, for every state a record can be persisted in.
        snapshot = _snapshot_in_state(state)
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(snapshot))
        payload = cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )
        jobs = cast("list[dict[str, object]]", payload["jobs"])
        written = cast("dict[str, bool]", jobs[0]["capabilities"])
        loaded = load_persisted_state(path).jobs[0]
        assert written == {
            "pausable": loaded.capabilities.pausable,
            "resumable": loaded.capabilities.resumable,
            "cancellable": loaded.capabilities.cancellable,
            "retryable": loaded.capabilities.retryable,
            "deletable": loaded.capabilities.deletable,
            "force_killable": loaded.capabilities.force_killable,
        }
        assert loaded.capabilities == snapshot.capabilities

    def test_a_start_paused_record_from_an_older_writer_gains_its_request_stamp(
        self, tmp_path: Path
    ) -> None:
        # The one deliberate asymmetry in the round trip. An older writer
        # emitted a start-paused job with an acknowledgement and no request,
        # which no current state machine can produce; loading repairs it. The
        # result is intentionally NOT the snapshot that was written.
        spec = _spec()
        acknowledged = 1000.0
        legacy = JobSnapshot(
            id="job-legacy",
            revision=1,
            spec=spec,
            state=JobState.PAUSED,
            desired_state=DesiredJobState.PAUSED,
            capabilities=capabilities_for_state(spec, JobState.PAUSED),
            attempt=JobAttempt(number=1),
            timestamps=JobTimestamps(
                created_at=acknowledged,
                state_changed_at=acknowledged,
                control_acknowledged_at=acknowledged,
            ),
            progress=None,
            result=None,
            error_kind=None,
            initiator=JobInitiator(kind="cli", command="index", project_root=None),
            runtime=_runtime(),
            resources=JobResourceSnapshot(started=None, finished=None),
            resilience=None,
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(legacy))
        loaded = load_persisted_state(path).jobs[0]
        assert loaded.timestamps.control_requested_at == acknowledged
        assert loaded == replace(
            legacy,
            timestamps=replace(legacy.timestamps, control_requested_at=acknowledged),
        )


class TestPersistedJobStateSchemaContract:
    """What a build accepts must not narrow to the exact file it writes.

    A reader pinned to one version turns every future layout change into an
    operator losing their history, which is the failure this states, and
    tests, the boundaries of.
    """

    def _written_payload(self, tmp_path: Path) -> tuple[Path, dict[str, object]]:
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        return path, cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )

    def _rewrite(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_a_file_from_a_newer_build_is_refused_as_newer_not_as_damaged(
        self, tmp_path: Path
    ) -> None:
        # Reading a layout this build does not know would turn a misread
        # record into a wrong decision. The refusal carries its own type and
        # the numbers as fields, so a caller can tell an intact file it is too
        # old for from a damaged one without matching on message text.
        path, payload = self._written_payload(tmp_path)
        declared = 2
        payload["version"] = declared
        self._rewrite(path, payload)
        with pytest.raises(NewerStateVersionError) as caught:
            load_persisted_state(path)
        assert caught.value.declared_version == declared
        assert caught.value.maximum_readable < declared
        assert caught.value.minimum_readable <= caught.value.maximum_readable

    def test_the_newer_build_refusal_remains_a_value_error(self) -> None:
        # Every reader narrowing to the parse layer's error type must keep
        # catching this. Promoting it out of that hierarchy would silently
        # un-handle the case in callers that never named the new type -
        # mutate the base class to prove this assertion is the one that
        # fails.
        assert issubclass(NewerStateVersionError, ValueError)

    def test_a_file_older_than_this_build_reads_is_refused_as_older(
        self, tmp_path: Path
    ) -> None:
        path, payload = self._written_payload(tmp_path)
        payload["version"] = 0
        self._rewrite(path, payload)
        with pytest.raises(ValueError, match="no longer readable"):
            load_persisted_state(path)

    def test_a_foreign_schema_is_refused_by_name(self, tmp_path: Path) -> None:
        path, payload = self._written_payload(tmp_path)
        payload["schema"] = "vaultspec.rag.something-else"
        self._rewrite(path, payload)
        with pytest.raises(ValueError, match="declares schema"):
            load_persisted_state(path)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("version", 0), ("schema", "vaultspec.rag.something-else")],
    )
    def test_only_a_too_new_file_carries_the_newer_build_refusal(
        self, tmp_path: Path, field: str, value: object
    ) -> None:
        # A layout below the readable floor is one this build genuinely cannot
        # interpret, with no newer sibling to preserve it for, and a foreign
        # schema is not this format at all. Widening the dedicated type to
        # either would tell an operator an intact file is waiting for a build
        # that reads it. Loosen the version comparison guarding the too-new
        # branch to prove this assertion is the one that fails.
        path, payload = self._written_payload(tmp_path)
        payload[field] = value
        self._rewrite(path, payload)
        with pytest.raises(ValueError) as caught:
            load_persisted_state(path)
        assert not isinstance(caught.value, NewerStateVersionError)

    def test_a_non_integer_version_is_refused(self, tmp_path: Path) -> None:
        path, payload = self._written_payload(tmp_path)
        payload["version"] = "1"
        self._rewrite(path, payload)
        with pytest.raises(ValueError, match="version must be an integer"):
            load_persisted_state(path)

    def test_fields_a_newer_writer_added_are_ignored_rather_than_refused(
        self, tmp_path: Path
    ) -> None:
        # Additive growth is what keeps the version from moving, so a file
        # carrying unknown keys at every level must still load unchanged.
        path, payload = self._written_payload(tmp_path)
        expected = load_persisted_state(path)
        payload["future_root_field"] = {"anything": True}
        job = cast("list[dict[str, object]]", payload["jobs"])[0]
        job["future_job_field"] = "ignored"
        cast("dict[str, object]", job["spec"])["future_spec_field"] = 1
        cast("dict[str, object]", job["runtime"])["future_runtime_field"] = None
        cast("dict[str, object]", job["resources"])["future_resource_field"] = []
        self._rewrite(path, payload)
        assert load_persisted_state(path) == expected

    def test_an_optional_field_a_newer_writer_added_defaults_when_absent(
        self, tmp_path: Path
    ) -> None:
        # The other half of additive growth: a build that writes a field must
        # still read a file written before that field existed.
        path, payload = self._written_payload(tmp_path)
        job = cast("list[dict[str, object]]", payload["jobs"])[0]
        for optional in (
            "resilience",
            "reuse",
            "drift",
            "gpu_lock_wait_seconds",
            "progress",
            "parent_job_id",
            "admission_acquired_at",
        ):
            del job[optional]
        self._rewrite(path, payload)
        loaded = load_persisted_state(path).jobs[0]
        assert loaded.resilience is None
        assert loaded.reuse is None
        assert loaded.drift is None
        assert loaded.gpu_lock_wait_seconds is None
        assert loaded.progress is None
        assert loaded.attempt.parent_job_id is None
        assert loaded.timestamps.admission_acquired_at is None


class TestPersistedJobStateWriteSide:
    """Every value the loader rejects must be refused where it is produced.

    A reading that is invalid on read but accepted on write puts a record on
    disk that only fails one boot later, in another process, on a path with no
    recovery. These pin the refusal to construction, where the traceback still
    names the producer.
    """

    @pytest.mark.parametrize(
        ("message", "construct"),
        [(message, construct) for _, message, construct in _REFUSED_AT_CONSTRUCTION],
        ids=[name for name, _, _ in _REFUSED_AT_CONSTRUCTION],
    )
    def test_a_value_the_loader_rejects_cannot_be_constructed(
        self, message: str, construct: Callable[[], object]
    ) -> None:
        with pytest.raises(ValueError, match=message):
            construct()

    def test_an_idempotency_binding_refuses_an_empty_job_id(self) -> None:
        snapshot = _valid_snapshot()
        with pytest.raises(TypeError, match="idempotency job_id must be a non-empty"):
            IdempotencyBinding(
                signature=(snapshot.spec, snapshot.initiator, False), job_id=""
            )

    def test_an_idempotency_binding_refuses_a_non_boolean_start_paused(self) -> None:
        # The loader checks this flag's type, so a binding carrying anything
        # else is written without complaint and refused one boot later.
        snapshot = _valid_snapshot()
        with pytest.raises(TypeError, match="idempotency start_paused must be boolean"):
            IdempotencyBinding(
                signature=(
                    snapshot.spec,
                    snapshot.initiator,
                    cast("bool", 1),
                ),
                job_id=snapshot.id,
            )

    def test_a_constructible_generation_survives_the_real_writer(
        self, tmp_path: Path
    ) -> None:
        state = PersistedManagerState(jobs=(_valid_snapshot(),), bindings=())
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, state)
        assert load_persisted_state(path) == state

    def test_a_quiesce_parked_job_reloads_through_the_real_loader(
        self, tmp_path: Path
    ) -> None:
        # A service quiesce parks queued work as paused while its intent stays
        # running, and resume selects on exactly that pair to tell it from work
        # an operator paused. The loader used to refuse the pair, so the manager
        # wrote a generation it could not read back.
        state_path = tmp_path / "jobs-state.json"
        root = str(tmp_path)
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=4,
            state_path=state_path,
        )
        created = manager.create(
            JobSpec(JobOperation.INDEX, JobSource.CODE, root, JobMode.INCREMENTAL),
            JobInitiator("service", "reindex_codebase", root),
        )
        assert created.job is not None
        deferred = manager.defer_unstarted_for_quiesce(created.job.id)
        assert deferred.job is not None
        assert deferred.job.state is JobState.PAUSED
        assert deferred.job.desired_state is DesiredJobState.RUNNING

        restored = load_persisted_state(state_path)
        assert [job.id for job in restored.jobs] == [created.job.id]
        assert restored.jobs[0].state is JobState.PAUSED
        assert restored.jobs[0].desired_state is DesiredJobState.RUNNING

    def test_paused_work_may_not_persist_cancelled_intent(self, tmp_path: Path) -> None:
        # Widening the paused pair set to admit running intent must not retire
        # the check: paused-but-cancelled remains incoherent.
        snapshot = replace(
            _valid_snapshot(),
            state=JobState.PAUSED,
            desired_state=DesiredJobState.CANCELLED,
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, PersistedManagerState(jobs=(snapshot,), bindings=()))
        with pytest.raises(ValueError, match="observed and desired states disagree"):
            load_persisted_state(path)

    def test_the_loader_still_refuses_a_null_memory_reading(
        self, tmp_path: Path
    ) -> None:
        # The loader's strictness is the invariant; the writer's permissiveness
        # was the defect. Loosening this read path to tolerate damaged records
        # would hide the next producer bug instead of surfacing it.
        path = tmp_path / "jobs-state.json"
        save_persisted_state(
            path, PersistedManagerState(jobs=(_valid_snapshot(),), bindings=())
        )
        payload = cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )
        jobs = cast("list[dict[str, object]]", payload["jobs"])
        resources = cast("dict[str, object]", jobs[0]["resources"])
        cast("dict[str, object]", resources["started"])["rss_mib"] = None
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(TypeError, match="resource rss_mib must be numeric"):
            load_persisted_state(path)


class TestPersistedJobStateLeavesNoDebris:
    """A write that fails must leave the state directory as it found it.

    Every temporary that outlives its write stays until an operator finds it,
    because nothing else looks at that directory again.
    """

    def test_a_replace_the_filesystem_refuses_leaves_no_temporary(
        self, tmp_path: Path
    ) -> None:
        # A real refusal, not a simulated one: a directory already occupies
        # the target name, so the temporary is written and the replace cannot
        # land. Nothing may survive that.
        path = tmp_path / "jobs-state.json"
        path.mkdir()
        with pytest.raises(PersistenceWriteError) as raised:
            save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        assert raised.value.published is False
        assert _temporaries(tmp_path) == []

    def test_a_successful_write_leaves_no_temporary(self, tmp_path: Path) -> None:
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        assert _temporaries(tmp_path) == []

    @pytest.mark.parametrize(
        ("build_block", "cause"),
        [
            # Two refusals, because the encoder has two of them and each
            # translates through a different arm. Nesting past the encoder's
            # ceiling raises RecursionError, which is neither an OSError nor a
            # ValueError; a cycle raises ValueError. Letting either out
            # untranslated would break the one exception type every caller of
            # this function handles.
            pytest.param(_self_referential, ValueError, id="a-cycle"),
            pytest.param(
                _nested_past_the_encoders_limit, RecursionError, id="past-the-ceiling"
            ),
        ],
    )
    def test_a_payload_that_cannot_be_encoded_never_reaches_a_temporary(
        self,
        tmp_path: Path,
        build_block: Callable[[], dict[str, object]],
        cause: type[Exception],
    ) -> None:
        # Serialization happens before the temporary is named, so a payload
        # the encoder refuses cannot leave debris at all rather than leaving
        # debris that gets cleaned up. This is NOT a cleanup guard: breaking
        # the cleanup leaves it passing, which is the point.
        snapshot = replace(_snapshot_in_state(JobState.QUEUED), reuse=build_block())
        path = tmp_path / "jobs-state.json"
        with pytest.raises(PersistenceWriteError) as raised:
            save_persisted_state(path, _generation(snapshot))
        assert raised.value.published is False
        assert isinstance(raised.value.__cause__, cause)
        assert _temporaries(tmp_path) == []
        assert not path.exists()
