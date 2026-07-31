"""Client/service release-compatibility classification.

A client and the daemon it drives are separate installs that drift
independently: a ``uv tool`` global install beside a project-local venv, one
machine with several checkouts, an upgrade that replaces the client and leaves
the previous daemon running. Nothing in the wire surface said so, so a client
would attach to a foreign release and drive it - sending fields that release
does not know (an unrecognised field is dropped, not refused), computing against
a different candidate set, and reporting an already-running success for a daemon
from an entirely different install.

The daemon now publishes its own package version on ``/health``, ``/readiness``
and both discovery views under :data:`SERVICE_VERSION_FIELD`. This module is the
single place that compares it, so the CLI and the MCP cannot diagnose one
condition two different ways.

The policy is exact equality, and a version that cannot be read is not a pass.
The same codebase already refuses to attach to a Qdrant server whose version it
cannot confirm, for the reason that applies here too: accepting an unconfirmable
version defeats the check. An unreported version is its own state rather than a
mismatch, so an operator is told the service predates version reporting instead
of being shown two versions that differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The wire field every publisher stamps and every reader compares. Declared
#: once here so the five publication sites cannot drift on the spelling.
SERVICE_VERSION_FIELD = "package_version"

#: Compatibility outcomes. ``match`` is the only compatible one; the other two
#: are distinct so a caller reports the condition it actually found.
VERSION_STATE_MATCH = "match"
VERSION_STATE_MISMATCH = "mismatch"
VERSION_STATE_UNREPORTED = "unreported"

#: Structured error codes for the failure envelopes. One per state, because a
#: code shared by two branches is satisfied by whichever fires.
VERSION_ERROR_MISMATCH = "service_version_mismatch"
VERSION_ERROR_UNREPORTED = "service_version_unreported"

#: The one remediation for both incompatible states: the running daemon is not
#: this install's, and only replacing it converges them.
_RESTART_REMEDIATION = (
    "Restart the service so it runs this install: "
    "`vaultspec-rag server stop` then `vaultspec-rag server start`.",
)

__all__ = [
    "SERVICE_VERSION_FIELD",
    "VERSION_ERROR_MISMATCH",
    "VERSION_ERROR_UNREPORTED",
    "VERSION_STATE_MATCH",
    "VERSION_STATE_MISMATCH",
    "VERSION_STATE_UNREPORTED",
    "DataPlaneService",
    "ServiceVersionVerdict",
    "classify_service_version",
    "local_package_version",
    "resolve_data_plane_service",
]


def local_package_version() -> str:
    """Return the ``vaultspec-rag`` release string of *this* install.

    Used by both sides: the daemon stamps it into what it publishes, and a
    client compares it against what it read. One function so the publishing and
    comparing halves can never resolve the version two different ways.

    Read through the package attribute rather than ``importlib.metadata`` here,
    because that attribute is already resolved-and-cached on first access; a
    second metadata read would cost the same ~100ms for the same string.
    """
    import vaultspec_rag

    return str(vaultspec_rag.__version__)


@dataclass(frozen=True, slots=True)
class ServiceVersionVerdict:
    """One release-compatibility verdict, with the evidence behind it.

    Carries both versions so every surface renders the same two facts, and the
    state so no surface has to re-derive the comparison from them.
    """

    state: str
    client_version: str
    service_version: str | None = None

    @property
    def is_compatible(self) -> bool:
        """Whether the client may drive this service."""
        return self.state == VERSION_STATE_MATCH

    def error_code(self) -> str | None:
        """Return the structured error code, or ``None`` when compatible."""
        if self.state == VERSION_STATE_MISMATCH:
            return VERSION_ERROR_MISMATCH
        if self.state == VERSION_STATE_UNREPORTED:
            return VERSION_ERROR_UNREPORTED
        return None

    def reason(self) -> str:
        """Render a one-line operator-facing account of this verdict."""
        if self.state == VERSION_STATE_MATCH:
            return f"client and service both run vaultspec-rag {self.client_version}"
        if self.state == VERSION_STATE_MISMATCH:
            return (
                f"this vaultspec-rag client is {self.client_version} but the "
                f"running service is {self.service_version}"
            )
        return (
            "the running service does not report its vaultspec-rag version, so "
            f"it cannot be confirmed compatible with this client "
            f"({self.client_version})"
        )

    def remediation(self) -> tuple[str, ...]:
        """Return the operator's next actions, empty when compatible."""
        return () if self.is_compatible else _RESTART_REMEDIATION

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-serialisable view carried on every envelope."""
        return {
            "state": self.state,
            "client_version": self.client_version,
            "service_version": self.service_version,
            "compatible": self.is_compatible,
        }


def _reported_version(payload: Mapping[str, object] | None) -> str | None:
    """Return the service version a payload reports, or ``None``."""
    if payload is None:
        return None
    raw = payload.get(SERVICE_VERSION_FIELD)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def classify_service_version(
    payload: Mapping[str, object] | None,
) -> ServiceVersionVerdict:
    """Classify a service payload's reported version against this client's.

    Accepts any of the payloads that carry the field - a ``/health`` response, a
    ``/readiness`` report, or either discovery view - so a caller compares
    whichever it already holds instead of making a probe for the version alone.

    Args:
        payload: A service-published mapping, or ``None`` when none was read.

    Returns:
        The verdict. An absent, blank, or non-string version is
        ``unreported``, never a silent pass.
    """
    client = local_package_version()
    service = _reported_version(payload)
    if service is None:
        return ServiceVersionVerdict(
            state=VERSION_STATE_UNREPORTED,
            client_version=client,
        )
    if service == client:
        return ServiceVersionVerdict(
            state=VERSION_STATE_MATCH,
            client_version=client,
            service_version=service,
        )
    return ServiceVersionVerdict(
        state=VERSION_STATE_MISMATCH,
        client_version=client,
        service_version=service,
    )


@dataclass(frozen=True, slots=True)
class DataPlaneService:
    """A daemon a client is about to drive, and whether it may.

    Pairs the address with the release verdict because the two questions a
    data-plane caller has are always asked together, and answering them at
    separate seams is how the CLI ended up gating neither while the MCP gated
    both.
    """

    port: int | None
    version: ServiceVersionVerdict

    @property
    def reachable(self) -> bool:
        """Whether a usable address was resolved at all."""
        return self.port is not None

    @property
    def usable(self) -> bool:
        """Whether this client may send data-plane work to this daemon."""
        return self.port is not None and self.version.is_compatible


def resolve_data_plane_service() -> DataPlaneService:
    """Resolve the daemon for data-plane work, with its release verdict.

    The one seam every data-plane caller passes through - search, retrieval,
    index refresh, clean - on both the CLI and the MCP, so one rule decides for
    both rather than each adapter deciding for itself.

    Deliberately not used by the lifecycle and observability verbs. ``stop``,
    ``status``, ``doctor``, ``logs`` and ``jobs`` must keep working against a
    daemon of any release, because they are how an operator observes the
    mismatch and how they resolve it; gating them would leave the verdict
    unactionable.

    The version comes from the discovery payload this call already reads for the
    port, so the verdict costs no extra round trip.
    """
    from ._discovery import resolve_machine_service

    resolution = resolve_machine_service()
    return DataPlaneService(
        port=resolution.port if resolution.is_ready else None,
        version=classify_service_version(resolution.payload),
    )
