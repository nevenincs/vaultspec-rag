"""Closed per-file indexing outcomes and convergence semantics.

Hash evidence is deliberately separate from successful convergence. A file
that failed extraction, decoding, or chunking remains visible pending work
even when its source bytes were read and hashed successfully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from .._job_errors import JobErrorKind
from ._content_policy import AdmissionDisposition, AdmissionReason, ContentKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = [
    "FileState",
    "FileStateKind",
    "iter_publishable_states",
    "validate_rel_path",
]


def validate_rel_path(rel_path: str) -> None:
    """Require canonical project-relative POSIX path syntax.

    Raises:
        ValueError: When *rel_path* is empty, ``.``, absolute, drive-qualified,
            contains a NUL or a backslash, walks upward through ``..``, or is
            not already in the form ``PurePosixPath`` renders it as.

    The nine clauses were written out twice - here as a row's own check and
    again in the ledger that persists those rows - and they had stayed
    identical, which is the only reason nothing had gone wrong yet. Four of
    them are containment checks: a backslash, a drive letter, an absolute
    path, and ``..`` are each a way of naming a file outside the project the
    row claims to describe. A copy that loses one clause does not fail; it
    accepts a path the other copy rejects, and which of the two runs depends
    on whether the value arrived as a row or through a ledger call.
    """
    path = PurePosixPath(rel_path)
    if (
        not rel_path
        or rel_path == "."
        or path.is_absolute()
        or PureWindowsPath(rel_path).drive
        or "\0" in rel_path
        or "\\" in rel_path
        or ".." in path.parts
        or path.as_posix() != rel_path
    ):
        raise ValueError("rel_path must be canonical project-relative POSIX syntax")


class FileStateKind(StrEnum):
    """Stable state vocabulary for one classified source path."""

    INDEXED = "indexed"
    POLICY_REJECTED = "policy_rejected"
    EXTRACT_RETRYABLE = "extract_retryable"
    EXTRACT_TERMINAL = "extract_terminal"
    DECODE_FAILED = "decode_failed"
    CHUNK_FAILED = "chunk_failed"


_FAILURE_ERROR_KIND: Final = MappingProxyType(
    {
        FileStateKind.EXTRACT_RETRYABLE: JobErrorKind.EXTRACTION_RETRYABLE,
        FileStateKind.EXTRACT_TERMINAL: JobErrorKind.EXTRACTION_TERMINAL,
        FileStateKind.DECODE_FAILED: JobErrorKind.DECODE_FAILED,
        FileStateKind.CHUNK_FAILED: JobErrorKind.CHUNK_FAILED,
    }
)

_REJECTION_REASONS: Final = frozenset(
    {
        AdmissionReason.IGNORED,
        AdmissionReason.NOT_ROUTED,
        AdmissionReason.SOURCE_PROFILE_EXCLUDED,
        AdmissionReason.SOURCE_TOO_LARGE,
        AdmissionReason.SOURCE_BINARY,
        AdmissionReason.SOURCE_EMPTY,
        AdmissionReason.SOURCE_PROBE_FAILED,
        AdmissionReason.PREPROCESS_SKIPPED,
    }
)

_CONFIG_STABLE_REJECTION_REASONS: Final = frozenset(
    {
        AdmissionReason.IGNORED,
        AdmissionReason.NOT_ROUTED,
        AdmissionReason.SOURCE_PROFILE_EXCLUDED,
    }
)

_EVIDENCE_STABLE_REJECTION_REASONS: Final = frozenset(
    {
        AdmissionReason.SOURCE_TOO_LARGE,
        AdmissionReason.SOURCE_BINARY,
        # Emptiness is stable only for the content that evidenced it. A file
        # caught mid-save reads empty and converges against the empty hash;
        # when the save lands the hash changes and it is classified again. A
        # genuinely empty file keeps that hash and stays converged, so neither
        # case retries forever.
        AdmissionReason.SOURCE_EMPTY,
        # A preprocessor's refusal is a fact about the bytes it read: the same
        # rule may parse the file happily once its content changes, so the
        # rejection may only be trusted against the hash that evidenced it.
        AdmissionReason.PREPROCESS_SKIPPED,
    }
)


def stable_rejection_reasons() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the reason tokens a rejection may converge on, by evidence class.

    ``FileState.stable_policy_rejection`` is the definition; this exposes the
    same two sets for callers that cannot evaluate a Python property - the
    ledger's finalization gate asks SQL the identical question and would
    otherwise hand-copy the membership, which is how it came to demand a hash
    for ``source_too_large`` and ``source_binary`` while letting
    ``source_empty`` through without one.

    Returns:
        ``(config_stable, evidence_stable)`` reason values. The first converge
        on their own; the second only alongside a content hash.
    """
    return (
        tuple(sorted(r.value for r in _CONFIG_STABLE_REJECTION_REASONS)),
        tuple(sorted(r.value for r in _EVIDENCE_STABLE_REJECTION_REASONS)),
    )


_CONTENT_HASH_RE = re.compile(r"[0-9a-f]{128}\Z")


@dataclass(frozen=True, slots=True)
class FileState:
    """One immutable file outcome suitable for ledgers and public summaries."""

    rel_path: str
    state: FileStateKind
    kind: ContentKind | None
    content_hash: str | None = None
    admission_reason: AdmissionReason | None = None
    error_kind: JobErrorKind | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        self._validate_enum_fields()
        self._validate_path()
        self._validate_scalar_evidence()
        self._validate_state_shape()

    def _validate_enum_fields(self) -> None:
        """Require every supplied discriminator to use its closed enum.

        These isinstance checks validate runtime-boundary data (rows rebuilt
        from the ledger's persisted state), so they are real guards despite the
        static field types; the reportUnnecessaryIsInstance false positive is
        suppressed with reason at each.
        """
        if not isinstance(self.state, FileStateKind):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("state must be a FileStateKind")
        if self.kind is not None and not isinstance(self.kind, ContentKind):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("kind must be a ContentKind when provided")
        if self.admission_reason is not None and not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            self.admission_reason, AdmissionReason
        ):
            raise TypeError("admission_reason must be an AdmissionReason when provided")
        if self.error_kind is not None and not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            self.error_kind, JobErrorKind
        ):
            raise TypeError("error_kind must be a JobErrorKind when provided")

    def _validate_path(self) -> None:
        """Require canonical project-relative POSIX path syntax."""
        validate_rel_path(self.rel_path)

    def _validate_scalar_evidence(self) -> None:
        """Validate optional hash and detail evidence independently of state."""
        if (
            self.content_hash is not None
            and _CONTENT_HASH_RE.fullmatch(self.content_hash) is None
        ):
            raise ValueError("content_hash must be a lowercase BLAKE2b-512 hex digest")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be empty when provided")

    def _validate_state_shape(self) -> None:
        """Dispatch the state-specific invariant set."""
        expected_error = _FAILURE_ERROR_KIND.get(self.state)
        if expected_error is not None:
            self._validate_failure(expected_error)
        elif self.state is FileStateKind.INDEXED:
            self._validate_indexed()
        else:
            self._validate_policy_rejection()

    def _validate_failure(self, expected_error: JobErrorKind) -> None:
        if self.kind is None:
            raise ValueError("a failed admitted file must retain its content kind")
        if self.error_kind is not expected_error:
            raise ValueError(
                f"{self.state.value} requires error kind {expected_error.value}"
            )
        if self.admission_reason is not None:
            raise ValueError("a processing failure must not carry a rejection reason")
        if self.detail is None:
            raise ValueError("a processing failure must carry non-empty detail")

    def _validate_indexed(self) -> None:
        if self.kind is None:
            raise ValueError("an indexed file must retain its content kind")
        if self.content_hash is None:
            raise ValueError("an indexed file must carry its content hash")
        if self.admission_reason is not None or self.error_kind is not None:
            raise ValueError(
                "an indexed file must not carry failure or rejection state"
            )
        if self.detail is not None:
            raise ValueError("an indexed file must not carry failure detail")

    def _validate_policy_rejection(self) -> None:
        if self.state is not FileStateKind.POLICY_REJECTED:
            raise ValueError(f"unknown file state {self.state!r}")
        if self.admission_reason not in _REJECTION_REASONS:
            raise ValueError("a policy rejection requires a stable rejection reason")
        if self.error_kind is not None or self.detail is not None:
            raise ValueError(
                "a policy rejection must not carry processing failure state"
            )

    @property
    def converged(self) -> bool:
        """Return whether this outcome may certify the file generation."""
        return self.state is FileStateKind.INDEXED or self.stable_policy_rejection

    @property
    def stable_policy_rejection(self) -> bool:
        """Return whether rejection has enough stable evidence to converge."""
        if self.state is not FileStateKind.POLICY_REJECTED:
            return False
        if self.admission_reason in _CONFIG_STABLE_REJECTION_REASONS:
            return True
        return (
            self.admission_reason in _EVIDENCE_STABLE_REJECTION_REASONS
            and self.content_hash is not None
        )

    @property
    def retryable(self) -> bool:
        """Return whether this state intrinsically requires service retry."""
        return self.state is FileStateKind.EXTRACT_RETRYABLE

    @property
    def stable_reason(self) -> str:
        """Return one stable reason token for structured adapters."""
        if self.admission_reason is not None:
            return self.admission_reason.value
        if self.error_kind is not None:
            return self.error_kind.value
        return self.state.value

    @classmethod
    def indexed(
        cls,
        rel_path: str,
        kind: ContentKind,
        content_hash: str,
    ) -> FileState:
        """Build a successfully indexed state."""
        return cls(rel_path, FileStateKind.INDEXED, kind, content_hash)

    @classmethod
    def policy_rejected(
        cls,
        rel_path: str,
        disposition: AdmissionDisposition,
        *,
        content_hash: str | None = None,
    ) -> FileState:
        """Build a stable policy rejection from classifier output."""
        if disposition.admitted:
            raise ValueError("an admitted disposition is not a policy rejection")
        return cls(
            rel_path,
            FileStateKind.POLICY_REJECTED,
            disposition.kind,
            content_hash,
            disposition.reason,
        )

    @classmethod
    def failed(
        cls,
        rel_path: str,
        state: FileStateKind,
        kind: ContentKind,
        detail: str,
        *,
        content_hash: str | None = None,
    ) -> FileState:
        """Build an extraction, decode, or chunk failure state."""
        error_kind = _FAILURE_ERROR_KIND.get(state)
        if error_kind is None:
            raise ValueError(f"{state.value} is not a processing failure state")
        return cls(
            rel_path=rel_path,
            state=state,
            kind=kind,
            content_hash=content_hash,
            error_kind=error_kind,
            detail=detail,
        )


def iter_publishable_states(
    states: Iterable[FileState],
) -> Iterator[tuple[str, str]]:
    """Validate ledger evidence and yield only the states a manifest records.

    Both publishers - the code sidecar and the document manifest - opened their
    write loop with the same five-statement gate: refuse an unconverged state,
    refuse one that breaks strict ascending path order, remember the path, skip
    anything not ``INDEXED``, and assert the survivor carries a hash. What each
    then did with the survivor is entirely different, which is why only the
    gate moves here and the loops stay where they are.

    The gate had already drifted where drift is cheapest to make and hardest to
    notice: the ordering refusal was two different sentences for one violation,
    so which explanation an operator got depended on whether the code index or
    the document index was publishing. The code side's wording is kept because
    it names both properties the check enforces - uniqueness and order.

    Args:
        states: Ledger evidence in the order the caller intends to publish it.

    Yields:
        ``(rel_path, content_hash)`` for each ``INDEXED`` state, in input
        order. The pair rather than the state, because the hash is
        ``str | None`` on the row and only this gate establishes it is
        present - yielding the row would move the assertion here and leave
        every caller re-narrowing a value already checked.

    Raises:
        ValueError: On the first unconverged state, or the first that is not
            strictly after its predecessor. Raised from inside the iteration,
            so a caller writing incrementally stops at the offending record
            rather than after publishing a partial manifest.
    """
    previous_path: str | None = None
    for state in states:
        if not state.converged:
            raise ValueError(
                f"cannot publish unresolved file state for {state.rel_path}"
            )
        if previous_path is not None and state.rel_path <= previous_path:
            raise ValueError(
                "ledger file states must be unique and ordered by relative path"
            )
        previous_path = state.rel_path
        if state.state is not FileStateKind.INDEXED:
            continue
        assert state.content_hash is not None
        yield state.rel_path, state.content_hash
