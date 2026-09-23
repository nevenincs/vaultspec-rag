"""The operator state wire contract round-trips and refuses unknown fields."""

from __future__ import annotations

import pydantic
import pytest

from ..operator_state._features import PreprocessHookState, TypesafeState
from ..operator_state._installation import (
    ComputeCapability,
    HardwarePresence,
    InstallRole,
)
from ..operator_state._models import (
    ComputeReport,
    Degradation,
    HardwareReading,
    HealthReport,
    InstallationReport,
    RootFeatures,
    ServiceFeatures,
    ServiceStateReport,
    TypesafeReport,
)
from ..operator_state._service import DegradationReason, HealthVerdict

pytestmark = [pytest.mark.unit]


def _features() -> ServiceFeatures:
    return ServiceFeatures(
        typesafe=TypesafeReport(state=TypesafeState.ACTIVE, model="systemone"),
        reranker_enabled=True,
        reranker_loaded=True,
        sparse_enabled=False,
        watcher_enabled=True,
        preprocess_mode="default",
        storage_backend="server",
        embedding_model="Qwen/Qwen3-Embedding-0.6B",
    )


def _health() -> HealthReport:
    return HealthReport(
        status=HealthVerdict.DEGRADED,
        degradations=(
            Degradation(
                reason=DegradationReason.QUARANTINED,
                detail="1 collection(s) are quarantined",
            ),
        ),
        features=_features(),
        models_loaded=True,
        project_count=2,
        pid=100,
        parent_pid=1,
        port=8766,
        executable="python",
        prefix="/env",
        base_prefix="/base",
        uptime_s=12.5,
        schema_version=2,
        package_version="0.4.35",
        service_token="token",
        jobs={"active": 0},
        qdrant={"mode": "server"},
        quiesce={"state": "running"},
        backend_capabilities={},
        support_profile={},
    )


def _service_state() -> ServiceStateReport:
    return ServiceStateReport(
        installation=InstallationReport(
            role=InstallRole.HOST,
            mcp_adapter=True,
            executable="python",
            prefix="/env",
            hardware=HardwareReading(
                presence=HardwarePresence.NVIDIA_GPU,
                name="NVIDIA GeForce RTX 4080 SUPER",
                memory_mib=16376,
            ),
            compute=ComputeReport(
                capability=ComputeCapability.CPU_ONLY_BUILD,
                torch_version="2.14.0+cpu",
            ),
        ),
        root_features=RootFeatures(
            root="/repo",
            preprocess_hooks=PreprocessHookState.ACTIVE,
            preprocess_rule_count=2,
            watcher_running=True,
        ),
        index={},
        projects={},
        watcher={},
        qdrant={},
        quiesce={},
        schema_version=2,
    )


@pytest.mark.parametrize(
    "report", [_health(), _service_state()], ids=["health", "service-state"]
)
def test_a_report_survives_the_json_wire_unchanged(
    report: HealthReport | ServiceStateReport,
) -> None:
    wire = report.model_dump(mode="json")

    assert type(report).model_validate(wire) == report


def test_enum_fields_travel_as_their_plain_values() -> None:
    wire = _service_state().model_dump(mode="json")

    assert wire["installation"]["compute"]["capability"] == "cpu_only_build"
    assert wire["installation"]["hardware"]["presence"] == "nvidia_gpu"
    assert wire["root_features"]["preprocess_hooks"] == "active"


@pytest.mark.parametrize(
    ("model", "wire"),
    [
        (HealthReport, _health().model_dump(mode="json")),
        (ServiceStateReport, _service_state().model_dump(mode="json")),
    ],
    ids=["health", "service-state"],
)
def test_a_field_the_contract_does_not_know_is_refused(
    model: type[HealthReport] | type[ServiceStateReport],
    wire: dict[str, object],
) -> None:
    """A stray key is how a renamed field silently stops reaching the operator.

    Mutation check: relaxing the shared base to ``extra="ignore"`` makes both
    cases validate without raising; restoring ``extra="forbid"`` passes.
    """
    with pytest.raises(pydantic.ValidationError, match="Extra inputs are not"):
        model.model_validate({**wire, "cuda": True})


def test_an_unknown_state_value_is_refused_rather_than_rendered() -> None:
    wire = _health().model_dump(mode="json")

    with pytest.raises(pydantic.ValidationError, match="status"):
        HealthReport.model_validate({**wire, "status": "starting"})


def test_the_client_parses_the_models_the_service_serves() -> None:
    from ..serviceclient._typed_state import parse_report

    health = _health()
    state = _service_state()

    assert parse_report(HealthReport, health.model_dump(mode="json")) == health
    assert parse_report(ServiceStateReport, state.model_dump(mode="json")) == state


@pytest.mark.parametrize(
    "payload",
    [None, [], {"ok": False, "error": "admin_timeout"}],
    ids=["absent", "not-a-report", "transport-error"],
)
def test_anything_but_a_report_parses_to_nothing(payload: object) -> None:
    from ..serviceclient._typed_state import parse_report

    assert parse_report(HealthReport, payload) is None
    assert parse_report(ServiceStateReport, payload) is None


def test_a_report_from_another_release_parses_to_nothing() -> None:
    """A field this build does not know must not be rendered as if understood.

    Mutation check: parsing with a model that ignores unknown fields returns a
    report here and fails the assertion; restoring the strict parse passes.
    """
    from ..serviceclient._typed_state import parse_report

    wire = _health().model_dump(mode="json")

    assert parse_report(HealthReport, {**wire, "field_from_a_newer_release": 1}) is None
