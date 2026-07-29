"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from ..job_manager.manager import JobManager
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcome,
    JobSource,
    JobSpec,
)
from ..service_quiesce import ServiceQuiesceController
from ._job_roots import (
    _TEST_PROJECT_ROOT,
    _TEST_PROJECT_ROOT_DIFFERENT,
    _TEST_PROJECT_ROOT_OTHER,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestManagedJobAdmission:
    """The canonical manager owns admission and replay under real contention."""

    def test_concurrent_equivalent_creates_share_one_exact_job(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT)

        def submit(_index: int) -> JobOutcome:
            return manager.create(spec, initiator)

        with ThreadPoolExecutor(max_workers=8) as workers:
            outcomes = list(workers.map(submit, range(32)))

        created = [outcome for outcome in outcomes if outcome.code == "job_created"]
        assert len(created) == 1
        assert created[0].job is not None
        exact_id = created[0].job.id
        assert {outcome.job.id for outcome in outcomes if outcome.job is not None} == {
            exact_id
        }
        assert manager.get(exact_id) is not None
        assert manager.get(exact_id[:8]) is None

        capacity = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                _TEST_PROJECT_ROOT_OTHER,
                JobMode.REBUILD,
            ),
            initiator,
        )
        assert capacity.code == "job_capacity_exceeded"

    def test_idempotency_replays_only_the_original_request(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)

        original = manager.create(spec, initiator, idempotency_key="request-7")
        replay = manager.create(spec, initiator, idempotency_key="request-7")
        conflict = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                _TEST_PROJECT_ROOT_DIFFERENT,
                JobMode.REBUILD,
            ),
            initiator,
            idempotency_key="request-7",
        )

        assert original.code == "job_created"
        assert replay.code == "idempotency_replayed"
        assert replay.job == original.job
        assert conflict.code == "idempotency_key_conflict"
        assert conflict.job == original.job

    def test_default_storage_is_managed_and_memory_only_is_explicit(self) -> None:
        from pathlib import Path

        from ..config._settings import get_config

        managed = JobManager(
            quiesce_controller=ServiceQuiesceController(), max_nonterminal=1
        )
        memory_only = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )

        assert managed.state_path == (
            Path(str(get_config().status_dir)).expanduser() / "jobs-state.json"
        )
        assert memory_only.state_path is None

    def test_managed_state_path_expands_home_relative_status_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ``~``-prefixed status dir never resolves to a cwd-relative ``~``.

        Binds to the ``expanduser()`` in the managed state-path resolution:
        without it, a service started from any working directory persists its
        canonical job state under ``./~/...`` relative to that directory,
        forking durable job state per start directory instead of sharing the
        one managed home location.
        """
        from pathlib import Path

        from ..config._settings import reset_config
        from ..config._types import EnvVar

        monkeypatch.setenv(EnvVar.STATUS_DIR.value, "~/.vaultspec-rag-jobs-guard")
        reset_config()
        try:
            managed = JobManager(
                quiesce_controller=ServiceQuiesceController(), max_nonterminal=1
            )
            assert managed.state_path is not None
            assert "~" not in managed.state_path.parts
            assert managed.state_path == (
                Path.home() / ".vaultspec-rag-jobs-guard" / "jobs-state.json"
            )
        finally:
            monkeypatch.undo()
            reset_config()

    def test_idempotency_aliases_and_key_length_are_bounded(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            max_terminal_history=1,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)

        assert manager.create(spec, initiator, idempotency_key="key-0").code == (
            "job_created"
        )
        assert manager.create(spec, initiator, idempotency_key="key-1").code == (
            "active_job_exists"
        )
        assert manager.create(spec, initiator, idempotency_key="key-2").code == (
            "active_job_exists"
        )
        assert manager.create(spec, initiator, idempotency_key="key-0").code == (
            "active_job_exists"
        )
        assert manager.create(spec, initiator, idempotency_key="x" * 257).code == (
            "invalid_idempotency_key"
        )

    def test_invalid_job_kinds_are_not_admitted(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=None,
        )
        maintenance = manager.create(
            JobSpec(
                JobOperation.MAINTENANCE,
                JobSource.MAINTENANCE,
                None,
                None,
            ),
            JobInitiator("schedule", "storage maintenance", None),
        )
        invalid_source = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.MAINTENANCE,
                None,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("schedule", "invalid index", None),
        )
        missing_root = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                None,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("http", "POST /jobs", None),
        )
        relative_root = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                "relative/project",
                JobMode.REBUILD,
            ),
            JobInitiator("cli", "server job create", "relative/project"),
        )

        assert maintenance.code == "invalid_job_spec"
        assert invalid_source.code == "invalid_job_spec"
        assert missing_root.code == "invalid_job_spec"
        assert relative_root.code == "invalid_job_spec"
        assert manager.active() == []

    def test_equivalent_root_spellings_deduplicate(self, tmp_path: Path) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=None,
        )
        initiator = JobInitiator("cli", "server job create", str(tmp_path))
        canonical = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.INCREMENTAL,
        )
        alias = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path / "uncreated" / ".."),
            JobMode.INCREMENTAL,
        )

        created = manager.create(canonical, initiator)
        deduplicated = manager.create(alias, initiator)

        assert created.code == "job_created"
        assert deduplicated.code == "active_job_exists"
        assert deduplicated.job == created.job
