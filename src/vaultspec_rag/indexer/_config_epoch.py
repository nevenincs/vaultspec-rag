"""Per-root config-epoch hashing for index-drift detection.

The indexers stamp a small set of reserved epoch keys into their meta sidecars
so that index-shaping configuration drift - ignore-file edits, preprocess-rule
edits, chunking-knob flips - becomes a dependable, self-healing reindex signal
even when the underlying file bytes never change. Two epoch classes exist,
because the two drift classes need different escalations:

* the *membership* epoch tracks which files are indexed (resolved ignore
  patterns and preprocess rule patterns); a mismatch is reconciled by the
  unscoped incremental's set arithmetic;
* the *content* epoch tracks how bytes become chunks (preprocess invocation
  fields, ``html_strip``, and ``vault_chunk_chars`` on the vault side); a
  mismatch invalidates stored vectors for unchanged bytes and needs a clean
  rebuild.

This module is stdlib-only (``hashlib`` / ``json``) so it stays importable from
the CPU-only spawn chunk-worker chain without loading torch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..config import PreprocessMode
    from ._content_policy import ContentKind, RootContentPolicy
    from ._preprocess_config import PreprocessRule
    from ._resolved_policy import ResolvedPreprocessRule

__all__ = [
    "ContentKindFingerprints",
    "NormalizedPolicyFingerprints",
    "PerKindPolicyFingerprints",
    "code_content_epoch",
    "code_membership_epoch",
    "resolved_policy_fingerprints",
    "vault_content_epoch",
]

RAW_CHUNK_SEMANTICS_VERSION = 1
PARSER_CAPABILITY_VERSION = 1


@dataclass(frozen=True, slots=True)
class ContentKindFingerprints:
    """Membership and byte-semantics identities for one content kind."""

    persistent_membership: str
    operation_membership: str
    content: str

    @property
    def membership(self) -> str:
        """Return the exact operation membership identity."""
        return self.operation_membership


@dataclass(frozen=True, slots=True)
class PerKindPolicyFingerprints:
    """Closed per-kind fingerprint projection."""

    code: ContentKindFingerprints
    document: ContentKindFingerprints

    def for_kind(self, kind: ContentKind) -> ContentKindFingerprints:
        """Return fingerprints for a closed content-kind token."""
        from ._content_policy import ContentKind

        if not isinstance(kind, ContentKind):
            raise TypeError("kind must be a ContentKind")
        if kind is ContentKind.CODE:
            return self.code
        return self.document


@dataclass(frozen=True, slots=True)
class NormalizedPolicyFingerprints:
    """Stable aggregate and per-kind policy identities."""

    persistent_membership: str
    operation_membership: str
    content: str
    execution: str
    snapshot: str
    per_kind: PerKindPolicyFingerprints

    @property
    def membership(self) -> str:
        """Return the exact operation membership identity."""
        return self.operation_membership


def _digest(payload: object) -> str:
    """Return the blake2b hex digest of a canonically-serialized payload.

    Canonicalization pins key order (``sort_keys``) and a compact separator set
    so that a semantically-identical payload always yields the same digest. TOML
    option values that JSON cannot represent natively (e.g. datetimes) degrade
    to their string form rather than raising.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.blake2b(canonical.encode("utf-8")).hexdigest()


def _preprocess_patterns(rules: Sequence[PreprocessRule]) -> list[str]:
    """Return the rule patterns in resolved-precedence order."""
    return [rule.pattern for rule in rules]


def resolved_policy_fingerprints(
    *,
    policy_schema_version: int,
    content_policy: RootContentPolicy,
    gitignore_patterns: Sequence[str],
    vaultragignore_patterns: Sequence[str],
    extra_excludes: Sequence[str],
    preprocess_schema_version: int,
    preprocess_rules: Sequence[ResolvedPreprocessRule],
    decoder_encoding: str,
    decoder_errors: str,
    normalize_newlines: bool,
    execution_mode: PreprocessMode,
    html_strip: bool,
    max_emitted_bytes: int,
) -> NormalizedPolicyFingerprints:
    """Hash a resolved policy without depending on object identity.

    Ordered rules and ignores retain semantic order. Ephemeral excludes shape
    the operation identity without changing the persistent-membership digest
    used by durable compatibility adapters.
    """
    persistent_membership_payload = {
        "version": policy_schema_version,
        "source_profile": content_policy.source_profile.value,
        "routes": [
            {"pattern": route.pattern, "target": route.kind.value}
            for route in content_policy.routes
        ],
        "gitignore": list(gitignore_patterns),
        "vaultragignore": list(vaultragignore_patterns),
        "preprocess_schema_version": preprocess_schema_version,
        "preprocess": [
            {
                "pattern": rule.pattern,
                "target": rule.target.value,
                "priority": rule.priority,
                "order": rule.order,
            }
            for rule in preprocess_rules
        ],
    }
    operation_membership_payload = {
        **persistent_membership_payload,
        "extra_excludes": list(extra_excludes),
    }
    content_payload = {
        "version": policy_schema_version,
        "raw_chunk_semantics_version": RAW_CHUNK_SEMANTICS_VERSION,
        "parser_capability_version": PARSER_CAPABILITY_VERSION,
        "preprocess_schema_version": preprocess_schema_version,
        "decoder": {
            "encoding": decoder_encoding,
            "errors": decoder_errors,
            "normalize_newlines": normalize_newlines,
        },
        "html_strip": bool(html_strip),
        "max_emitted_bytes": int(max_emitted_bytes),
        "preprocess": [
            {
                "pattern": rule.pattern,
                "command": rule.command,
                "entry_point": rule.entry_point,
                "target": rule.target.value,
                "extractor_version": rule.extractor_version,
                "on_error": rule.on_error,
                "timeout_s": rule.timeout_s,
                "options": rule.options,
                "priority": rule.priority,
                "order": rule.order,
                "batch": rule.batch,
                "path_independent": rule.path_independent,
                "max_source_bytes": rule.max_source_bytes,
            }
            for rule in preprocess_rules
        ],
    }
    persistent_membership = _digest(persistent_membership_payload)
    operation_membership = _digest(operation_membership_payload)
    content = _digest(content_payload)
    execution = _digest(
        {"version": policy_schema_version, "preprocess_mode": execution_mode}
    )
    per_kind = _per_kind_fingerprints(
        policy_schema_version=policy_schema_version,
        persistent_membership_payload=persistent_membership_payload,
        operation_membership_payload=operation_membership_payload,
        content_payload=content_payload,
        preprocess_rules=preprocess_rules,
    )
    snapshot = _digest(
        {
            "version": policy_schema_version,
            "operation_membership": operation_membership,
            "content": content,
            "execution": execution,
            "per_kind": {
                "code": {
                    "membership": per_kind.code.operation_membership,
                    "content": per_kind.code.content,
                },
                "document": {
                    "membership": per_kind.document.operation_membership,
                    "content": per_kind.document.content,
                },
            },
        }
    )
    return NormalizedPolicyFingerprints(
        persistent_membership=persistent_membership,
        operation_membership=operation_membership,
        content=content,
        execution=execution,
        snapshot=snapshot,
        per_kind=per_kind,
    )


def _per_kind_fingerprints(
    *,
    policy_schema_version: int,
    persistent_membership_payload: Mapping[str, object],
    operation_membership_payload: Mapping[str, object],
    content_payload: Mapping[str, object],
    preprocess_rules: Sequence[ResolvedPreprocessRule],
) -> PerKindPolicyFingerprints:
    """Derive independent kind identities from canonical aggregate payloads."""
    from ._content_policy import ContentKind

    by_kind: dict[ContentKind, ContentKindFingerprints] = {}
    for kind in ContentKind:
        persistent_payload = {
            **persistent_membership_payload,
            "kind": kind.value,
        }
        operation_payload = {
            **operation_membership_payload,
            "kind": kind.value,
        }
        rules = [rule for rule in preprocess_rules if rule.target is kind]
        kind_content_payload = {
            **content_payload,
            "kind": kind.value,
            "max_emitted_bytes": (
                content_payload["max_emitted_bytes"] if rules else None
            ),
            "preprocess": [
                {
                    "pattern": rule.pattern,
                    "command": rule.command,
                    "entry_point": rule.entry_point,
                    "target": rule.target.value,
                    "extractor_version": rule.extractor_version,
                    "on_error": rule.on_error,
                    "timeout_s": rule.timeout_s,
                    "options": rule.options,
                    "priority": rule.priority,
                    "order": rule.order,
                    "batch": rule.batch,
                    "path_independent": rule.path_independent,
                    "max_source_bytes": rule.max_source_bytes,
                }
                for rule in rules
            ],
        }
        by_kind[kind] = ContentKindFingerprints(
            persistent_membership=_digest(persistent_payload),
            operation_membership=_digest(operation_payload),
            content=_digest(
                {
                    "version": policy_schema_version,
                    **kind_content_payload,
                }
            ),
        )
    return PerKindPolicyFingerprints(
        code=by_kind[ContentKind.CODE],
        document=by_kind[ContentKind.DOCUMENT],
    )


def code_membership_epoch(
    *,
    gitignore_patterns: Sequence[str],
    vaultragignore_patterns: Sequence[str],
    preprocess_rules: Sequence[PreprocessRule],
) -> str:
    """Hash the inputs that decide which code files are indexed.

    Gitignore order remains significant because later rules and negations may
    override earlier rules. Directory traversal is already normalized by the
    collector. The ``.vaultragignore`` file patterns keep their file order, and CLI
    ``--exclude`` patterns are deliberately excluded upstream so the epoch does
    not thrash between an ephemeral CLI run and the resident service.
    """
    payload = {
        "gitignore": list(gitignore_patterns),
        "vaultragignore": list(vaultragignore_patterns),
        "preprocess_patterns": _preprocess_patterns(preprocess_rules),
    }
    return _digest(payload)


def code_content_epoch(
    *,
    preprocess_rules: Sequence[PreprocessRule],
    html_strip: bool,
    max_emitted_bytes: int,
) -> str:
    """Hash the inputs that decide how code bytes become chunks.

    Covers the preprocess invocation surface (command/entry_point, options,
    on_error, resolved timeout, and per-rule order), ``html_strip``, and the
    emitted-text cap - a cap change re-truncates any extraction that exceeds
    it, so it is content-shaping for unchanged bytes. A change here escalates
    to a clean rebuild.
    """
    payload = {
        "html_strip": bool(html_strip),
        "max_emitted_bytes": int(max_emitted_bytes),
        "preprocess": [
            {
                "command": rule.command,
                "entry_point": rule.entry_point,
                "on_error": rule.on_error,
                "timeout_s": rule.timeout_s,
                "options": dict(rule.options),
                "order": rule.order,
            }
            for rule in preprocess_rules
        ],
    }
    return _digest(payload)


def vault_content_epoch(*, vault_chunk_chars: int) -> str:
    """Hash the one content-shaping knob for the vault index.

    ``vault_chunk_chars`` sets the chunk boundary; changing it re-chunks every
    document with unchanged bytes, so a mismatch escalates to a clean rebuild.
    """
    return _digest({"vault_chunk_chars": int(vault_chunk_chars)})
