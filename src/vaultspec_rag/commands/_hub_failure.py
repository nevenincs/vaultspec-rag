"""Why a request to the model hub failed, as a closed vocabulary.

A failed fetch asks different things of an operator depending on its cause: a
hub that cannot be reached, a name the hub does not have, a full volume, a
certificate this host does not trust. The cause is read from the exception the
hub client raised, which has to happen in the process that caught it - an
exception does not cross a pipe - so the download child classifies its own
failure and reports the class, and the command that started it classifies what
it catches itself with the same function.
"""

from __future__ import annotations

import errno
import ssl
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["HubFailure", "classify_hub_failure", "first_line"]


class HubFailure(StrEnum):
    """The closed set of reasons a model download did not complete."""

    #: The hub could not be reached, or stopped answering part-way.
    UNREACHABLE = "unreachable"
    #: The hub answered that it has no such repository, revision or file.
    NOT_FOUND = "not_found"
    #: The volume holding the cache ran out of space.
    NO_SPACE = "no_space"
    #: The hub presented a certificate this host does not trust.
    UNTRUSTED_CERTIFICATE = "untrusted_certificate"
    #: Too little arrived for too long, and the download was stopped.
    STALLED = "stalled"
    #: The download process ended without saying how it went.
    DIED = "died"


def _causes(exc: BaseException) -> Iterator[BaseException]:
    """Yield *exc* and every exception it was raised from, outermost first."""
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        seen.add(id(link))
        yield link
        link = link.__cause__ or link.__context__


def classify_hub_failure(exc: BaseException) -> HubFailure:
    """Name why a hub request failed, so the remedy offered is the right one.

    The hub client wraps what it catches, so the two causes it cannot name
    itself are looked for anywhere in the chain: the operating system's own
    out-of-space error number, and the TLS library's verification error.
    """
    from huggingface_hub.errors import (
        RemoteEntryNotFoundError,
        RepositoryNotFoundError,
        RevisionNotFoundError,
    )

    chain = list(_causes(exc))
    if any(isinstance(link, OSError) and link.errno == errno.ENOSPC for link in chain):
        return HubFailure.NO_SPACE
    if any(isinstance(link, ssl.SSLCertVerificationError) for link in chain):
        return HubFailure.UNTRUSTED_CERTIFICATE
    # Only what the hub itself answered "not found" for. The client also has a
    # local not-found error, raised when it could not reach the hub and had no
    # snapshot to fall back on; that one is a network failure and is left to
    # the last line.
    if isinstance(
        exc, RepositoryNotFoundError | RevisionNotFoundError | RemoteEntryNotFoundError
    ):
        return HubFailure.NOT_FOUND
    return HubFailure.UNREACHABLE


def first_line(exc: BaseException) -> str:
    """Return the first non-empty line of *exc*'s message.

    The hub client's messages run to a paragraph with a request id and a URL;
    the first line is the statement.
    """
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return lines[0] if lines else type(exc).__name__
