"""Closed public source-domain vocabulary and strict parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, get_args

__all__ = [
    "INDEX_SOURCES",
    "IndexSource",
    "PublicSourceType",
    "SourceTypeParseError",
    "parse_source_type",
    "unsupported_feedback_envelope",
]


class PublicSourceType(StrEnum):
    """Canonical source selections exposed through public adapters."""

    VAULT = "vault"
    CODE = "code"
    DOCUMENT = "document"
    COMBINED = "combined"


_ALIASES: Final = MappingProxyType(
    {
        "codebase": PublicSourceType.CODE,
        "docs": PublicSourceType.VAULT,
        "all": PublicSourceType.COMBINED,
    }
)


#: The concrete index sources - every PublicSourceType except COMBINED, which
#: names a fan-out rather than a corpus. Eight sites wrote this triple out,
#: one of them already declaring it under this name inside the server package,
#: where the store and the CLI could not import it without inverting the
#: layering. A plain alias, not a ``type`` statement, so Typer and Pydantic can
#: both resolve it.
IndexSource = Literal["vault", "code", "document"]

#: The same vocabulary at runtime, mechanically pulled out of the Literal
#: above with ``get_args`` rather than re-declared. A hand-written tuple next
#: to a hand-written Literal is two spellings of one fact: nothing stops them
#: naming different sources, and a membership test against the tuple then
#: guards a field typed by the Literal without either noticing the other
#: moved. Deriving the tuple from the Literal removes that seam entirely -
#: there is only one spelling left to edit.
INDEX_SOURCES: tuple[str, ...] = get_args(IndexSource)

#: ``IndexSource`` itself is still hand-written, because a ``Literal`` cannot
#: be computed from ``StrEnum`` members at a level a type checker honours.
#: This is the other half of the pair the Literal cannot self-check: catch it
#: loudly at import instead of leaving it to silently disagree.
_NON_COMBINED_SOURCES = {
    member.value
    for member in PublicSourceType
    if member is not PublicSourceType.COMBINED
}
if set(INDEX_SOURCES) != _NON_COMBINED_SOURCES:
    _drift_message = (
        "IndexSource has drifted from PublicSourceType: update the Literal in "
        "_source_types.py to match every non-combined PublicSourceType member"
    )
    raise RuntimeError(_drift_message)


@dataclass(frozen=True, slots=True)
class SourceTypeParseError(ValueError):
    """Structured rejection for an unknown or ill-typed source selection."""

    received: object
    aliases_allowed: bool

    @property
    def allowed(self) -> tuple[str, ...]:
        """Return the stable canonical choices."""
        return tuple(item.value for item in PublicSourceType)

    @property
    def error_kind(self) -> str:
        """Return the stable adapter-facing error kind."""
        return "unknown_source_type"

    def as_payload(self) -> dict[str, object]:
        """Return a transport-safe error representation."""
        return {
            "error_kind": self.error_kind,
            "received": self.received,
            "allowed": list(self.allowed),
            "aliases_allowed": self.aliases_allowed,
        }

    def as_error_envelope(self) -> dict[str, object]:
        """Return the failure envelope every adapter reports this rejection as.

        Five call sites built this by hand - two HTTP routes and three service
        client calls - each spreading :meth:`as_payload` into the same three
        keys. The exception already knows its kind and how it reads; what it
        did not own was how it is reported, so every new caller had to be told
        by example, and a caller told by a stale example reports a shape the
        others do not.
        """
        return {
            "ok": False,
            "error": self.error_kind,
            "message": str(self),
            **self.as_payload(),
        }

    def __str__(self) -> str:
        choices = ", ".join(repr(value) for value in self.allowed)
        return f"unknown source type {self.received!r}; expected one of {choices}"


def parse_source_type(
    value: object,
    *,
    allow_aliases: bool = False,
) -> PublicSourceType:
    """Parse one source selection without coercion or permissive fallback.

    Compatibility aliases are accepted only when the caller opts in, keeping
    canonical service contracts closed while allowing legacy CLI spellings at
    their existing boundary.
    """
    if isinstance(value, PublicSourceType):
        return value
    if isinstance(value, str):
        try:
            return PublicSourceType(value)
        except ValueError:
            if allow_aliases:
                resolved = _ALIASES.get(value)
                if resolved is not None:
                    return resolved
    raise SourceTypeParseError(value, allow_aliases)


#: Sources whose results carry no cross-collection point identity, so feedback
#: naming specific points cannot be resolved against them.
_FEEDBACK_UNSUPPORTED: Final = frozenset(
    {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}
)


def unsupported_feedback_envelope(
    source: PublicSourceType,
    *,
    has_point_ids: bool,
) -> dict[str, object] | None:
    """Return the refusal envelope for point-id feedback, or ``None`` to allow.

    The HTTP route and the service client each carried this: the same set of
    sources, the same "does the caller name any points" test, and the same
    three-key envelope down to the error token. The client builds it locally to
    refuse without a round trip, which is worth doing and is exactly what makes
    the copy dangerous - the two are a request apart, so a server-side change
    to the rule or the wording leaves the client refusing on the old terms and
    nothing observes the disagreement.

    Args:
        source: The already-parsed search source.
        has_point_ids: Whether the caller named any like or unlike ids.

    Returns:
        The refusal envelope, or ``None`` when the request is allowed. Callers
        over HTTP wrap the envelope in their own 400; the client returns it
        directly, which is the only difference the two ever had.
    """
    if not has_point_ids or source not in _FEEDBACK_UNSUPPORTED:
        return None
    return {
        "ok": False,
        "error": "unsupported_feedback_for_search_type",
        "message": (
            f"feedback point ids are not supported for {source.value} "
            "search; omit like_ids and unlike_ids"
        ),
    }
