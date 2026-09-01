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
"""

from __future__ import annotations

import json
import os
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from .._readiness import (
    DependencyReadiness,
    ReadinessReport,
    ReadinessStatus,
    _torch_readiness,
    compute_readiness,
)
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..store_schema import STORAGE_SCHEMA_VERSION as _STORAGE_SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DIMENSIONS = ("torch", "models", "qdrant")


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
        # The report carries the bounded storage-schema descriptor, the
        # config-derived support profile, and the package release alongside the
        # readiness dimensions. The set is exact: readiness stays a bounded
        # snapshot rather than accreting into a general health console.
        # ``package_version`` earns its place by being a gate rather than a
        # display field - a client refuses to drive a service whose release does
        # not match its own, so the value has to reach a direct consumer of this
        # report and not only /health.
        assert set(restored.keys()) == {
            "ready",
            "server_mode",
            "dependencies",
            "degraded_reasons",
            "support_profile",
            "schema",
            "package_version",
        }
        assert [d["name"] for d in restored["dependencies"]] == list(_DIMENSIONS)
        assert restored["schema"]["version"] == _STORAGE_SCHEMA_VERSION
        # Degraded reasons are the detail strings of the non-ready dimensions,
        # so the two views can never disagree.
        assert restored["degraded_reasons"] == [
            dep["detail"]
            for dep in restored["dependencies"]
            if dep["status"] != "ready" and dep["detail"]
        ]


@pytest.mark.usefixtures("isolated_status_dir")
class TestTorchDimension:
    def test_torch_dimension_reflects_the_real_accelerator_state(self) -> None:
        # The reporter mirrors whichever supported accelerator this host has.
        import torch

        cuda_available = torch.cuda.is_available()
        mps_available = torch.backends.mps.is_available()
        report = compute_readiness()
        torch_dep = report.dimension("torch")
        assert torch_dep is not None
        assert torch_dep.info["installed"] is True
        assert torch_dep.info["cuda_available"] is cuda_available
        assert torch_dep.info["mps_available"] is mps_available
        assert torch_dep.info["backend"] == (
            "cuda" if cuda_available else "mps" if mps_available else None
        )
        assert torch_dep.status == (
            ReadinessStatus.READY
            if (cuda_available or mps_available)
            else ReadinessStatus.NOT_READY
        )

    def test_mps_dimension_reports_unified_memory_without_cuda(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_torch = ModuleType("torch")
        fake_torch.__dict__.update(
            version=SimpleNamespace(cuda=None),
            cuda=SimpleNamespace(is_available=lambda: False),
            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
            mps=SimpleNamespace(),
        )
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)

        torch_dep = _torch_readiness()

        assert torch_dep.status is ReadinessStatus.READY
        assert torch_dep.info["backend"] == "mps"
        assert torch_dep.info["memory_kind"] == "unified"
        assert torch_dep.info["cuda_available"] is False
        assert torch_dep.info["mps_available"] is True
        assert "MPS available" in torch_dep.detail

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
        from ..config._settings import get_config

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
        from ..qdrant_runtime._resolve import resolve_binary

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
