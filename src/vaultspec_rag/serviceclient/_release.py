"""Client/server release compatibility: one published datum, one shared verdict.

A daemon and the clients that drive it are separate installs that drift
independently - a globally installed tool alongside a project-local
environment, a machine with several checkouts, or an upgrade that replaces the
client while the previous daemon keeps serving. None of the wire payloads
carried the package release, so a client had neither the datum to compare nor
a place to compare it; it attached to a foreign build and drove it silently.

This module owns both halves. The daemon stamps its own release onto every
surface that already identifies it, and every entry point renders the verdict
this module returns rather than deriving its own, so the CLI and the MCP can
never disagree about what a given pairing means.

The release verdict is a signal, not a gate. A client that refused to talk to
a differently-released daemon could not stop it either, leaving an operator no
way out of the very mismatch being reported; the honest move is to report the
pairing and let the operator act. Compatibility of the discovery *file shape*
is a separate and stricter question - a shape this build cannot parse is
refused outright where that file is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

#: Verdict vocabulary. ``unknown`` is deliberately distinct from ``match``: a
#: daemon predating the published field cannot be confirmed compatible, and
#: reporting an unconfirmed pairing as agreement is the exact failure this
#: module exists to remove. An unverifiable pairing is never a pass.
RELEASE_MATCH = "match"
RELEASE_MISMATCH = "mismatch"
RELEASE_UNKNOWN = "unknown"

#: The wire field carrying the package release on ``/health``, ``/readiness``
#: and the discovery file. Named apart from the two version-shaped fields that
#: already travel those surfaces and mean something else: ``version`` is the
#: discovery-file schema discriminator, and ``schema_version`` is the storage
#: shape. A third spelling of "version" would be read as one of those.
RELEASE_FIELD = "package_version"

__all__ = [
    "RELEASE_FIELD",
    "RELEASE_MATCH",
    "RELEASE_MISMATCH",
    "RELEASE_UNKNOWN",
    "ReleaseCompatibility",
    "compare_release",
    "local_release",
    "payload_release",
    "payload_release_compatibility",
]

@cache
def local_release() -> str:
    """Return the package release of the process making this call.

    Neutral by name because both sides use it: the daemon stamps its own
    release onto the payloads it publishes, and a client compares that stamp
    against its own.

    Cached, and resolved on first call rather than at import: reading installed
    package metadata costs most of this package's import budget, and every
    spawn worker re-imports the chain.
    """
    from vaultspec_rag import __version__

    return __version__


@dataclass(frozen=True, slots=True)
class ReleaseCompatibility:
    """One verdict on a client/daemon release pairing, with both releases.

    Both sides travel with the verdict so an operator surface never has to
    report a bare "mismatch" it cannot substantiate - naming the two releases
    is what turns the signal into an action.
    """

    verdict: str
    client: str
    service: str | None = None

    @property
    def confirmed(self) -> bool:
        """Whether the daemon published a release this client could read."""
        return self.verdict != RELEASE_UNKNOWN

    @property
    def is_mismatch(self) -> bool:
        """Whether both releases are known and disagree."""
        return self.verdict == RELEASE_MISMATCH

    def summary(self) -> str:
        """Render a one-line operator-facing account of this pairing."""
        if self.verdict == RELEASE_MATCH:
            return f"client and service both on {self.client}"
        if self.verdict == RELEASE_MISMATCH:
            return (
                f"client on {self.client}, service on {self.service}; "
                "restart the service so both run the same release"
            )
        return (
            f"client on {self.client}, service release not reported; "
            "the service predates the release signal or is a foreign build"
        )


def compare_release(
    service_release: object,
    *,
    client: str | None = None,
) -> ReleaseCompatibility:
    """Return the verdict for *service_release* against this build.

    A non-string or empty service release is treated as unreported rather than
    as a mismatch: the distinction an operator needs is "confirmed different"
    against "could not be confirmed", and collapsing the two would report a
    garbled field with the same words as a genuine version skew.
    """
    mine = client if client is not None else local_release()
    if not isinstance(service_release, str) or not service_release:
        return ReleaseCompatibility(RELEASE_UNKNOWN, mine, None)
    verdict = RELEASE_MATCH if service_release == mine else RELEASE_MISMATCH
    return ReleaseCompatibility(verdict, mine, service_release)


def payload_release(payload: object) -> str | None:
    """Return the release stamped on a health/readiness/discovery payload."""
    if not isinstance(payload, dict):
        return None
    value: object = payload.get(RELEASE_FIELD)
    return value if isinstance(value, str) and value else None


def payload_release_compatibility(
    payload: object,
    *,
    client: str | None = None,
) -> ReleaseCompatibility:
    """Return the verdict for whatever release *payload* carries."""
    return compare_release(payload_release(payload), client=client)
