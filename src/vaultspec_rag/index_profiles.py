"""Named, closed resource and corpus support profiles for index admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from ._job_errors import JobError, JobErrorKind
from ._units import human_bytes

if TYPE_CHECKING:
    from ._store_writes import VolumeReading

__all__ = [
    "IndexDomain",
    "IndexSupportProfile",
    "SupportMeasurement",
    "SupportProfileLimits",
    "get_index_support_profile",
    "index_support_profile_status",
    "validate_profile_admission",
]

type StorageBackend = Literal["local", "server"]


class IndexDomain(StrEnum):
    """Independently admitted indexing domains."""

    CODE = "code"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class SupportMeasurement:
    """Bounded corpus dimensions known at an admission boundary."""

    source_files: int
    source_bytes: int
    generated_chunks: int = 0
    weighted_bytes: int = 0
    extracted_bytes: int = 0
    queue_bytes: int = 0
    rss_bytes: int = 0
    cuda_bytes: int = 0

    def __post_init__(self) -> None:
        for name in (
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
            "extracted_bytes",
            "queue_bytes",
            "rss_bytes",
            "cuda_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class SupportProfileLimits:
    """Maximum admitted dimensions for one content domain."""

    source_files: int
    source_bytes: int
    generated_chunks: int
    weighted_bytes: int
    extracted_bytes: int
    queue_bytes: int
    rss_bytes: int
    cuda_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
            "extracted_bytes",
            "queue_bytes",
            "rss_bytes",
            "cuda_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def exceeded_by(self, measured: SupportMeasurement) -> tuple[str, int, int] | None:
        """Return the first exceeded dimension in stable diagnostic order.

        ``cuda_bytes`` is deliberately absent: the measured value is a runtime
        allocation peak, not a corpus dimension, and runtime CUDA demand is
        governed by the per-job ceiling and forward-peak capture. It stays a
        measured, reported field but never decides corpus admission.
        """
        for name in (
            "source_files",
            "source_bytes",
            "extracted_bytes",
            "generated_chunks",
            "weighted_bytes",
            "queue_bytes",
            "rss_bytes",
        ):
            actual = getattr(measured, name)
            limit = getattr(self, name)
            if actual > limit:
                return name, actual, limit
        return None


@dataclass(frozen=True, slots=True)
class IndexSupportProfile:
    """One named host, backend, and per-domain admission contract."""

    name: str
    accepted_backends: frozenset[StorageBackend]
    minimum_ram_bytes: int
    minimum_free_disk_bytes: int
    code: SupportProfileLimits
    document: SupportProfileLimits

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("profile name must not be empty")
        if not self.accepted_backends:
            raise ValueError("accepted_backends must not be empty")
        if isinstance(self.minimum_ram_bytes, bool) or self.minimum_ram_bytes <= 0:
            raise ValueError("minimum_ram_bytes must be positive")
        if (
            isinstance(self.minimum_free_disk_bytes, bool)
            or self.minimum_free_disk_bytes <= 0
        ):
            raise ValueError("minimum_free_disk_bytes must be positive")

    def limits_for(self, domain: IndexDomain) -> SupportProfileLimits:
        """Return independent limits for a closed domain."""
        if domain is IndexDomain.CODE:
            return self.code
        if domain is IndexDomain.DOCUMENT:
            return self.document
        raise AssertionError(f"unhandled index domain: {domain!r}")


_GIB: Final = 1024**3

_PROFILES: Final = MappingProxyType(
    {
        "managed-service": IndexSupportProfile(
            name="managed-service",
            accepted_backends=frozenset({"server"}),
            minimum_ram_bytes=16 * _GIB,
            minimum_free_disk_bytes=64 * _GIB,
            code=SupportProfileLimits(
                source_files=500_000,
                source_bytes=128 * _GIB,
                generated_chunks=5_000_000,
                weighted_bytes=512 * _GIB,
                extracted_bytes=128 * _GIB,
                queue_bytes=512 * 1024**2,
                rss_bytes=16 * _GIB,
                cuda_bytes=12 * _GIB,
            ),
            document=SupportProfileLimits(
                source_files=100_000,
                source_bytes=512 * _GIB,
                generated_chunks=5_000_000,
                weighted_bytes=1024 * _GIB,
                extracted_bytes=1024 * _GIB,
                queue_bytes=512 * 1024**2,
                rss_bytes=16 * _GIB,
                cuda_bytes=12 * _GIB,
            ),
        ),
        "embedded-local": IndexSupportProfile(
            name="embedded-local",
            accepted_backends=frozenset({"local", "server"}),
            minimum_ram_bytes=8 * _GIB,
            minimum_free_disk_bytes=16 * _GIB,
            code=SupportProfileLimits(
                source_files=50_000,
                source_bytes=16 * _GIB,
                generated_chunks=500_000,
                weighted_bytes=64 * _GIB,
                extracted_bytes=16 * _GIB,
                queue_bytes=128 * 1024**2,
                rss_bytes=8 * _GIB,
                cuda_bytes=6 * _GIB,
            ),
            document=SupportProfileLimits(
                source_files=10_000,
                source_bytes=64 * _GIB,
                generated_chunks=500_000,
                weighted_bytes=128 * _GIB,
                extracted_bytes=128 * _GIB,
                queue_bytes=128 * 1024**2,
                rss_bytes=8 * _GIB,
                cuda_bytes=6 * _GIB,
            ),
        ),
    }
)


def get_index_support_profile(name: str) -> IndexSupportProfile:
    """Resolve a configured profile name or fail closed."""
    try:
        return _PROFILES[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(_PROFILES))
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"unknown index support profile {name!r}; expected one of {allowed}",
        ) from exc


def index_support_profile_status(name: str) -> dict[str, object]:
    """Return the active profile as a stable, JSON-safe status descriptor."""
    profile = get_index_support_profile(name)

    def _limits(limits: SupportProfileLimits) -> dict[str, int]:
        return {
            "source_files": limits.source_files,
            "source_bytes": limits.source_bytes,
            "generated_chunks": limits.generated_chunks,
            "weighted_bytes": limits.weighted_bytes,
            "extracted_bytes": limits.extracted_bytes,
            "queue_bytes": limits.queue_bytes,
            "rss_bytes": limits.rss_bytes,
            "cuda_bytes": limits.cuda_bytes,
        }

    return {
        "name": profile.name,
        "accepted_backends": sorted(profile.accepted_backends),
        "minimum_ram_bytes": profile.minimum_ram_bytes,
        "minimum_free_disk_bytes": profile.minimum_free_disk_bytes,
        "domains": {
            IndexDomain.CODE.value: _limits(profile.code),
            IndexDomain.DOCUMENT.value: _limits(profile.document),
        },
    }


def _shortfall(reading: VolumeReading, required: int) -> str:
    """Render one volume's requirement, observation, and gap in units."""
    free = reading.free_bytes or 0
    return (
        f"{reading.describe()} has {human_bytes(free)} free; "
        f"{human_bytes(required)} required ({human_bytes(required - free)} short)"
    )


def _store_disk_refusal(profile: IndexSupportProfile, reading: VolumeReading) -> str:
    """Explain a store headroom refusal in units, at a location, with a way out.

    The requirement is a property of the vector store's volume, which is
    frequently not the volume holding the indexed tree. Naming the exact
    directory, drive, and role is what stops the refusal reading as a flat
    contradiction of what the operator's file manager shows.
    """
    from .config import EnvVar

    smaller = _smaller_disk_profile(profile)
    lines = [
        f"profile {profile.name!r}: "
        f"{_shortfall(reading, profile.minimum_free_disk_bytes)}.",
        f"Free space on that volume, or point {EnvVar.QDRANT_STORAGE_DIR.value} "
        f"at a volume with room.",
    ]
    if smaller is not None:
        lines.append(
            f"A smaller profile is available: set "
            f"{EnvVar.INDEX_SUPPORT_PROFILE.value}={smaller.name} "
            f"(needs {human_bytes(smaller.minimum_free_disk_bytes)})."
        )
    return " ".join(lines)


def _workspace_disk_refusal(reading: VolumeReading, required: int) -> str:
    """Explain a refusal on the volume holding the project's own data dir.

    Reported as its own condition rather than folded into the store's: the
    two targets are routinely on different volumes with wildly different
    requirements, and an operator told only "disk" would free space on
    whichever one they happened to think of.
    """
    return (
        f"the indexed project's own data dir cannot be written: "
        f"{_shortfall(reading, required)}. "
        f"Free space on that volume and retry."
    )


def _check_workspace_volume(
    store_volume: VolumeReading,
    workspace_volume: VolumeReading | None,
) -> None:
    """Refuse when the project's own data dir has no room for its bookkeeping.

    Skipped when both targets landed on the same volume: the store's
    requirement is strictly larger there, so it has already answered this
    question and a second report would only invite an operator to free
    space twice on one drive.
    """
    from ._store_writes import DISK_FLOOR_BYTES

    if workspace_volume is None or workspace_volume.free_bytes is None:
        return
    if workspace_volume.same_volume_as(store_volume):
        return
    if workspace_volume.free_bytes >= DISK_FLOOR_BYTES:
        return
    raise JobError(
        JobErrorKind.DISK_PREFLIGHT_FAILED,
        _workspace_disk_refusal(workspace_volume, DISK_FLOOR_BYTES),
    )


def _smaller_disk_profile(active: IndexSupportProfile) -> IndexSupportProfile | None:
    """Return the lowest-floor profile below *active*, or ``None`` if it is lowest.

    Offering the active profile back as the remediation is worse than
    offering nothing, so the suggestion is omitted when no profile has a
    lower disk floor.
    """
    lower = [
        candidate
        for candidate in _PROFILES.values()
        if candidate.minimum_free_disk_bytes < active.minimum_free_disk_bytes
    ]
    if not lower:
        return None
    return min(lower, key=lambda candidate: candidate.minimum_free_disk_bytes)


def validate_profile_admission(
    profile_name: str,
    domain: IndexDomain,
    measured: SupportMeasurement,
    *,
    backend: StorageBackend,
    available_ram_bytes: int,
    store_volume: VolumeReading,
    workspace_volume: VolumeReading | None = None,
) -> IndexSupportProfile:
    """Validate known host and corpus dimensions before mutable/GPU work.

    An index writes to two independent targets. ``store_volume`` is the
    vector store's, which carries the profile's headroom requirement and is
    frequently not the volume holding the indexed tree. ``workspace_volume``
    is the project's own data dir - the run ledger and index metadata -
    which needs only the small shared write floor. Each is checked and
    reported separately so a refusal names the target that is actually
    short.

    A ``None`` free figure means this process cannot see that volume (a
    remote store), and its check is skipped rather than decided against an
    unrelated number; the per-write floor still guards the run.
    """
    profile = get_index_support_profile(profile_name)
    if backend not in profile.accepted_backends:
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"profile {profile.name!r} does not support backend {backend!r}",
        )
    if available_ram_bytes < profile.minimum_ram_bytes:
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"profile {profile.name!r} requires "
            f"{human_bytes(profile.minimum_ram_bytes)} RAM; host reports "
            f"{human_bytes(available_ram_bytes)}",
        )
    store_free = store_volume.free_bytes
    if store_free is not None and store_free < profile.minimum_free_disk_bytes:
        raise JobError(
            JobErrorKind.DISK_PREFLIGHT_FAILED,
            _store_disk_refusal(profile, store_volume),
        )
    _check_workspace_volume(store_volume, workspace_volume)
    exceeded = profile.limits_for(domain).exceeded_by(measured)
    if exceeded is not None:
        dimension, actual, limit = exceeded
        raise JobError(
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
            f"{domain.value} {dimension} is {actual}; profile "
            f"{profile.name!r} permits {limit}",
        )
    return profile
