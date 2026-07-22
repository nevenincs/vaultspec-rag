"""Closed vocabulary for content ownership and index admission.

The types in this module are the stable, dependency-free boundary shared by
discovery, indexing, and service adapters.  They deliberately describe caller
intent and policy outcomes without assigning meaning to repository layout or
using parser capability as an admission rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

__all__ = [
    "AdmissionDisposition",
    "AdmissionPolicyError",
    "AdmissionReason",
    "ClassifiedContent",
    "ContentKind",
    "ContentRoute",
    "RootContentPolicy",
    "SourceProfileVersion",
    "classify_content",
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


@dataclass(frozen=True, slots=True)
class ClassifiedContent:
    """One admission outcome plus parser capability chosen after admission."""

    disposition: AdmissionDisposition
    language: str | None = None
    grammar: str | None = None

    def __post_init__(self) -> None:
        if self.disposition.admitted and self.language is None:
            raise ValueError("admitted content must have a parser selection")
        if not self.disposition.admitted and (
            self.language is not None or self.grammar is not None
        ):
            raise ValueError("rejected content must not select a parser")


def _matched_explicit_kind(
    policy: RootContentPolicy,
    rel_path: str,
    transform_kind: ContentKind | None,
) -> ContentKind | None:
    matched = [
        route.kind
        for route in policy.routes
        if PurePosixPath(rel_path).full_match(route.pattern)
    ]
    if transform_kind is not None:
        matched.append(transform_kind)
    if not matched:
        return None
    owner = matched[0]
    if any(kind is not owner for kind in matched[1:]):
        raise AdmissionPolicyError(
            f"path {rel_path!r} matches conflicting explicit content targets"
        )
    return owner


def classify_content(
    *,
    rel_path: str,
    ignored: bool,
    policy: RootContentPolicy,
    transform_kind: ContentKind | None = None,
) -> ClassifiedContent:
    """Classify one path through the shared deterministic admission order."""
    from ._chunking import CONVENTIONAL_SOURCE_EXTENSIONS, select_parser

    if ignored:
        return ClassifiedContent(
            AdmissionDisposition(None, False, AdmissionReason.IGNORED)
        )

    explicit_kind = _matched_explicit_kind(policy, rel_path, transform_kind)
    suffix = PurePosixPath(rel_path).suffix.lower()
    if explicit_kind is not None:
        parser = select_parser(suffix)
        return ClassifiedContent(
            AdmissionDisposition(
                explicit_kind,
                True,
                AdmissionReason.EXPLICIT_ROUTE,
            ),
            parser.language,
            parser.grammar,
        )

    if policy.source_profile is SourceProfileVersion.EXPLICIT_ONLY_V1:
        return ClassifiedContent(
            AdmissionDisposition(None, False, AdmissionReason.NOT_ROUTED)
        )
    if suffix not in CONVENTIONAL_SOURCE_EXTENSIONS:
        return ClassifiedContent(
            AdmissionDisposition(
                ContentKind.CODE,
                False,
                AdmissionReason.SOURCE_PROFILE_EXCLUDED,
            )
        )

    parser = select_parser(suffix)
    return ClassifiedContent(
        AdmissionDisposition(ContentKind.CODE, True, AdmissionReason.SOURCE_PROFILE),
        parser.language,
        parser.grammar,
    )
