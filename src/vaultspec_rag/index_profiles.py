"""Named, closed resource and corpus support profiles for index admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from ._job_errors import JobError, JobErrorKind
from ._units import human_bytes

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ._store_writes import VolumeReading

__all__ = [
    "IndexDomain",
    "AdmissionEnvironment",
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
class AdmissionEnvironment:
    """Host and storage observations for one profile admission decision."""

    backend: StorageBackend
    available_ram_bytes: int
    store_volume: VolumeReading
    workspace_volume: VolumeReading | None = None


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

# The flat disk floor answers one question only: is this host plausibly
# provisioned to run a vector store at all. Whether a PARTICULAR run fits is
# answered by the per-run point estimate at the bulk-index pre-flight, which
# sizes the actual work instead of guessing at it.
#
# Derived from measurements rather than picked as a safe-feeling round number:
# a fresh namespace's three collections preallocate ~336 MiB each under the
# pinned segment geometry (~1.0 GiB); the shared write floor reserves 1.0 GiB
# of WAL and optimizer headroom; an ordinary indexed project measured 3.4 GiB
# for a 12,408-point namespace; and an optimizer pass on that data transiently
# inflates ~30% before it shrinks (~1.0 GiB). That totals ~6.4 GiB, rounded up
# for margin.
#
# The previous value was 64 GiB - roughly twenty times an ordinary project -
# which refused small incremental runs on hosts that had ample room for them,
# because it was answering the per-run question with a host-provisioning
# number.
_MANAGED_DISK_FLOOR: Final = 8 * _GIB

# The same derivation at this profile's scale. Its corpus caps are a tenth of
# managed-service's, so an ordinary project here is smaller (~1.7 GiB of data,
# ~0.5 GiB of optimizer inflation on it), and the shared write floor still
# reserves 1.0 GiB. The preallocation term stays: this profile accepts the
# SERVER backend as well as the local one, and only local mode preallocates
# nothing - a floor has to hold for every backend its profile admits, so it is
# derived against the costlier of the two (~1.0 GiB). That totals ~4.2 GiB,
# rounded up for margin.
#
# This must stay strictly below the managed floor. A ladder whose smaller
# profile demands more disk than its larger one is an incoherent contract, and
# it also silently breaks the refusal's fall-back suggestion, which can only
# offer a profile with a lower floor.
_EMBEDDED_DISK_FLOOR: Final = 5 * _GIB

_PROFILES: Final = MappingProxyType(
    {
        "managed-service": IndexSupportProfile(
            name="managed-service",
            accepted_backends=frozenset({"server"}),
            minimum_ram_bytes=16 * _GIB,
            minimum_free_disk_bytes=_MANAGED_DISK_FLOOR,
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
            minimum_free_disk_bytes=_EMBEDDED_DISK_FLOOR,
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


def _store_disk_refusal(
    profile: IndexSupportProfile,
    reading: VolumeReading,
    backend: StorageBackend,
) -> str:
    """Explain a store headroom refusal in units, at a location, with a way out.

    The requirement is a property of the vector store's volume, which is
    frequently not the volume holding the indexed tree. Naming the exact
    directory, drive, and role is what stops the refusal reading as a flat
    contradiction of what the operator's file manager shows.
    """
    from .config import EnvVar

    smaller = _smaller_disk_profile(profile, backend, _PROFILES.values())
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


def _smaller_disk_profile(
    active: IndexSupportProfile,
    backend: StorageBackend,
    candidates: Iterable[IndexSupportProfile],
) -> IndexSupportProfile | None:
    """Return the lowest-floor profile that would actually admit this caller.

    A suggestion must survive being taken. Two independent things disqualify
    a candidate: a floor that is not lower (offering the profile that just
    refused, or one that would refuse harder), and a profile that does not
    accept the backend in use - switching to it trades a disk refusal for a
    backend refusal, which is worse than saying nothing. ``None`` means no
    candidate clears both, and the caller omits the sentence entirely.

    ``candidates`` is a parameter rather than a read of the shipped profile
    table so the backend rule stays exercisable. No profile in the current
    table can trip it - the only lower-floor profile accepts both backends -
    and a rule that no test can make fail is one nobody can trust.
    """
    usable = [
        candidate
        for candidate in candidates
        if candidate.minimum_free_disk_bytes < active.minimum_free_disk_bytes
        and backend in candidate.accepted_backends
    ]
    if not usable:
        return None
    return min(usable, key=lambda candidate: candidate.minimum_free_disk_bytes)


def validate_profile_admission(
    profile_name: str,
    domain: IndexDomain,
    measured: SupportMeasurement,
    environment: AdmissionEnvironment,
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
    if environment.backend not in profile.accepted_backends:
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"profile {profile.name!r} does not support backend {environment.backend!r}",
        )
    if environment.available_ram_bytes < profile.minimum_ram_bytes:
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"profile {profile.name!r} requires "
            f"{human_bytes(profile.minimum_ram_bytes)} RAM; host reports "
                f"{human_bytes(environment.available_ram_bytes)}",
        )
    store_free = environment.store_volume.free_bytes
    if store_free is not None and store_free < profile.minimum_free_disk_bytes:
        raise JobError(
            JobErrorKind.DISK_PREFLIGHT_FAILED,
            _store_disk_refusal(profile, environment.store_volume, environment.backend),
        )
    _check_workspace_volume(environment.store_volume, environment.workspace_volume)
    exceeded = profile.limits_for(domain).exceeded_by(measured)
    if exceeded is not None:
        dimension, actual, limit = exceeded
        raise JobError(
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
            f"{domain.value} {dimension} is {actual}; profile "
            f"{profile.name!r} permits {limit}",
        )
    return profile
