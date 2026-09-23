"""The typed wire contract for operator state.

The service serialises these models on its health and service-state routes and
the service client parses the same models back, so a field either side does
not know is a validation error instead of a silently ignored key. Envelopes
another subsystem already owns - quiesce, the vector-store runtime, the jobs
rollup, device load - travel inside as that owner's mapping, because this
package does not get to redefine them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..config._types import PreprocessMode
from ..index_profiles import StorageBackend
from ._features import PreprocessHookState, TypesafeState
from ._installation import ComputeCapability, HardwarePresence, InstallRole
from ._service import DegradationReason, HealthVerdict

__all__ = [
    "ComputeReport",
    "Degradation",
    "HardwareReading",
    "HealthReport",
    "InstallationReport",
    "RootFeatures",
    "ServiceFeatures",
    "ServiceStateReport",
    "TypesafeReport",
]


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HardwareReading(_Wire):
    """The accelerator the machine has, independent of any torch install."""

    presence: HardwarePresence
    name: str | None = None
    memory_mib: int | None = None


class ComputeReport(_Wire):
    """Whether an environment can run inference, with the evidence."""

    capability: ComputeCapability
    torch_version: str | None = None
    backend: Literal["cuda", "mps"] | None = None
    device_name: str | None = None
    memory_mib: int | None = None
    detail: str | None = None


class InstallationReport(_Wire):
    """What one environment is: its role, interpreter, hardware and compute.

    ``local`` marks a report the client made about its own daemon
    interpreter because no service answered; a service's report about itself
    is never local.
    """

    role: InstallRole
    mcp_adapter: bool
    executable: str
    prefix: str
    hardware: HardwareReading
    compute: ComputeReport
    local: bool = False


class Degradation(_Wire):
    """One reason a live service is not fully healthy."""

    reason: DegradationReason
    detail: str


class TypesafeReport(_Wire):
    """Hosted classification as the service process sees it, redacted."""

    state: TypesafeState
    model: str
    last_success_age_seconds: float | None = None
    retry_after_seconds: float = 0.0


class ServiceFeatures(_Wire):
    """Optional features that apply to every root the service serves."""

    typesafe: TypesafeReport
    reranker_enabled: bool
    reranker_loaded: bool
    sparse_enabled: bool
    watcher_enabled: bool
    preprocess_mode: PreprocessMode
    storage_backend: StorageBackend
    embedding_model: str
    sparse_model: str | None = None
    reranker_model: str | None = None


class RootFeatures(_Wire):
    """Optional features resolved for one repository."""

    root: str
    preprocess_hooks: PreprocessHookState
    preprocess_rule_count: int
    watcher_running: bool


class HealthReport(_Wire):
    """The lightweight, ungated health probe of a live service."""

    status: HealthVerdict
    degradations: tuple[Degradation, ...] = ()
    features: ServiceFeatures
    models_loaded: bool
    project_count: int
    nonconforming: tuple[str, ...] = ()
    pid: int
    parent_pid: int
    port: int
    executable: str
    prefix: str
    base_prefix: str
    virtual_env: str | None = None
    uptime_s: float
    schema_version: int
    package_version: str
    service_token: str
    jobs: dict[str, object]
    qdrant: dict[str, object]
    quiesce: dict[str, object]
    device_load: dict[str, object] | None = None
    backend_capabilities: dict[str, object]
    support_profile: dict[str, object]


class ServiceStateReport(_Wire):
    """The consolidated, token-gated state of a live service for one root."""

    installation: InstallationReport
    root_features: RootFeatures
    index: dict[str, object]
    projects: dict[str, object]
    watcher: dict[str, object]
    qdrant: dict[str, object]
    quiesce: dict[str, object]
    schema_version: int
