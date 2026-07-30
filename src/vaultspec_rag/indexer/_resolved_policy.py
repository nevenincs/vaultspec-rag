"""Immutable, operation-scoped index policy resolution.

Resolve caller-owned routing, ignores, preprocessing, decoding, execution
mode, and normalized identities once. Discovery, workers, epochs, and
publication can then consume the same value without reopening configuration.
"""

from __future__ import annotations

import codecs
import datetime
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

import pathspec

from .. import _typed_fields
from ..config._settings import get_config
from . import _config_epoch, _ignore_specs
from ._content_policy import (
    ClassifiedContent,
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
    classify_content,
)
from ._preprocess_config import OnError, PreprocessRule, load_preprocess_rules
from ._preprocess_schema import UNIT_TEXT_MAX_CHARS, validate_max_emitted_bytes

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from ..config._types import PreprocessMode, RootContentPolicyConfig

__all__ = [
    "DecoderPolicy",
    "DocumentChunkingPolicy",
    "IndexPolicyResolutionOptions",
    "ResolvedIndexPolicy",
    "ResolvedPreprocessRule",
    "compile_content_policy",
    "preprocess_stale_note",
    "resolve_index_policy",
]

POLICY_SCHEMA_VERSION = 1

type _ScalarTag = Literal[
    "none",
    "bool",
    "int",
    "float",
    "str",
    "date",
    "time",
    "datetime",
]
type _ContainerTag = Literal["mapping", "list", "tuple"]
type CanonicalOption = tuple[_ScalarTag | _ContainerTag, object]

_CANONICAL_OPTION_TAGS: frozenset[str] = frozenset(
    {
        "none",
        "bool",
        "int",
        "float",
        "str",
        "date",
        "time",
        "datetime",
        "mapping",
        "list",
        "tuple",
    }
)


def _canonical_option(value: object) -> CanonicalOption:
    """Validate and narrow one canonical tagged option pair."""
    if not isinstance(value, tuple):
        raise TypeError("canonical preprocess option must be a tagged pair")
    pair = cast("tuple[object, ...]", value)  # ty: ignore[redundant-cast]
    if len(pair) != 2:
        raise TypeError("canonical preprocess option must be a tagged pair")
    if pair[0] not in _CANONICAL_OPTION_TAGS:
        raise TypeError(f"unknown canonical preprocess option tag {pair[0]!r}")
    return cast("CanonicalOption", pair)


def _mapping_payload(
    payload: object,
) -> tuple[tuple[str, CanonicalOption], ...]:
    """Validate and narrow a canonical mapping payload."""
    if not isinstance(payload, tuple):
        raise TypeError("canonical mapping payload must be a tuple")
    items: list[tuple[str, CanonicalOption]] = []
    for item in cast("tuple[object, ...]", payload):  # ty: ignore[redundant-cast]
        if not isinstance(item, tuple):
            raise TypeError("canonical mapping entries must be key-value pairs")
        pair = cast("tuple[object, ...]", item)  # ty: ignore[redundant-cast]
        if len(pair) != 2:
            raise TypeError("canonical mapping entries must be key-value pairs")
        key, nested = pair
        if not isinstance(key, str):
            raise TypeError("canonical mapping keys must be strings")
        items.append((key, _canonical_option(nested)))
    return tuple(items)


def _sequence_payload(payload: object) -> tuple[CanonicalOption, ...]:
    """Validate and narrow a canonical sequence payload."""
    if not isinstance(payload, tuple):
        raise TypeError("canonical sequence payload must be a tuple")
    return tuple(
        _canonical_option(nested)
        for nested in cast("tuple[object, ...]", payload)  # ty: ignore[redundant-cast]
    )


def _freeze_temporal(
    value: datetime.date | datetime.time,
) -> CanonicalOption:
    """Freeze one immutable TOML temporal scalar."""
    if isinstance(value, datetime.datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, datetime.date):
        return ("date", value.isoformat())
    return ("time", value.isoformat())


def _freeze_mapping(mapping: Mapping[object, object]) -> CanonicalOption:
    """Freeze one option mapping, rejecting any non-string key."""
    items: list[tuple[str, CanonicalOption]] = []
    for key, nested in mapping.items():
        if not isinstance(key, str):
            raise TypeError("preprocess option mapping keys must be strings")
        items.append((key, _freeze_option(nested)))
    return ("mapping", tuple(sorted(items)))


def _freeze_scalar(value: object) -> CanonicalOption:
    """Freeze one option scalar, rejecting any unsupported type."""
    scalar_tags: tuple[
        tuple[type[object], Literal["bool", "int", "float", "str"]], ...
    ] = (
        (bool, "bool"),
        (int, "int"),
        (float, "float"),
        (str, "str"),
    )
    for scalar_type, tag in scalar_tags:
        if isinstance(value, scalar_type):
            payload = repr(value) if tag == "float" else value
            return tag, payload
    raise TypeError(
        f"unsupported preprocess option type {type(value).__module__}."
        f"{type(value).__qualname__}"
    )


def _freeze_option(value: object) -> CanonicalOption:
    """Freeze one option with explicit type tags for hashing and pickling."""
    if value is None:
        return ("none", None)
    if isinstance(value, Mapping):
        return _freeze_mapping(cast("Mapping[object, object]", value))
    if isinstance(value, list):
        return (
            "list",
            tuple(_freeze_option(item) for item in cast("list[object]", value)),
        )
    if isinstance(value, tuple):
        return (
            "tuple",
            tuple(_freeze_option(item) for item in cast("tuple[object, ...]", value)),
        )
    if isinstance(value, (datetime.date, datetime.time)):
        return _freeze_temporal(value)
    return _freeze_scalar(value)


def _thaw_temporal(
    tag: Literal["date", "time", "datetime"],
    payload: object,
) -> datetime.date | datetime.time:
    """Validate and materialize one canonical temporal scalar."""
    if not isinstance(payload, str):
        raise TypeError(f"canonical {tag} payload must be a string")
    if tag == "date":
        return datetime.date.fromisoformat(payload)
    if tag == "time":
        return datetime.time.fromisoformat(payload)
    return datetime.datetime.fromisoformat(payload)


def _thaw_none(payload: object) -> None:
    if payload is not None:
        raise TypeError("canonical none payload must be None")
    return None


def _thaw_bool(payload: object) -> bool:
    return _typed_fields.required_bool(
        payload,
        on_invalid=lambda: TypeError("canonical bool payload must be a bool"),
    )


def _thaw_int(payload: object) -> int:
    return _typed_fields.required_int(
        payload,
        on_invalid=lambda: TypeError("canonical int payload must be an int"),
    )


def _thaw_str(payload: object) -> str:
    return _typed_fields.required_str(
        payload,
        allow_empty=True,
        on_invalid=lambda: TypeError("canonical str payload must be a string"),
    )


def _thaw_float(payload: object) -> float:
    return float(
        _typed_fields.required_str(
            payload,
            allow_empty=True,
            on_invalid=lambda: TypeError("canonical float payload must be a string"),
        )
    )


def _thaw_scalar(tag: _ScalarTag, payload: object) -> object:
    """Validate and materialize one canonical scalar."""
    if tag == "date" or tag == "time" or tag == "datetime":
        return _thaw_temporal(
            tag,
            payload,
        )
    scalar_thawers = {
        "none": _thaw_none,
        "bool": _thaw_bool,
        "int": _thaw_int,
        "str": _thaw_str,
        "float": _thaw_float,
    }
    try:
        return scalar_thawers[tag](payload)
    except KeyError:
        raise TypeError(f"unknown canonical preprocess option tag {tag!r}") from None


def _thaw_option(value: CanonicalOption) -> object:
    """Materialize a fresh invocation value from canonical immutable data."""
    tag, payload = value
    if tag == "mapping":
        items = _mapping_payload(payload)
        return {key: _thaw_option(nested) for key, nested in items}
    if tag in ("list", "tuple"):
        items = _sequence_payload(payload)
        values = tuple(_thaw_option(nested) for nested in items)
        return list(values) if tag == "list" else values
    return _thaw_scalar(tag, payload)


@dataclass(frozen=True, slots=True)
class DecoderPolicy:
    """Text-decoding semantics captured in a resolved policy snapshot."""

    encoding: str = "utf-8"
    errors: str = "strict"
    normalize_newlines: bool = True

    def __post_init__(self) -> None:
        encoding = codecs.lookup(self.encoding).name
        codecs.lookup_error(self.errors)
        if self.errors != "strict":
            raise ValueError("decoder errors policy must be 'strict'")
        object.__setattr__(self, "encoding", encoding)


@dataclass(frozen=True, slots=True)
class DocumentChunkingPolicy:
    """Document split budget captured in a resolved policy snapshot.

    ``chunk_chars`` derives on the production path from the dense model's
    token window multiplied by the configured chars-per-token ratio, and
    ``unit_text_max_chars`` mirrors the unit schema's declared text ceiling.
    The static defaults mirror the shipped configuration so a directly
    constructed snapshot stays valid.
    """

    chunk_chars: int = 2048 * 3
    chunk_overlap_chars: int = 256
    unit_text_max_chars: int = UNIT_TEXT_MAX_CHARS

    def __post_init__(self) -> None:
        for name in ("chunk_chars", "chunk_overlap_chars", "unit_text_max_chars"):
            value = cast("object", getattr(self, name))
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.chunk_overlap_chars >= self.chunk_chars:
            raise ValueError(
                "chunk_overlap_chars must be smaller than chunk_chars, got "
                f"overlap={self.chunk_overlap_chars}, budget={self.chunk_chars}"
            )


@dataclass(frozen=True, slots=True)
class IndexPolicyResolutionOptions:
    """Caller-owned values resolved into one immutable index policy."""

    content_policy: RootContentPolicy
    extra_excludes: Sequence[str] = ()
    decoder: DecoderPolicy | None = None
    execution_mode: PreprocessMode | None = None
    html_strip: bool | None = None
    max_emitted_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPreprocessRule:
    """Deeply immutable, precedence-resolved preprocessing semantics."""

    pattern: str
    command: str | None
    entry_point: str | None
    priority: int
    target: ContentKind
    extractor_version: str
    on_error: OnError
    timeout_s: float | None
    options: tuple[tuple[str, CanonicalOption], ...]
    order: int
    batch: bool
    path_independent: bool
    max_source_bytes: int | None

    def __post_init__(self) -> None:
        canonical: CanonicalOption = ("mapping", self.options)
        try:
            normalized = _freeze_option(_thaw_option(canonical))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid canonical preprocess options") from exc
        if normalized != canonical:
            raise ValueError("preprocess options are not canonically ordered")

    @classmethod
    def from_rule(cls, rule: PreprocessRule) -> ResolvedPreprocessRule:
        """Copy a mutable rule/options tree into canonical immutable data."""
        frozen_options = _freeze_option(rule.options)
        _tag, payload = frozen_options
        if _tag != "mapping":
            raise TypeError("preprocess rule options must be a mapping")
        return cls(
            pattern=rule.pattern,
            command=rule.command,
            entry_point=rule.entry_point,
            priority=rule.priority,
            target=rule.target,
            extractor_version=rule.extractor_version,
            on_error=rule.on_error,
            timeout_s=rule.timeout_s,
            options=_mapping_payload(payload),
            order=rule.order,
            batch=rule.batch,
            path_independent=rule.path_independent,
            max_source_bytes=rule.max_source_bytes,
        )

    def materialize(self) -> PreprocessRule:
        """Build a fresh picklable worker rule from snapshot authority."""
        options = {key: _thaw_option(value) for key, value in self.options}
        return PreprocessRule(
            pattern=self.pattern,
            command=self.command,
            entry_point=self.entry_point,
            priority=self.priority,
            target=self.target,
            extractor_version=self.extractor_version,
            on_error=self.on_error,
            timeout_s=self.timeout_s,
            options=options,
            order=self.order,
            batch=self.batch,
            path_independent=self.path_independent,
            max_source_bytes=self.max_source_bytes,
        )


@dataclass(frozen=True, slots=True)
class ResolvedIndexPolicy:
    """One exact, reconstructible policy snapshot for an index operation."""

    root_dir: pathlib.Path
    policy_schema_version: int
    content_policy: RootContentPolicy
    preprocess_schema_version: int
    preprocess_rules: tuple[ResolvedPreprocessRule, ...]
    decoder: DecoderPolicy
    execution_mode: PreprocessMode
    html_strip: bool
    max_emitted_bytes: int
    gitignore_patterns: tuple[str, ...]
    vaultragignore_patterns: tuple[str, ...]
    extra_excludes: tuple[str, ...]
    document_chunking: DocumentChunkingPolicy = field(
        default_factory=DocumentChunkingPolicy
    )
    fingerprints: _config_epoch.NormalizedPolicyFingerprints = field(init=False)
    _git_spec: pathspec.GitIgnoreSpec = field(init=False, repr=False, compare=False)
    _rag_spec: pathspec.GitIgnoreSpec | None = field(
        init=False, repr=False, compare=False
    )
    _preprocess_matchers: tuple[
        tuple[pathspec.GitIgnoreSpec, ResolvedPreprocessRule], ...
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.root_dir.resolve() != self.root_dir:
            raise ValueError("resolved policy root must be canonical")
        policy_schema_version = cast("object", self.policy_schema_version)
        if (
            isinstance(policy_schema_version, bool)
            or policy_schema_version != POLICY_SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported policy schema version {self.policy_schema_version}"
            )
        preprocess_schema_version = cast("object", self.preprocess_schema_version)
        if (
            isinstance(preprocess_schema_version, bool)
            or not isinstance(preprocess_schema_version, int)
            or preprocess_schema_version <= 0
        ):
            raise ValueError("preprocess_schema_version must be a positive integer")
        html_strip = cast("object", self.html_strip)
        if not isinstance(html_strip, bool):
            raise ValueError("html_strip must be a boolean")
        validate_max_emitted_bytes(cast("object", self.max_emitted_bytes))
        if self.execution_mode not in {"default", "off"}:
            raise ValueError(
                f"unknown preprocess execution mode {self.execution_mode!r}"
            )

        route_owners = {
            route.pattern: route.kind for route in self.content_policy.routes
        }
        for rule in self.preprocess_rules:
            route_owner = route_owners.get(rule.pattern)
            if route_owner is not None and route_owner is not rule.target:
                from .._job_errors import JobErrorKind
                from ._content_policy import AdmissionPolicyError

                raise AdmissionPolicyError(
                    f"{JobErrorKind.ADMISSION_CONFIG_INVALID.value}: pattern "
                    f"{rule.pattern!r} targets both {route_owner.value!r} and "
                    f"{rule.target.value!r}"
                )

        git_spec = pathspec.GitIgnoreSpec.from_lines(self.gitignore_patterns)
        effective_root_ignores = (*self.vaultragignore_patterns, *self.extra_excludes)
        rag_spec = (
            pathspec.GitIgnoreSpec.from_lines(effective_root_ignores)
            if effective_root_ignores
            else None
        )
        preprocess_matchers = tuple(
            (pathspec.GitIgnoreSpec.from_lines([rule.pattern]), rule)
            for rule in self.preprocess_rules
        )
        fingerprints = _config_epoch.resolved_policy_fingerprints(
            policy_schema_version=self.policy_schema_version,
            content_policy=self.content_policy,
            gitignore_patterns=self.gitignore_patterns,
            vaultragignore_patterns=self.vaultragignore_patterns,
            extra_excludes=self.extra_excludes,
            preprocess_schema_version=self.preprocess_schema_version,
            preprocess_rules=self.preprocess_rules,
            decoder_encoding=self.decoder.encoding,
            decoder_errors=self.decoder.errors,
            normalize_newlines=self.decoder.normalize_newlines,
            execution_mode=self.execution_mode,
            html_strip=self.html_strip,
            max_emitted_bytes=self.max_emitted_bytes,
            document_chunking={
                "chunk_chars": self.document_chunking.chunk_chars,
                "chunk_overlap_chars": self.document_chunking.chunk_overlap_chars,
                "unit_text_max_chars": self.document_chunking.unit_text_max_chars,
            },
        )
        object.__setattr__(self, "_git_spec", git_spec)
        object.__setattr__(self, "_rag_spec", rag_spec)
        object.__setattr__(self, "_preprocess_matchers", preprocess_matchers)
        object.__setattr__(self, "fingerprints", fingerprints)

    def __reduce__(self) -> tuple[type[ResolvedIndexPolicy], tuple[object, ...]]:
        """Pickle canonical fields and rebuild mutable matcher caches."""
        return (
            ResolvedIndexPolicy,
            (
                self.root_dir,
                self.policy_schema_version,
                self.content_policy,
                self.preprocess_schema_version,
                self.preprocess_rules,
                self.decoder,
                self.execution_mode,
                self.html_strip,
                self.max_emitted_bytes,
                self.gitignore_patterns,
                self.vaultragignore_patterns,
                self.extra_excludes,
                self.document_chunking,
            ),
        )

    def match_preprocess(self, rel_path: str) -> ResolvedPreprocessRule | None:
        """Return the snapshot transform assigned to a relative path, if any."""
        for matcher, rule in self._preprocess_matchers:
            if matcher.match_file(rel_path):
                return rule
        return None

    def transform_disabled(self, rel_path: str) -> bool:
        """Return whether routing is retained while its transform is disabled.

        A path in this state keeps its published membership and its prior
        points; the run reports it through ``preprocess_stale_note``.
        """
        return (
            self.execution_mode == "off" and self.match_preprocess(rel_path) is not None
        )

    def classify(self, rel_path: str) -> ClassifiedContent:
        """Classify one path using only this snapshot's resolved inputs."""
        rule = self.match_preprocess(rel_path)
        return classify_content(
            rel_path=rel_path,
            ignored=_ignore_specs.is_ignored(rel_path, self._git_spec, self._rag_spec),
            policy=self.content_policy,
            transform_kind=rule.target if rule is not None else None,
        )

    def fingerprints_for(
        self,
        kind: ContentKind,
    ) -> _config_epoch.ContentKindFingerprints:
        """Return the independent membership/content identity for one kind."""
        return self.fingerprints.per_kind.for_kind(kind)


def preprocess_stale_note(rel_path: str) -> str:
    """Report one path whose retained work went stale under a disabled transform.

    The companion to ``ResolvedIndexPolicy.transform_disabled``: every run that
    retains a path on that predicate surfaces it with this one wording.
    """
    return f"{rel_path}: preprocessing disabled; retained work as stale"


def compile_content_policy(config: RootContentPolicyConfig) -> RootContentPolicy:
    """Compile raw caller configuration into closed policy vocabulary."""
    from .._job_errors import JobErrorKind
    from ._content_policy import AdmissionPolicyError

    try:
        source_profile = SourceProfileVersion(config.source_profile)
    except ValueError:
        raise AdmissionPolicyError(
            f"{JobErrorKind.ADMISSION_CONFIG_INVALID.value}: unknown source profile "
            f"{config.source_profile!r}"
        ) from None

    routes: list[ContentRoute] = []
    for index, route in enumerate(config.routes):
        try:
            kind = ContentKind(route.target)
        except ValueError:
            raise AdmissionPolicyError(
                f"{JobErrorKind.ADMISSION_CONFIG_INVALID.value}: route #{index} has "
                f"unknown target {route.target!r}"
            ) from None
        routes.append(ContentRoute(route.pattern, kind))
    try:
        return RootContentPolicy(source_profile, tuple(routes))
    except AdmissionPolicyError as exc:
        raise AdmissionPolicyError(
            f"{JobErrorKind.ADMISSION_CONFIG_INVALID.value}: {exc}"
        ) from exc


def resolve_index_policy(
    root_dir: pathlib.Path,
    options: IndexPolicyResolutionOptions,
) -> ResolvedIndexPolicy:
    """Resolve one root policy without reopening mutable index resources."""
    cfg = get_config()
    resolved_decoder = options.decoder or DecoderPolicy()
    resolved_mode = (
        cfg.preprocess_mode
        if options.execution_mode is None
        else options.execution_mode
    )
    resolved_html_strip = (
        bool(cfg.html_strip) if options.html_strip is None else options.html_strip
    )
    resolved_max_bytes = (
        int(cfg.preprocess_max_emitted_bytes)
        if options.max_emitted_bytes is None
        else options.max_emitted_bytes
    )

    # Strict loading both rejects malformed ownership and bypasses the kill
    # switch. Routing stays present when execution is off; consumers consult
    # execution_mode before launching an extractor.
    preprocess_config = load_preprocess_rules(root_dir, strict=True)
    rules = tuple(
        ResolvedPreprocessRule.from_rule(rule) for rule in preprocess_config.rules
    )
    return ResolvedIndexPolicy(
        root_dir=root_dir.resolve(),
        policy_schema_version=POLICY_SCHEMA_VERSION,
        content_policy=options.content_policy,
        preprocess_schema_version=preprocess_config.schema_version,
        preprocess_rules=rules,
        decoder=resolved_decoder,
        execution_mode=resolved_mode,
        html_strip=resolved_html_strip,
        max_emitted_bytes=resolved_max_bytes,
        gitignore_patterns=tuple(_ignore_specs.collect_gitignore_patterns(root_dir)),
        vaultragignore_patterns=tuple(
            _ignore_specs.collect_vaultragignore_patterns(root_dir)
        ),
        extra_excludes=tuple(options.extra_excludes),
        document_chunking=DocumentChunkingPolicy(
            chunk_chars=int(cfg.document_chunk_chars),
            chunk_overlap_chars=int(cfg.document_chunk_overlap_chars),
            unit_text_max_chars=UNIT_TEXT_MAX_CHARS,
        ),
    )
