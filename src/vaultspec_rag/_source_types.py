"""Closed public source-domain vocabulary and strict parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "PublicSourceType",
    "SourceTypeParseError",
    "parse_source_type",
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
