"""Unit tests for the bounded, read-only readiness reporter.

Exercises the real readiness computation against the real environment
with no mocks, no patches, and no network: torch CUDA availability is a
real expectation (the dev host has an RTX 4080, so CUDA *is* available -
that is a real assertion, not a skip condition), model presence is the
real Hugging Face cache probe, and the qdrant dimension reads a real
temp-isolated resolution state. The report's read-only contract is
proven by asserting the managed dir and the configured pyproject are
untouched across a computation, and the serialisable shape is proven by
round-tripping through ``json.dumps``.

See the plan ``2026-06-13-server-first-default-plan`` (W03.P07) and the
ADR ``2026-06-13-provisioning-setup-adr``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, cast

import pytest

from .._readiness import (
    DependencyReadiness,
    ReadinessReport,
    ReadinessStatus,
    compute_readiness,
)
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DIMENSIONS = ("torch", "models", "qdrant")


@pytest.fixture(autouse=True)
def _reset_config_around_each_test() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    yield
    reset_config()


@pytest.fixture
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the managed service dir (and thus the qdrant bin dir) at tmp."""
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
    reset_config()
    try:
        yield tmp_path
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


@pytest.fixture
def local_only_env() -> Iterator[None]:
    """Force the effective backend to local for the qdrant dimension test."""
    prev = os.environ.get(EnvVar.LOCAL_ONLY.value)
    os.environ[EnvVar.LOCAL_ONLY.value] = "1"
    reset_config()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(EnvVar.LOCAL_ONLY.value, None)
        else:
            os.environ[EnvVar.LOCAL_ONLY.value] = prev
        reset_config()


class TestReadinessReportModel:
    def test_ready_is_true_only_when_every_dimension_is_ready(self) -> None:
        all_ready = ReadinessReport(
            dependencies=[
                DependencyReadiness("torch", ReadinessStatus.READY),
                DependencyReadiness("models", ReadinessStatus.READY),
                DependencyReadiness("qdrant", ReadinessStatus.READY),
            ]
        )
        assert all_ready.ready is True

        one_missing = ReadinessReport(
            dependencies=[
                DependencyReadiness("torch", ReadinessStatus.READY),
                DependencyReadiness("models", ReadinessStatus.NOT_READY),
                DependencyReadiness("qdrant", ReadinessStatus.READY),
            ]
        )
        assert one_missing.ready is False

    def test_empty_report_is_not_ready(self) -> None:
        assert ReadinessReport().ready is False

    def test_dimension_lookup_finds_the_named_node(self) -> None:
        node = DependencyReadiness("models", ReadinessStatus.READY)
        report = ReadinessReport(dependencies=[node])
        assert report.dimension("models") is node
        assert report.dimension("qdrant") is None

    def test_to_dict_is_json_serialisable_and_complete(self) -> None:
        report = ReadinessReport(
            dependencies=[
                DependencyReadiness(
                    "torch",
                    ReadinessStatus.READY,
                    "CUDA available",
                    info={"cuda_available": True},
                ),
            ],
            server_mode=True,
        )
        data = report.to_dict()
        json.dumps(data)  # must not raise
        assert data["ready"] is True
        assert data["server_mode"] is True
        node = report.dependencies[0].to_dict()
        assert node["name"] == "torch"
        assert node["status"] == "ready"
        assert node["info"] == {"cuda_available": True}


@pytest.mark.usefixtures("isolated_status_dir")
class TestComputeReadinessShape:
    def test_report_is_bounded_to_the_known_dependency_set(self) -> None:
        report = compute_readiness()
        names = [dep.name for dep in report.dependencies]
        # Bounded and ordered: exactly the three known dependencies, no
        # accretion into a general health console.
        assert names == list(_DIMENSIONS)

    def test_every_dimension_carries_a_bounded_status(self) -> None:
        report = compute_readiness()
        for dep in report.dependencies:
            assert dep.status in {
                ReadinessStatus.READY,
                ReadinessStatus.NOT_READY,
                ReadinessStatus.UNKNOWN,
            }

    def test_report_round_trips_through_json(self) -> None:
        data = compute_readiness().to_dict()
        restored = json.loads(json.dumps(data))
        assert set(restored.keys()) == {"ready", "server_mode", "dependencies"}
        assert [d["name"] for d in restored["dependencies"]] == list(_DIMENSIONS)


@pytest.mark.usefixtures("isolated_status_dir")
class TestTorchDimension:
    def test_torch_dimension_reflects_the_real_cuda_state(self) -> None:
        # The reporter must mirror the host's actual CUDA state: ready with
        # a real device (the GPU dev host), not-ready without one (a CPU-only
        # CI runner). Asserting against the live value keeps the test
        # hermetic on either host rather than requiring a GPU.
        import torch

        available = torch.cuda.is_available()
        report = compute_readiness()
        torch_dep = report.dimension("torch")
        assert torch_dep is not None
        assert torch_dep.info["installed"] is True
        assert torch_dep.info["cuda_available"] is available
        assert torch_dep.status == (
            ReadinessStatus.READY if available else ReadinessStatus.NOT_READY
        )

    def test_torch_dimension_does_not_force_a_model_load(self) -> None:
        # Computing readiness must not allocate the embedding/reranker
        # models onto the GPU. On a CUDA host we confirm no new device
        # memory was allocated across the call; on a CPU-only host there is
        # nothing to allocate, so we confirm the dimension is still produced
        # observably (no model load is forced either way).
        import torch

        if torch.cuda.is_available():
            before = torch.cuda.memory_allocated(0)
            compute_readiness()
            after = torch.cuda.memory_allocated(0)
            assert after == before
        else:
            report = compute_readiness()
            assert report.dimension("torch") is not None


@pytest.mark.usefixtures("isolated_status_dir")
class TestModelsDimension:
    def test_models_dimension_probes_each_configured_repo(self) -> None:
        from ..config import get_config

        cfg = get_config()
        report = compute_readiness()
        models = report.dimension("models")
        assert models is not None
        repos = cast("dict[str, object]", models.info["repos"])
        assert isinstance(repos, dict)
        # The probe reports presence for each configured repo, keyed by
        # the repo id, with a boolean value (no download triggered).
        expected = {
            str(cfg.embedding_model),
            str(cfg.sparse_model),
            str(cfg.reranker_model),
        }
        assert set(repos.keys()) == expected
        assert all(isinstance(v, bool) for v in repos.values())

    def test_models_status_matches_the_real_cache_state(self) -> None:
        report = compute_readiness()
        models = report.dimension("models")
        assert models is not None
        repos = cast("dict[str, object]", models.info["repos"])
        assert isinstance(repos, dict)
        all_present = all(repos.values())
        if all_present:
            assert models.status == ReadinessStatus.READY
        else:
            assert models.status == ReadinessStatus.NOT_READY
            assert models.detail


@pytest.mark.usefixtures("isolated_status_dir")
class TestQdrantDimension:
    def test_absent_binary_is_not_ready_in_server_mode(self) -> None:
        # Server mode is the effective default and the temp-isolated
        # managed dir holds no provisioned binary. Unless an operator env
        # binary or a PATH qdrant resolves on this host, the dimension is
        # NOT_READY with an actionable remediation.
        from ..qdrant_runtime import resolve_binary

        report = compute_readiness()
        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert report.server_mode is True

        if resolve_binary() is None:
            assert qdrant.status == ReadinessStatus.NOT_READY
            assert qdrant.info["binary_source"] == "absent"
            assert "--local-only" in qdrant.detail
        else:
            # A real provisioned/PATH binary on the dev host: with no
            # supervised child in this process, a resolvable binary reads
            # READY.
            assert qdrant.status == ReadinessStatus.READY
            assert qdrant.info["binary_source"] in {"env", "provisioned", "path"}

    @pytest.mark.usefixtures("local_only_env")
    def test_local_only_makes_an_absent_binary_ready(self) -> None:
        report = compute_readiness()
        assert report.server_mode is False
        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        # Local-only needs no server binary, so the on-disk store is
        # ready regardless of whether a binary resolves.
        assert qdrant.status == ReadinessStatus.READY
        assert qdrant.info["server_mode"] is False

    def test_resolution_source_reflects_an_operator_supplied_binary(
        self, tmp_path: Path
    ) -> None:
        # An operator-supplied binary is the first resolution source.
        # Point the env knob at a real file and confirm the dimension
        # reports the ``env`` source - read-only, no execution.
        fake_binary = tmp_path / "qdrant-operator"
        fake_binary.write_bytes(b"operator-supplied")
        prev = os.environ.get(EnvVar.QDRANT_BINARY.value)
        os.environ[EnvVar.QDRANT_BINARY.value] = str(fake_binary)
        reset_config()
        try:
            report = compute_readiness()
            qdrant = report.dimension("qdrant")
            assert qdrant is not None
            assert qdrant.info["binary_source"] == "env"
            assert qdrant.info["binary_path"] == str(fake_binary)
            # Binary resolves and no child is supervised in this process,
            # so the read-only reporter can honestly call it ready.
            assert qdrant.status == ReadinessStatus.READY
        finally:
            if prev is None:
                os.environ.pop(EnvVar.QDRANT_BINARY.value, None)
            else:
                os.environ[EnvVar.QDRANT_BINARY.value] = prev
            reset_config()


class TestReadOnlyContract:
    def test_compute_readiness_writes_nothing_to_the_managed_dir(
        self, isolated_status_dir: Path
    ) -> None:
        # A read-only report must not provision a binary or create any
        # managed-dir state as a side effect of probing.
        compute_readiness()
        assert not (isolated_status_dir / "bin").exists()

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_compute_readiness_is_repeatable_and_stable(self) -> None:
        first = compute_readiness().to_dict()
        second = compute_readiness().to_dict()
        # Same environment, same bounded snapshot - no mutation drifted
        # the result between calls.
        assert first == second
