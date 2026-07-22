"""Named, closed resource and corpus support profiles for index admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from ._job_errors import JobError, JobErrorKind

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

    def __post_init__(self) -> None:
        for name in (
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
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

    def __post_init__(self) -> None:
        for name in (
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def exceeded_by(self, measured: SupportMeasurement) -> tuple[str, int, int] | None:
        """Return the first exceeded dimension in stable diagnostic order."""
        for name in (
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
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
            ),
            document=SupportProfileLimits(
                source_files=100_000,
                source_bytes=512 * _GIB,
                generated_chunks=5_000_000,
                weighted_bytes=1024 * _GIB,
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
            ),
            document=SupportProfileLimits(
                source_files=10_000,
                source_bytes=64 * _GIB,
                generated_chunks=500_000,
                weighted_bytes=128 * _GIB,
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


def validate_profile_admission(
    profile_name: str,
    domain: IndexDomain,
    measured: SupportMeasurement,
    *,
    backend: StorageBackend,
    available_ram_bytes: int,
    free_disk_bytes: int,
) -> IndexSupportProfile:
    """Validate known host and corpus dimensions before mutable/GPU work."""
    profile = get_index_support_profile(profile_name)
    if backend not in profile.accepted_backends:
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"profile {profile.name!r} does not support backend {backend!r}",
        )
    if available_ram_bytes < profile.minimum_ram_bytes:
        raise JobError(
            JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET,
            f"profile {profile.name!r} requires {profile.minimum_ram_bytes} RAM bytes; "
            f"host reports {available_ram_bytes}",
        )
    if free_disk_bytes < profile.minimum_free_disk_bytes:
        raise JobError(
            JobErrorKind.DISK_PREFLIGHT_FAILED,
            f"profile {profile.name!r} requires {profile.minimum_free_disk_bytes} "
            f"free disk bytes; storage reports {free_disk_bytes}",
        )
    exceeded = profile.limits_for(domain).exceeded_by(measured)
    if exceeded is not None:
        dimension, actual, limit = exceeded
        raise JobError(
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
            f"{domain.value} {dimension} is {actual}; profile "
            f"{profile.name!r} permits {limit}",
        )
    return profile
