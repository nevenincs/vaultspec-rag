"""Per-root document-preprocessing rule configuration.

Loads ``.vaultragpreprocess.toml`` from the project root and resolves it
into an ordered, compiled set of preprocessing rules. This is the registration
surface: a sibling of ``.vaultragignore`` that maps file patterns to
project-supplied extraction commands so binary or unsupported formats can be
indexed first-class.

The module is deliberately CPU-only and dependency-light (stdlib ``tomllib``
plus the already-present ``pathspec``) so it is safe to import from the spawn
chunk worker. Rule *matching* (which needs the compiled ``pathspec`` specs)
lives in :class:`PreprocessConfig`, held parent-side; the matched
:class:`PreprocessRule` is a small frozen, picklable dataclass that can be
threaded into a worker task without dragging the compiled specs across the
process boundary.

Error policy: a missing or malformed config degrades to zero rules (warn,
never raise - a broken file must not wedge the resident watcher service); an
individual malformed rule is dropped with a warning while valid rules survive.
A missing target or extractor version, or a defective declared input, is a
typed policy error for the whole root instead, so routing never changes
silently. Hard-fail is reserved for the explicit ``preprocess check`` CLI verb, which
calls :func:`load_preprocess_rules` with ``strict=True``.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import math
import os
import pathlib
import tomllib
from typing import TYPE_CHECKING, Literal, cast

import pathspec

from .. import store_schema
from .._job_errors import JobErrorKind
from ..operator_state._features import PreprocessHookState
from ._content_policy import ContentKind
from ._preprocess_approval import policy_is_approved
from ._source_file import open_source_file

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = logging.getLogger(__name__)

# A preprocess command with no declared ``timeout_s`` still gets a bounded
# wall-clock ceiling so an omitted timeout can never mean "wait forever" (DoS).
# An explicit value is honoured up to the hard maximum.
_DEFAULT_PREPROCESS_TIMEOUT_S = 120.0
_MAX_PREPROCESS_TIMEOUT_S = 1800.0

__all__ = [
    "PREPROCESS_CONFIG_FILENAME",
    "OnError",
    "PreprocessConfig",
    "PreprocessConfigError",
    "PreprocessContext",
    "PreprocessPolicyError",
    "PreprocessRule",
    "config_hook_state",
    "hook_state",
    "load_filterable_metadata",
    "load_preprocess_rules",
    "root_hook_state",
]

#: The per-root config filename, a sibling of ``.vaultragignore``.
PREPROCESS_CONFIG_FILENAME = ".vaultragpreprocess.toml"

#: The config-schema major this loader understands. A file declaring a higher
#: top-level ``version`` is rejected (degrade in the default mode) so a future
#: incompatible config shape is never silently half-read (review CONFIG-001).
SUPPORTED_CONFIG_VERSION = 2

#: Default rule priority when a rule omits ``priority``. Lower sorts first
#: (higher precedence); the shared default makes file order the tie-breaker.
_DEFAULT_PRIORITY = 100

OnError = Literal["skip", "fail", "passthrough"]

_VALID_ON_ERROR: frozenset[str] = frozenset({"skip", "fail", "passthrough"})


class PreprocessConfigError(ValueError):
    """Raised by :func:`load_preprocess_rules` in strict mode on any defect.

    Strict mode backs the ``preprocess check`` CLI verb, the only path
    where a config defect is a hard error. The non-strict default degrades
    instead, per the error policy.
    """


class PreprocessPolicyError(PreprocessConfigError):
    """Fail-closed routing or migration defect with a stable job error kind."""

    error_kind: JobErrorKind

    def __init__(self, error_kind: JobErrorKind, detail: str) -> None:
        self.error_kind = error_kind
        super().__init__(f"{error_kind.value}: {detail}")


@dataclasses.dataclass(frozen=True, slots=True)
class PreprocessRule:
    """One resolved, validated preprocessing rule.

    Picklable by construction (only primitives and a plain mapping), so the
    matched rule for a file can be threaded into a spawn chunk worker without
    carrying the compiled ``pathspec`` matcher across the process boundary.

    Attributes:
        pattern: The gitignore-style glob this rule matched on.
        command: The subprocess command template with a ``{path}``
            placeholder (or a ``{paths}`` manifest placeholder when
            ``batch`` is set). Exactly one of ``command``/``entry_point`` is
            set.
        entry_point: A ``"module:callable"`` reference, executed out-of-process
            by the runner (the safe out-of-process form). Exactly one of
            ``command``/``entry_point`` is set.
        priority: Lower sorts first (higher precedence).
        target: Content domain that owns the extracted output.
        extractor_version: Caller-managed semantic version for cache and
            content-fingerprint invalidation.
        on_error: Disposition when preprocessing fails: ``skip`` (drop the
            file), ``fail`` (abort the index run), or ``passthrough`` (index
            the raw file unprocessed).
        timeout_s: Wall-clock bound for the command subprocess, or ``None``
            for no explicit bound.
        options: Opaque per-rule options forwarded to the preprocessor.
        order: Zero-based position of the rule in the source file, used as the
            deterministic tie-breaker after ``priority``.
        batch: When ``True`` the command receives a manifest of source paths
            via a ``{paths}`` placeholder and emits a JSON array of per-file
            outputs, so one subprocess amortises the spawn cost across many
            files. Valid only on ``command`` rules whose command carries
            ``{paths}``; never combined with ``entry_point``.
        path_independent: Permit cache reuse between byte-identical inputs at
            different paths. Defaults to false because most extractors embed
            source identity in locators or metadata.
        max_source_bytes: Optional per-rule source-size ceiling. The worker
            combines it with the active support-profile ceiling and enforces
            the smaller value before launching an extractor.
        inputs: Root-relative gitignore-style patterns naming the files that
            define the extractor, such as its script and helper modules.
        inputs_digest: Digest over the matched input files' root-relative
            paths and contents, or ``None`` when the rule declares no inputs.
    """

    pattern: str
    command: str | None
    entry_point: str | None
    priority: int
    target: ContentKind
    extractor_version: str
    on_error: OnError
    timeout_s: float | None
    options: Mapping[str, object]
    order: int
    batch: bool = False
    path_independent: bool = False
    max_source_bytes: int | None = None
    inputs: tuple[str, ...] = ()
    inputs_digest: str | None = None


class PreprocessConfig:
    """An ordered, compiled set of preprocessing rules for one project root.

    Holds each rule alongside a compiled single-pattern ``pathspec`` matcher.
    Rules are pre-sorted by ``(priority, order)`` at construction so
    :meth:`match` is a deterministic first-match scan.
    """

    __slots__ = ("_compiled", "_policy_digest", "_schema_version")

    def __init__(
        self,
        rules: list[PreprocessRule],
        schema_version: int = SUPPORTED_CONFIG_VERSION,
        policy_digest: str | None = None,
    ) -> None:
        """Compile and order the given rules.

        Args:
            rules: Validated rules in source-file order.
            schema_version: Declared policy schema version.
            policy_digest: Digest of the policy file bytes these rules were
                parsed from, or ``None`` for a config that was not read from
                a file.
        """
        self._schema_version = schema_version
        self._policy_digest = policy_digest
        owners: dict[str, ContentKind] = {}
        for rule in rules:
            existing = owners.setdefault(rule.pattern, rule.target)
            if existing is not rule.target:
                raise PreprocessPolicyError(
                    JobErrorKind.ADMISSION_CONFIG_INVALID,
                    f"preprocess pattern {rule.pattern!r} targets both "
                    f"{existing.value!r} and {rule.target.value!r}",
                )
        ordered = sorted(rules, key=lambda r: (r.priority, r.order))
        self._compiled: list[tuple[pathspec.GitIgnoreSpec, PreprocessRule]] = [
            (pathspec.GitIgnoreSpec.from_lines([rule.pattern]), rule)
            for rule in ordered
        ]

    def __bool__(self) -> bool:
        """Return whether any rules are present."""
        return bool(self._compiled)

    @property
    def rules(self) -> list[PreprocessRule]:
        """Return the resolved rules in precedence order."""
        return [rule for _, rule in self._compiled]

    @property
    def schema_version(self) -> int:
        """Return the declared root policy schema version."""
        return self._schema_version

    @property
    def policy_digest(self) -> str | None:
        """Return the digest an operator approval of these rules must name.

        Taken over the bytes the rules were parsed from, so the rules a run
        executes and the policy its approval is checked against cannot be two
        different readings of the file.
        """
        return self._policy_digest

    def approved_for(self, root: pathlib.Path) -> bool:
        """Whether the operator approved exactly this policy for *root*.

        A config without rules has nothing to approve, so it never reads the
        approval store.
        """
        return bool(self._compiled) and policy_is_approved(root, self._policy_digest)

    def match(self, rel_path: str) -> PreprocessRule | None:
        """Return the highest-precedence rule whose pattern matches.

        Args:
            rel_path: POSIX-normalised, project-relative path (the same path
                form the ignore specs are matched against).

        Returns:
            The matching :class:`PreprocessRule`, or ``None`` if no rule
            matches.
        """
        for spec, rule in self._compiled:
            if spec.match_file(rel_path):
                return rule
        return None

    def __reduce__(
        self,
    ) -> tuple[type[PreprocessConfig], tuple[list[PreprocessRule], int, str | None]]:
        """Pickle by re-running the constructor over the picklable rules.

        The compiled ``pathspec`` matchers are rebuilt on unpickle rather than
        serialised, so this config can be threaded into a spawn chunk worker
        so it can cross the spawn boundary without depending on ``pathspec``
        internals being picklable.
        """
        return (
            PreprocessConfig,
            (self.rules, self.schema_version, self.policy_digest),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class PreprocessContext:
    """Everything a chunk worker needs to preprocess a matched file.

    Threaded into the spawn worker alongside each file. All fields are
    picklable: :class:`PreprocessConfig` rebuilds its matchers on unpickle,
    ``cache_root`` is a path, and the cap is an int.

    Attributes:
        config: The resolved per-root preprocess rules.
        cache_root: The preprocess output cache root.
        max_emitted_bytes: The emitted-text length cap.
        project_root: The project root; placed on the hook child's
            ``PYTHONPATH`` so a ``command``/``entry_point`` that imports its own
            module tree can do so.
        max_source_bytes: Optional support-profile ceiling applied to every
            source before extraction. A matching rule may lower this ceiling.
    """

    config: PreprocessConfig
    cache_root: pathlib.Path
    max_emitted_bytes: int
    project_root: pathlib.Path
    max_source_bytes: int | None = None


def load_preprocess_rules(
    root_dir: pathlib.Path,
    *,
    strict: bool = False,
) -> PreprocessConfig:
    """Load and resolve ``.vaultragpreprocess.toml`` from a project root.

    Mirrors ``.vaultragignore`` resolution: root-only, no subtree walk. The
    non-strict default implements the degrade policy; ``strict=True`` raises
    :class:`PreprocessConfigError` on the first defect and backs the
    ``preprocess check`` CLI verb.

    Resolution always retains valid rules, including when execution is switched
    off or the root's policy is not approved.  Both are enforced only while
    materializing worker context, so routing and ownership remain available to
    discovery and reconciliation.

    Args:
        root_dir: The project root to resolve the config from.
        strict: When ``True``, raise on any parse or rule defect instead of
            warning and degrading, and bypass the mode gate.

    Returns:
        A :class:`PreprocessConfig`; empty when the file is absent, malformed
        (non-strict), or carries no valid rules.

    Raises:
        PreprocessConfigError: Only when ``strict`` is ``True`` and the config
            is malformed or contains an invalid rule.
    """
    document = _read_config(root_dir, strict=strict)
    if document is None:
        return PreprocessConfig([])
    raw, data = document

    version = data.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        message = (
            f"{PREPROCESS_CONFIG_FILENAME}: top-level 'version' must be an integer"
        )
        if strict:
            raise PreprocessConfigError(message)
        logger.warning("%s; ignoring preprocess rules", message)
        return PreprocessConfig([])
    if version > SUPPORTED_CONFIG_VERSION:
        message = (
            f"{PREPROCESS_CONFIG_FILENAME}: config version {version} is newer than "
            f"supported ({SUPPORTED_CONFIG_VERSION}); upgrade vaultspec-rag"
        )
        raise PreprocessPolicyError(JobErrorKind.ADMISSION_CONFIG_INVALID, message)
    if version < SUPPORTED_CONFIG_VERSION:
        raise PreprocessPolicyError(
            JobErrorKind.MIGRATION_REQUIRED,
            f"{PREPROCESS_CONFIG_FILENAME}: config version {version} must be "
            f"migrated to {SUPPORTED_CONFIG_VERSION}",
        )

    raw_rules = data.get("rule", [])
    if not isinstance(raw_rules, list):
        message = f"{PREPROCESS_CONFIG_FILENAME}: 'rule' must be an array of tables"
        if strict:
            raise PreprocessConfigError(message)
        logger.warning("%s; ignoring preprocess rules", message)
        return PreprocessConfig([])

    rules: list[PreprocessRule] = []
    for order, raw_rule in enumerate(cast("list[object]", raw_rules)):
        rule = _resolve_rule(raw_rule, order, strict=strict)
        if rule is not None:
            rules.append(_with_inputs_digest(root_dir, rule))
    if strict:
        # Validated here too so the check verb reports a bad declaration;
        # the declaration itself is read by load_filterable_metadata.
        _resolve_filterable_metadata(data, strict=True)
    return PreprocessConfig(
        rules,
        schema_version=version,
        policy_digest=f"sha256:{hashlib.sha256(raw).hexdigest()}",
    )


def _read_config(
    root_dir: pathlib.Path, *, strict: bool
) -> tuple[bytes, dict[str, object]] | None:
    """Read and parse the root's config file, or ``None`` when there is none.

    A missing file is ``None``. An unreadable or malformed one is ``None``
    after a warning, or raises in strict mode.
    """
    config_file = root_dir / PREPROCESS_CONFIG_FILENAME
    if not config_file.is_file():
        return None
    try:
        raw = config_file.read_bytes()
        return raw, tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        message = (
            f"{PREPROCESS_CONFIG_FILENAME} at {config_file} "
            f"is unreadable or malformed: {exc}"
        )
        if strict:
            raise PreprocessConfigError(message) from exc
        logger.warning("%s; ignoring it", message)
        return None


#: The array of tables declaring filterable document metadata keys.
FILTERABLE_METADATA_TABLE = "filterable_metadata"


def load_filterable_metadata(
    root_dir: pathlib.Path,
) -> tuple[store_schema.DeclaredMetadataKey, ...]:
    """Return the document metadata keys a root declares filterable.

    Each ``[[filterable_metadata]]`` entry names a ``key`` and one ``scope``,
    ``unit`` or ``document``. The declaration is neither a rule nor part of
    any policy fingerprint, so changing it never requires a rebuild.

    Never raises: a missing, unreadable, or unsupported file declares nothing,
    and an invalid entry is dropped with a warning. The ``preprocess check``
    verb reports the same defects as errors.
    """
    document = _read_config(root_dir, strict=False)
    if document is None:
        return ()
    _raw, data = document
    if data.get("version", 1) != SUPPORTED_CONFIG_VERSION:
        logger.warning(
            "%s: unsupported config version; no metadata key is filterable",
            PREPROCESS_CONFIG_FILENAME,
        )
        return ()
    return _resolve_filterable_metadata(data, strict=False)


def _resolve_filterable_metadata(
    data: dict[str, object], *, strict: bool
) -> tuple[store_schema.DeclaredMetadataKey, ...]:
    """Validate the declaration table into declared keys.

    A key declared in both scopes is a configuration error; outside strict
    mode it is dropped entirely, because either scope would be a guess.
    """

    def reject(message: str) -> None:
        full = f"{PREPROCESS_CONFIG_FILENAME}: {message}"
        if strict:
            raise PreprocessConfigError(full)
        logger.warning("%s", full)

    entries = data.get(FILTERABLE_METADATA_TABLE, [])
    if not isinstance(entries, list):
        reject(f"'{FILTERABLE_METADATA_TABLE}' must be an array of tables")
        return ()
    scopes: dict[str, set[store_schema.MetadataScope]] = {}
    for index, entry in enumerate(cast("list[object]", entries)):
        where = f"{FILTERABLE_METADATA_TABLE} #{index}"
        if not isinstance(entry, dict):
            reject(f"{where} must be a table")
            continue
        table = cast("dict[str, object]", entry)
        unknown = sorted(set(table) - {"key", "scope"})
        if unknown:
            reject(f"{where} has unknown field(s) {unknown}")
            continue
        key = table.get("key")
        problem = store_schema.metadata_key_problem(key)
        if problem is not None or not isinstance(key, str):
            reject(f"{where}: {problem}")
            continue
        scope = table.get("scope")
        if scope not in store_schema.METADATA_SCOPES:
            reject(
                f"{where}: 'scope' must be one of "
                f"{list(store_schema.METADATA_SCOPES)}; got {scope!r}"
            )
            continue
        scopes.setdefault(key, set()).add(cast("store_schema.MetadataScope", scope))
    declared: list[store_schema.DeclaredMetadataKey] = []
    for key, key_scopes in sorted(scopes.items()):
        if len(key_scopes) > 1:
            reject(f"metadata key {key!r} is declared in more than one scope")
            continue
        declared.append(store_schema.DeclaredMetadataKey(key, key_scopes.pop()))
    return tuple(declared)


class _RuleRejectedError(Exception):
    """Internal sentinel raised to drop a single invalid rule (non-strict)."""


def _resolve_rule(
    raw_rule: object,
    order: int,
    *,
    strict: bool,
) -> PreprocessRule | None:
    """Validate one raw rule table into a :class:`PreprocessRule`.

    Returns ``None`` (after a warning) for an invalid rule in non-strict mode;
    raises :class:`PreprocessConfigError` in strict mode. The validation rules
    are: ``pattern`` is required; exactly one of ``command``/
    ``entry_point``; ``on_error`` is one of the known values; and an
    ``entry_point`` must be a ``"module:callable"`` reference.
    """

    def _reject(reason: str) -> _RuleRejectedError:
        message = f"{PREPROCESS_CONFIG_FILENAME}: dropping rule #{order} - {reason}"
        if strict:
            raise PreprocessConfigError(message)
        logger.warning("%s", message)
        return _RuleRejectedError(message)

    try:
        return _build_rule(raw_rule, order, _reject)
    except _RuleRejectedError:
        return None


def _build_rule(
    raw_rule: object,
    order: int,
    reject: Callable[[str], _RuleRejectedError],
) -> PreprocessRule:
    """Construct a rule or raise via ``reject`` on the first defect."""
    if not isinstance(raw_rule, dict):
        raise reject("rule must be a table")
    rule_map = cast("dict[str, object]", raw_rule)

    pattern = rule_map.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise reject("missing or non-string 'pattern'")

    command, entry_point = _resolve_invocation(rule_map, reject)
    target = _resolve_target(rule_map, order)
    extractor_version = _resolve_extractor_version(rule_map, order)
    on_error = _resolve_on_error(rule_map, reject)
    priority = _resolve_priority(rule_map, reject)
    timeout_s = resolve_timeout(rule_map, reject)
    batch = _resolve_batch(rule_map, command, entry_point, reject)
    path_independent = _resolve_path_independent(rule_map, reject)
    max_source_bytes = _resolve_max_source_bytes(rule_map, reject)
    inputs = _resolve_inputs(rule_map, order)

    options_raw = rule_map.get("options", {})
    if not isinstance(options_raw, dict):
        raise reject("'options' must be a table")
    try:
        options_value = _normalize_json_option(
            cast("dict[object, object]", options_raw)
        )
    except (TypeError, ValueError) as exc:
        raise reject(f"'options' must contain canonical JSON values: {exc}") from exc
    if not isinstance(options_value, dict):
        raise reject("'options' must be a table")
    # _normalize_json_option raises TypeError on any non-str mapping key
    # (see its recursive dict branch below), so a dict survives it with
    # str keys only.
    options = cast("dict[str, object]", options_value)

    return PreprocessRule(
        pattern=pattern,
        command=command,
        entry_point=entry_point,
        priority=priority,
        target=target,
        extractor_version=extractor_version,
        on_error=on_error,
        timeout_s=timeout_s,
        options=options,
        order=order,
        batch=batch,
        path_independent=path_independent,
        max_source_bytes=max_source_bytes,
        inputs=inputs,
    )


def _normalize_json_option(value: object) -> object:
    """Return one TOML option as a deterministic JSON-compatible value.

    TOML has native date/time scalars that JSON does not. The invocation
    envelope and cache fingerprint are JSON contracts, so normalize those
    scalars at policy admission rather than allowing serialization to fail in
    a worker. Non-finite floats are rejected because they are not JSON values.
    """
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not supported")
        return value
    if isinstance(value, list):
        return [_normalize_json_option(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        normalized: dict[str, object] = {}
        for key, nested in mapping.items():
            if not isinstance(key, str):
                raise TypeError("mapping keys must be strings")
            normalized[key] = _normalize_json_option(nested)
        return normalized
    raise TypeError(f"unsupported value type {type(value).__name__}")


def _resolve_path_independent(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> bool:
    """Resolve explicit cross-path cache reuse authority."""
    value = rule_map.get("path_independent", False)
    if not isinstance(value, bool):
        raise reject("'path_independent' must be a boolean")
    return value


def _resolve_max_source_bytes(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> int | None:
    """Resolve an optional positive per-rule source-size ceiling."""
    value = rule_map.get("max_source_bytes")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise reject("'max_source_bytes' must be a positive integer")
    return value


#: Per-rule bounds on declared inputs. Policy load hashes every matched file
#: on each operation, so these cap that cost.
_MAX_INPUT_FILES = 256
_MAX_INPUT_BYTES = 32 * 1024 * 1024
_INPUT_READ_CHUNK = 1024 * 1024
_GLOB_CHARS = frozenset("*?[")


def _inputs_error(order: int, detail: str) -> PreprocessPolicyError:
    """Return the typed refusal for a declared-input defect.

    A defect fails the whole root closed rather than dropping the rule, so
    routing never changes because an extractor file went missing.
    """
    return PreprocessPolicyError(
        JobErrorKind.ADMISSION_CONFIG_INVALID,
        f"{PREPROCESS_CONFIG_FILENAME}: rule #{order} {detail}",
    )


def _resolve_inputs(rule_map: dict[str, object], order: int) -> tuple[str, ...]:
    """Validate the optional declared-input patterns of one rule.

    Each pattern is a root-relative gitignore-style pattern. Absolute
    patterns, negations, backslashes and ``.``/``..`` components are refused
    so a declaration can only ever name files beneath the root.
    """
    raw = rule_map.get("inputs")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise _inputs_error(order, "has 'inputs' that is not a non-empty array")
    patterns: list[str] = []
    for item in cast("list[object]", raw):
        if not isinstance(item, str) or not item.strip():
            raise _inputs_error(order, "has an 'inputs' entry that is not a string")
        parts = item.split("/")
        if (
            item.startswith(("/", "!"))
            or "\\" in item
            or ":" in parts[0]
            or any(part in {".", ".."} for part in parts)
        ):
            raise _inputs_error(
                order,
                f"has 'inputs' pattern {item!r}; patterns must be relative to "
                "the project root and stay inside it",
            )
        patterns.append(item)
    return tuple(patterns)


def _with_inputs_digest(root_dir: pathlib.Path, rule: PreprocessRule) -> PreprocessRule:
    """Return *rule* carrying the digest of its declared inputs, if any."""
    if not rule.inputs:
        return rule
    return dataclasses.replace(
        rule,
        inputs_digest=_inputs_digest(root_dir.resolve(), rule.inputs, rule.order),
    )


def _inputs_digest(root: pathlib.Path, patterns: tuple[str, ...], order: int) -> str:
    """Hash the files a rule's input patterns match beneath canonical *root*.

    One digest over the sorted root-relative paths and each file's content
    digest. Every pattern must match at least one regular file, matches are
    bounded in count and total size, and each file is read through the
    canonical source admission so a link can never carry in a file from
    outside the root.
    """
    matched: dict[str, pathlib.Path] = {}
    for pattern in patterns:
        found = _match_inputs(root, pattern, order)
        if not found:
            raise _inputs_error(
                order, f"has 'inputs' pattern {pattern!r} that matches no file"
            )
        matched.update(found)
        if len(matched) > _MAX_INPUT_FILES:
            raise _inputs_error(
                order, f"declares more than {_MAX_INPUT_FILES} input files"
            )
    total = 0
    entries: list[tuple[str, str]] = []
    for rel in sorted(matched):
        file_hash = hashlib.blake2b()
        try:
            with open_source_file(matched[rel], root) as stream:
                while chunk := stream.read(_INPUT_READ_CHUNK):
                    total += len(chunk)
                    if total > _MAX_INPUT_BYTES:
                        raise _inputs_error(
                            order,
                            f"declares input files larger than {_MAX_INPUT_BYTES} "
                            "bytes in total",
                        )
                    file_hash.update(chunk)
        except OSError as exc:
            raise _inputs_error(
                order,
                f"has input file {rel!r} that is unreadable or not a regular "
                f"file inside the project root: {exc}",
            ) from exc
        entries.append((rel, file_hash.hexdigest()))
    encoded = json.dumps(entries, separators=(",", ":")).encode("utf-8")
    return f"blake2b:{hashlib.blake2b(encoded).hexdigest()}"


def _match_inputs(
    root: pathlib.Path, pattern: str, order: int
) -> dict[str, pathlib.Path]:
    """Return the in-root files one root-anchored input pattern matches.

    The walk starts at the pattern's literal directory prefix and never
    follows a link. A linked directory on the way is refused rather than
    skipped, because a skipped link would hide the files it points at from
    the digest.
    """
    spec = pathspec.GitIgnoreSpec.from_lines([f"/{pattern}"])
    prefix: list[str] = []
    for part in pattern.split("/")[:-1]:
        if not part or _GLOB_CHARS.intersection(part):
            break
        prefix.append(part)
    start = root.joinpath(*prefix)
    if not start.is_dir():
        return {}
    if start.resolve() != start:
        raise _inputs_error(
            order,
            f"has 'inputs' pattern {pattern!r} reaching outside the project "
            "root through a link",
        )
    found: dict[str, pathlib.Path] = {}
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        directory = pathlib.Path(dirpath)
        for name in dirnames:
            child = directory / name
            if child.is_symlink() or os.path.isjunction(child):
                raise _inputs_error(
                    order,
                    f"has 'inputs' pattern {pattern!r} reaching the link "
                    f"{child.relative_to(root).as_posix()!r}; declare paths "
                    "that do not pass through links",
                )
        for name in filenames:
            path = directory / name
            rel = path.relative_to(root).as_posix()
            if spec.match_file(rel):
                found[rel] = path
    return found


def _resolve_target(
    rule_map: dict[str, object],
    order: int,
) -> ContentKind:
    """Resolve the required content owner without applying fallback routing."""
    target_raw = rule_map.get("target")
    if target_raw is None:
        raise PreprocessPolicyError(
            JobErrorKind.MIGRATION_REQUIRED,
            f"{PREPROCESS_CONFIG_FILENAME}: rule #{order} is missing 'target'",
        )
    if not isinstance(target_raw, str) or not target_raw:
        raise PreprocessPolicyError(
            JobErrorKind.ADMISSION_CONFIG_INVALID,
            f"{PREPROCESS_CONFIG_FILENAME}: rule #{order} has a non-string 'target'",
        )
    try:
        return ContentKind(target_raw)
    except ValueError:
        raise PreprocessPolicyError(
            JobErrorKind.ADMISSION_CONFIG_INVALID,
            f"{PREPROCESS_CONFIG_FILENAME}: rule #{order} has unknown "
            f"'target' {target_raw!r}",
        ) from None


def _resolve_extractor_version(
    rule_map: dict[str, object],
    order: int,
) -> str:
    """Resolve the required caller-managed extractor semantic version."""
    version_raw = rule_map.get("extractor_version")
    if version_raw is None:
        raise PreprocessPolicyError(
            JobErrorKind.MIGRATION_REQUIRED,
            f"{PREPROCESS_CONFIG_FILENAME}: rule #{order} is missing "
            "'extractor_version'",
        )
    if not isinstance(version_raw, str) or not version_raw.strip():
        raise PreprocessPolicyError(
            JobErrorKind.ADMISSION_CONFIG_INVALID,
            f"{PREPROCESS_CONFIG_FILENAME}: rule #{order} has an invalid "
            "'extractor_version'",
        )
    return version_raw.strip()


def _resolve_invocation(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> tuple[str | None, str | None]:
    """Resolve the command/entry_point XOR, returning ``(command, entry_point)``.

    Exactly one is non-``None``. ``entry_point`` must be a ``"module:callable"``
    reference; it is executed out-of-process by the runner (#185 follow-up), so
    it is no longer rejected at load time.
    """
    command_raw = rule_map.get("command")
    entry_raw = rule_map.get("entry_point")
    if (command_raw is None) == (entry_raw is None):
        raise reject("rule must set exactly one of 'command' or 'entry_point'")
    if command_raw is not None:
        if not isinstance(command_raw, str) or not command_raw:
            raise reject("'command' must be a non-empty string")
        return command_raw, None
    if not isinstance(entry_raw, str) or not entry_raw:
        raise reject("'entry_point' must be a non-empty string")
    module, sep, attr = entry_raw.partition(":")
    if not sep or not module or not attr:
        raise reject("'entry_point' must be of the form 'module:callable'")
    return None, entry_raw


#: The manifest placeholder a batch command must carry, and the per-file
#: placeholder it must not (a batch command is handed a paths manifest, never a
#: single path).
_BATCH_PLACEHOLDER = "{paths}"
_SINGLE_PLACEHOLDER = "{path}"


def _resolve_batch(
    rule_map: dict[str, object],
    command: str | None,
    entry_point: str | None,
    reject: Callable[[str], _RuleRejectedError],
) -> bool:
    """Resolve and validate the ``batch`` knob against the invocation form.

    ``batch = true`` is valid only on a ``command`` rule whose command carries
    the ``{paths}`` manifest placeholder and not the per-file ``{path}``
    placeholder; it is never combined with ``entry_point`` (which keeps v1
    per-file semantics). A non-batch command must not carry ``{paths}`` - the
    manifest placeholder is meaningless without a batch invocation.
    """
    batch_raw = rule_map.get("batch", False)
    if not isinstance(batch_raw, bool):
        raise reject("'batch' must be a boolean")
    if not batch_raw:
        if command is not None and _BATCH_PLACEHOLDER in command:
            raise reject(f"'{_BATCH_PLACEHOLDER}' placeholder requires 'batch = true'")
        return False
    if entry_point is not None:
        raise reject("'batch' is not valid with 'entry_point'")
    if command is None or _BATCH_PLACEHOLDER not in command:
        raise reject(
            f"a batch command must contain the '{_BATCH_PLACEHOLDER}' placeholder"
        )
    if _SINGLE_PLACEHOLDER in command:
        raise reject(
            f"a batch command must not contain the '{_SINGLE_PLACEHOLDER}' "
            f"placeholder; use '{_BATCH_PLACEHOLDER}'"
        )
    return True


def _resolve_on_error(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> OnError:
    """Resolve and validate the ``on_error`` disposition."""
    on_error_raw = rule_map.get("on_error", "skip")
    if not isinstance(on_error_raw, str) or on_error_raw not in _VALID_ON_ERROR:
        raise reject(
            f"invalid 'on_error' {on_error_raw!r}; "
            f"expected one of {sorted(_VALID_ON_ERROR)}"
        )
    return cast("OnError", on_error_raw)


def _resolve_priority(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> int:
    """Resolve and validate ``priority`` (defaults to the shared band)."""
    priority_raw = rule_map.get("priority", _DEFAULT_PRIORITY)
    if not isinstance(priority_raw, int) or isinstance(priority_raw, bool):
        raise reject("'priority' must be an integer")
    return priority_raw


def resolve_timeout(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> float:
    """Resolve and validate ``timeout_s``, defaulting to a bounded ceiling.

    Never returns ``None``: an omitted timeout must not mean "wait forever" for a
    project-supplied command. A blocking or hostile command with no timeout would
    otherwise hang the indexer or the resident watcher indefinitely (DoS). An
    explicit value is honoured up to a hard maximum.
    """
    timeout_raw = rule_map.get("timeout_s")
    if timeout_raw is None:
        return _DEFAULT_PREPROCESS_TIMEOUT_S
    if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
        raise reject("'timeout_s' must be a number")
    if timeout_raw <= 0:
        raise reject("'timeout_s' must be positive")
    return min(float(timeout_raw), _MAX_PREPROCESS_TIMEOUT_S)


def hook_state(rule_count: int, mode: str, *, approved: bool) -> PreprocessHookState:
    """Whether a root's preprocessing hooks run.

    This is the only derivation of "hooks will run": a root's rules run when
    the ``off`` kill switch is not thrown and the operator has approved the
    root's current policy, and a root without rules runs nothing. The kill
    switch is reported ahead of a missing approval because approving cannot
    make a switched-off service run anything.
    """
    if rule_count == 0:
        return PreprocessHookState.NONE
    if mode == "off":
        return PreprocessHookState.DISABLED
    return PreprocessHookState.ACTIVE if approved else PreprocessHookState.UNAPPROVED


def config_hook_state(
    root: pathlib.Path,
    config: PreprocessConfig,
    mode: str,
) -> PreprocessHookState:
    """Resolve the hook state of *root* for one already-loaded *config*.

    Approval is checked against the digest *config* carries, so a caller that
    goes on to run a rule from this same object runs exactly what was
    approved.
    """
    return hook_state(len(config.rules), mode, approved=config.approved_for(root))


def root_hook_state(root: pathlib.Path, mode: str) -> tuple[PreprocessHookState, int]:
    """Resolve a root's hook state and rule count for reporting.

    Reads only the root's own config file - never the tree - and never raises:
    a malformed config degrades to ``INVALID_CONFIG`` with no rules, which is
    what indexing does with it too. The count is the config's own, not a
    gated zero, so a switched-off or unapproved rule set still says how many
    it holds.
    """
    if not (root / PREPROCESS_CONFIG_FILENAME).is_file():
        return PreprocessHookState.NONE, 0
    try:
        config = load_preprocess_rules(root, strict=True)
    except PreprocessConfigError:
        return PreprocessHookState.INVALID_CONFIG, 0
    return config_hook_state(root, config, mode), len(config.rules)
