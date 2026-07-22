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
from typing import Final

from .._job_errors import JobErrorKind
from ._content_policy import AdmissionDisposition, AdmissionReason, ContentKind

__all__ = ["FileState", "FileStateKind"]


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
        AdmissionReason.SOURCE_PROBE_FAILED,
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
    }
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
        if not isinstance(self.state, FileStateKind):
            raise TypeError("state must be a FileStateKind")
        if self.kind is not None and not isinstance(self.kind, ContentKind):
            raise TypeError("kind must be a ContentKind when provided")
        if self.admission_reason is not None and not isinstance(
            self.admission_reason, AdmissionReason
        ):
            raise TypeError("admission_reason must be an AdmissionReason when provided")
        if self.error_kind is not None and not isinstance(
            self.error_kind, JobErrorKind
        ):
            raise TypeError("error_kind must be a JobErrorKind when provided")

        path = PurePosixPath(self.rel_path)
        if (
            not self.rel_path
            or self.rel_path == "."
            or path.is_absolute()
            or PureWindowsPath(self.rel_path).drive
            or "\0" in self.rel_path
            or "\\" in self.rel_path
            or ".." in path.parts
            or path.as_posix() != self.rel_path
        ):
            raise ValueError("rel_path must be canonical project-relative POSIX syntax")
        if (
            self.content_hash is not None
            and _CONTENT_HASH_RE.fullmatch(self.content_hash) is None
        ):
            raise ValueError("content_hash must be a lowercase BLAKE2b-512 hex digest")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be empty when provided")

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
