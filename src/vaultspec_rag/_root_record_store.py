"""One versioned JSON file of per-root operator records in the status directory.

Operator intent about a root - consent to run its hooks, a stop of its
automatic updates - lives outside the repository so the repository cannot
vouch for itself, and is keyed by canonical root so two spellings of one
directory are one decision. Every such store has the same shape on disk::

    {"version": N, "roots": {"<canonical root key>": {...}}}

This module reads and writes that shape. It does not decide what a damaged
store means. Each store makes that call at its own site, because the safe
answer differs: a store that grants something reads damage as "nothing is
granted", while a store that withholds something has to read damage as
"cannot tell" rather than "nothing is withheld".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

from ._atomic_write import JsonWriteOptions, write_json_atomically

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

__all__ = [
    "RootRecordStoreError",
    "read_root_records",
    "write_root_records",
]


class RootRecordStoreError(OSError):
    """A store exists but could not be read as the expected version.

    Attributes:
        path: The store file.
        kind: ``unreadable`` when the bytes could not be read, ``malformed``
            when they were read and are not a store of the expected version.
        detail: The underlying reason, for the operator.
    """

    def __init__(
        self,
        path: pathlib.Path,
        kind: Literal["unreadable", "malformed"],
        detail: str,
    ) -> None:
        self.path = path
        self.kind = kind
        self.detail = detail
        super().__init__(f"store {path} is {kind} ({detail})")
        # Name the store as the file that failed, as any OSError would.
        self.filename = str(path)


def read_root_records(path: pathlib.Path, *, version: int) -> dict[object, object]:
    """Return the raw per-root records of the store at *path*.

    An absent store has no records. Each record is returned as read; the
    caller validates its own fields.

    Raises:
        RootRecordStoreError: The store exists but could not be read, or is
            not a well-formed store of *version*.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise RootRecordStoreError(path, "unreadable", str(exc)) from exc
    try:
        parsed: object = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise RootRecordStoreError(path, "malformed", str(exc)) from exc
    document = cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}
    roots = document.get("roots")
    if document.get("version") != version or not isinstance(roots, dict):
        raise RootRecordStoreError(path, "malformed", f"not a version {version} store")
    return cast("dict[object, object]", roots)


def write_root_records(
    path: pathlib.Path,
    records: Mapping[str, Mapping[str, object]],
    *,
    version: int,
) -> None:
    """Publish the whole store at *path*, owner-only and durable.

    Raises:
        OSError: The store could not be written.
    """
    write_json_atomically(
        path,
        {
            "version": version,
            "roots": {key: dict(record) for key, record in records.items()},
        },
        JsonWriteOptions(indent=2, sort_keys=True, durable=True, private=True),
    )
