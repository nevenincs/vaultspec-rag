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
    "AdmissionReason",
    "ContentKind",
    "SourceProfileVersion",
]


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
