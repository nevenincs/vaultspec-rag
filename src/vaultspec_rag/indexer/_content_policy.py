"""Closed vocabulary for content ownership and index admission.

The types in this module are the stable, dependency-free boundary shared by
discovery, indexing, and service adapters.  They deliberately describe caller
intent and policy outcomes without assigning meaning to repository layout or
using parser capability as an admission rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "AdmissionDisposition",
    "AdmissionPolicyError",
    "AdmissionReason",
    "ContentKind",
    "ContentRoute",
    "RootContentPolicy",
    "SourceProfileVersion",
]


class AdmissionPolicyError(ValueError):
    """Raised when explicit routes assign conflicting content ownership."""


class ContentKind(StrEnum):
    """Closed set of independently owned index content domains."""

    CODE = "code"
    DOCUMENT = "document"


class AdmissionReason(StrEnum):
    """Stable reason tokens produced by content-policy classification."""

    EXPLICIT_ROUTE = "explicit_route"
    SOURCE_PROFILE = "source_profile"
    IGNORED = "ignored"
    NOT_ROUTED = "not_routed"
    SOURCE_PROFILE_EXCLUDED = "source_profile_excluded"
    SOURCE_TOO_LARGE = "source_too_large"
    SOURCE_BINARY = "source_binary"
    SOURCE_PROBE_FAILED = "source_probe_failed"


class SourceProfileVersion(StrEnum):
    """Public, versioned source-admission profiles selectable by callers."""

    CONVENTIONAL_V1 = "conventional-v1"
    EXPLICIT_ONLY_V1 = "explicit-only-v1"


@dataclass(frozen=True, slots=True)
class ContentRoute:
    """One compiled caller route; tuple position defines its precedence."""

    pattern: str
    kind: ContentKind

    def __post_init__(self) -> None:
        if not self.pattern.strip():
            raise ValueError("content route pattern must not be empty")
        if "\0" in self.pattern:
            raise ValueError("content route pattern must not contain NUL")


@dataclass(frozen=True, slots=True)
class RootContentPolicy:
    """Immutable root routing and source-admission selection.

    Routes are evaluated in their declared tuple order. This contract owns
    content membership only; optional transforms are resolved independently.
    """

    source_profile: SourceProfileVersion
    routes: tuple[ContentRoute, ...] = ()

    def __post_init__(self) -> None:
        owners: dict[str, ContentKind] = {}
        for route in self.routes:
            existing = owners.setdefault(route.pattern, route.kind)
            if existing is not route.kind:
                raise AdmissionPolicyError(
                    f"content route {route.pattern!r} targets both "
                    f"{existing.value!r} and {route.kind.value!r}"
                )


@dataclass(frozen=True, slots=True)
class AdmissionDisposition:
    """Immutable ownership and admission outcome for one project-relative path.

    A policy rejection may retain ``kind`` so reconciliation can act in the
    correct content domain.  An admitted path must always have exactly one
    owner; routing conflicts are configuration errors resolved before a
    disposition is created.
    """

    kind: ContentKind | None
    admitted: bool
    reason: AdmissionReason

    def __post_init__(self) -> None:
        if self.admitted and self.kind is None:
            raise ValueError("an admitted path must have a content kind")
