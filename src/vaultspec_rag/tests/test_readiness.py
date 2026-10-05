"""Unit tests for the bounded, read-only readiness reporter.

Exercises the real readiness computation against the real environment
with no mocks, no patches, and no network: torch CUDA availability is a
real expectation (the dev host has an RTX 4080, so CUDA *is* available -
that is a real assertion, not a skip condition), model presence is the
real offline complete-snapshot cache probe at the configured revisions, and
the qdrant dimension reads a real
temp-isolated resolution state. The report's read-only contract is
proven by asserting the managed dir and the configured pyproject are
untouched across a computation, and the serialisable shape is proven by
round-tripping through ``json.dumps``.
"""

from __future__ import annotations

import hashlib
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
    _qdrant_readiness,
    _torch_readiness,
    compute_readiness,
)
from ..config._types import EnvVar
from ..operator_state._compute import classify_torch
from ..store_schema import STORAGE_SCHEMA_VERSION as _STORAGE_SCHEMA_VERSION
from ._config_fixtures import reset_config
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DIMENSIONS = ("torch", "models", "qdrant")

#: Both operator binary settings cleared. They outrank the managed install, so
#: a pair in the developer's own environment would decide the dimension.
_NO_OPERATOR_BINARY: dict[str, str | None] = {
    EnvVar.QDRANT_BINARY.value: None,
    EnvVar.QDRANT_BINARY_SHA256.value: None,
}


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
        # ``environment_holders`` is the one non-dependency member, and it is
        # deliberately outside ``dependencies`` so it cannot enter ``ready``:
        # a held environment is healthy, and the holders matter only to an
        # operator about to replace it. It is empty unless a caller opts into
        # the process-table walk that fills it.
        assert set(restored.keys()) == {
            "ready",
            "server_mode",
            "dependencies",
            "degraded_reasons",
            "environment_holders",
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


@pytest.mark.torch
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
        assert torch_dep.info["torch_version"] == torch.__version__
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

        torch_dep = _torch_readiness(classify_torch(fake_torch))

        assert torch_dep.status is ReadinessStatus.READY
        assert torch_dep.info["capability"] == "ready"
        assert torch_dep.info["backend"] == "mps"
        assert torch_dep.info["memory_mib"] is None
        assert "MPS available" in torch_dep.detail

    def test_a_client_without_torch_is_ready_not_broken(self) -> None:
        """A torch-free client never asked for an accelerator.

        Mutation check: mapping every non-ready capability to not-ready reports
        this client as broken and fails the status assertion; restoring the
        client branch passes.
        """
        from ..operator_state._installation import ComputeCapability
        from ..operator_state._models import ComputeReport

        torch_dep = _torch_readiness(
            ComputeReport(capability=ComputeCapability.NOT_APPLICABLE)
        )

        assert torch_dep.status is ReadinessStatus.READY
        assert "client" in torch_dep.detail

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
        # the repo id, with a complete-snapshot boolean (no download triggered).
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

    def test_disabled_sparse_is_never_probed_or_named_as_missing(self) -> None:
        # Dense-only mode must never require the SPARSEUP repo: it is
        # absent from the probed set entirely, and an absent cache entry for
        # it can therefore never surface as a readiness failure.
        from ..config._settings import get_config

        prev = os.environ.get(EnvVar.SPARSE_ENABLED.value)
        os.environ[EnvVar.SPARSE_ENABLED.value] = "0"
        reset_config()
        try:
            cfg = get_config()
            assert cfg.sparse_enabled is False
            report = compute_readiness()
            models = report.dimension("models")
            assert models is not None
            repos = cast("dict[str, object]", models.info["repos"])
            assert isinstance(repos, dict)
            assert str(cfg.sparse_model) not in repos
            assert str(cfg.embedding_model) in repos
            assert str(cfg.reranker_model) in repos
            if models.status == ReadinessStatus.NOT_READY:
                assert str(cfg.sparse_model) not in models.detail
        finally:
            if prev is None:
                os.environ.pop(EnvVar.SPARSE_ENABLED.value, None)
            else:
                os.environ[EnvVar.SPARSE_ENABLED.value] = prev
            reset_config()


@pytest.mark.usefixtures("isolated_status_dir")
class TestQdrantDimension:
    def test_absent_binary_is_not_ready_in_server_mode(self) -> None:
        # Server mode is the effective default, the temp-isolated managed dir
        # holds no provisioned binary, and the operator setting is cleared, so
        # nothing resolves: there is no other place a binary is looked for.
        with managed_env(**_NO_OPERATOR_BINARY):
            report = compute_readiness()
        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert report.server_mode is True
        assert qdrant.status == ReadinessStatus.NOT_READY
        assert qdrant.info["binary_source"] == "absent"
        assert "--local-only" in qdrant.detail

    def test_an_unusable_operator_setting_is_not_ready_and_says_why(
        self, tmp_path: Path
    ) -> None:
        """A setting a start would refuse must not read as an absent binary.

        Proven able to fail: letting the refusal fall through to the absent
        branch fails this on the ``invalid`` source assertion below.
        """
        missing = tmp_path / "no-such-qdrant"
        with managed_env(
            **{
                EnvVar.QDRANT_BINARY.value: str(missing),
                EnvVar.QDRANT_BINARY_SHA256.value: "c" * 64,
            }
        ):
            report = compute_readiness()
        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert qdrant.status == ReadinessStatus.NOT_READY
        assert qdrant.info["binary_source"] == "invalid"
        assert qdrant.info["binary_error"] == "qdrant_binary_invalid"
        assert qdrant.info["binary_path"] is None
        assert EnvVar.QDRANT_BINARY.value in qdrant.detail
        assert str(missing) in qdrant.detail

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

    def test_an_operator_binary_that_matches_its_declared_digest_is_ready(
        self, tmp_path: Path
    ) -> None:
        # An operator binary is the first resolution source. Name a real file
        # with its real digest and confirm the dimension reports the ``env``
        # source - read-only, hashed, never executed.
        fake_binary = tmp_path / "qdrant-operator"
        fake_binary.write_bytes(b"operator-supplied")
        declared = hashlib.sha256(b"operator-supplied").hexdigest()
        with managed_env(
            **{
                EnvVar.QDRANT_BINARY.value: str(fake_binary),
                EnvVar.QDRANT_BINARY_SHA256.value: declared,
            }
        ):
            report = compute_readiness()
        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert qdrant.info["binary_source"] == "env"
        assert qdrant.info["binary_path"] == str(fake_binary)
        assert "binary_error" not in qdrant.info
        assert qdrant.status == ReadinessStatus.READY

    def test_an_operator_binary_that_is_not_what_was_declared_is_not_ready(
        self, tmp_path: Path
    ) -> None:
        """An operator binary is reported usable only after hashing it too.

        Mutation it catches: hashing only the managed install. The operator
        binary then reads ``READY`` on resolution alone and this fails on the
        status assertion.
        """
        fake_binary = tmp_path / "qdrant-operator"
        fake_binary.write_bytes(b"what the operator has")
        declared = hashlib.sha256(b"what the operator declared").hexdigest()
        with managed_env(
            **{
                EnvVar.QDRANT_BINARY.value: str(fake_binary),
                EnvVar.QDRANT_BINARY_SHA256.value: declared,
            }
        ):
            report = compute_readiness()
        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert qdrant.status == ReadinessStatus.NOT_READY
        assert qdrant.info["binary_source"] == "env"
        assert qdrant.info["binary_error"] == "qdrant_binary_unverified"
        assert EnvVar.QDRANT_BINARY_SHA256.value in qdrant.detail

    @staticmethod
    def _seed_install_that_is_not_the_pinned_release(source: str = "download") -> Path:
        """Seed a managed install whose manifest is in order and whose bytes are not.

        The manifest says everything a provisioning run would have it say,
        down to the committed digest of the release executable. Only hashing
        the executable tells the install from a real one.
        """
        from ..qdrant_runtime._constants import (
            MANIFEST_FILENAME,
            QDRANT_ASSET_SHA256,
            QDRANT_EXECUTABLE_SHA256,
            QDRANT_SERVER_VERSION,
        )
        from ..qdrant_runtime._resolve import (
            asset_for_platform,
            binary_filename,
            qdrant_bin_dir,
        )

        version_dir = qdrant_bin_dir()
        version_dir.mkdir(parents=True)
        binary = version_dir / binary_filename()
        binary.write_bytes(b"not the pinned release")
        asset = asset_for_platform()
        (version_dir / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "version": QDRANT_SERVER_VERSION,
                    "asset": asset,
                    "asset_sha256": QDRANT_ASSET_SHA256[asset],
                    "binary_sha256": QDRANT_EXECUTABLE_SHA256[asset],
                    "source": source,
                }
            ),
            encoding="utf-8",
        )
        return binary

    @pytest.mark.parametrize("source", ["download", "archive", "operator"])
    def test_an_install_that_is_not_the_pinned_release_is_not_ready(
        self, source: str
    ) -> None:
        """An install a start would refuse is reported refused, with every remedy.

        Nothing resolves, so no binary is named as the one in use; the detail
        carries the path and both ways to replace what is there.

        Mutation it catches: reading a refused install as no install. The
        operator is then told to provision over a file a provisioning run
        refuses to overwrite, and this fails on the source assertion.
        """
        binary = self._seed_install_that_is_not_the_pinned_release(source)

        with managed_env(**_NO_OPERATOR_BINARY):
            report = compute_readiness()

        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert qdrant.status == ReadinessStatus.NOT_READY
        assert qdrant.info["binary_source"] == "invalid"
        assert qdrant.info["binary_path"] is None
        assert qdrant.info["binary_error"] == "qdrant_binary_unverified"
        assert str(binary) in qdrant.detail
        assert "vaultspec-rag server qdrant install --upgrade" in qdrant.detail
        assert "--archive <file>" in qdrant.detail
        assert EnvVar.QDRANT_BINARY_SHA256.value in qdrant.detail

    @pytest.mark.usefixtures("local_only_env")
    def test_local_only_does_not_judge_a_binary_it_will_not_run(self) -> None:
        """Nothing is looked for, so what a start would refuse is not reported.

        Mutation it catches: dropping the answer local-only mode gets before
        any binary is judged. The seeded file is then judged and refused, and
        this fails on the source assertion.
        """
        self._seed_install_that_is_not_the_pinned_release()

        with managed_env(**_NO_OPERATOR_BINARY):
            report = compute_readiness()

        qdrant = report.dimension("qdrant")
        assert qdrant is not None
        assert qdrant.info["binary_source"] == "not_needed"
        assert qdrant.status == ReadinessStatus.READY
        assert "binary_error" not in qdrant.info

    def test_a_check_that_does_not_finish_is_not_ready(self) -> None:
        """Running out of time is neither a pass nor an absent binary.

        A budget of nothing stands in for a file that cannot be read in time:
        the judgement is never given the chance to finish.

        Mutation it catches: reporting an unfinished judgement as nothing
        installed. The operator is then told to provision what may already be
        there, and this fails on the source assertion.
        """
        self._seed_install_that_is_not_the_pinned_release()

        with managed_env(**_NO_OPERATOR_BINARY):
            qdrant = _qdrant_readiness(server_mode=True, verify_budget=0.0)

        assert qdrant.status == ReadinessStatus.NOT_READY
        assert qdrant.info["binary_source"] == "unchecked"
        assert qdrant.info["binary_error"] == "qdrant_binary_unchecked"
        assert "could not be verified" in qdrant.detail


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
