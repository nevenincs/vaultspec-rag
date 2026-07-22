"""Per-root document-preprocessing rule configuration.

Loads ``.vaultragpreprocess.toml`` from the project root and resolves it
into an ordered, compiled set of preprocessing rules. This is the registration
surface decided in the ``preprocess-hooks`` ADR (D1, D2, D3): a sibling of
``.vaultragignore`` that maps file patterns to project-supplied extraction
commands so binary or unsupported formats can be indexed first-class.

The module is deliberately CPU-only and dependency-light (stdlib ``tomllib``
plus the already-present ``pathspec``) so it is safe to import from the spawn
chunk worker. Rule *matching* (which needs the compiled ``pathspec`` specs)
lives in :class:`PreprocessConfig`, held parent-side; the matched
:class:`PreprocessRule` is a small frozen, picklable dataclass that can be
threaded into a worker task without dragging the compiled specs across the
process boundary.

Error policy (D3): a missing or malformed config degrades to zero rules (warn,
never raise - a broken file must not wedge the resident watcher service); an
individual malformed rule is dropped with a warning while valid rules survive.
Hard-fail is reserved for the explicit ``preprocess check`` CLI verb, which
calls :func:`load_preprocess_rules` with ``strict=True``.
"""

from __future__ import annotations

import dataclasses
import logging
import tomllib
from typing import TYPE_CHECKING, Literal, cast

import pathspec

from .._job_errors import JobErrorKind
from ._content_policy import ContentKind

if TYPE_CHECKING:
    import pathlib
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
    "load_preprocess_rules",
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

    Strict mode backs the ``preprocess check`` CLI verb (D13), the only path
    where a config defect is a hard error. The non-strict default degrades
    instead, per the D3 error policy.
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
            by the runner (the safe form of D9). Exactly one of
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


class PreprocessConfig:
    """An ordered, compiled set of preprocessing rules for one project root.

    Holds each rule alongside a compiled single-pattern ``pathspec`` matcher.
    Rules are pre-sorted by ``(priority, order)`` at construction so
    :meth:`match` is a deterministic first-match scan (D2).
    """

    __slots__ = ("_compiled", "_schema_version")

    def __init__(
        self,
        rules: list[PreprocessRule],
        schema_version: int = SUPPORTED_CONFIG_VERSION,
    ) -> None:
        """Compile and order the given rules.

        Args:
            rules: Validated rules in source-file order.
            schema_version: Declared policy schema version.
        """
        self._schema_version = schema_version
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
    ) -> tuple[type[PreprocessConfig], tuple[list[PreprocessRule], int]]:
        """Pickle by re-running the constructor over the picklable rules.

        The compiled ``pathspec`` matchers are rebuilt on unpickle rather than
        serialised, so this config can be threaded into a spawn chunk worker
        (D6) without depending on ``pathspec`` internals being picklable.
        """
        return (PreprocessConfig, (self.rules, self.schema_version))


@dataclasses.dataclass(frozen=True, slots=True)
class PreprocessContext:
    """Everything a chunk worker needs to preprocess a matched file.

    Threaded into the spawn worker alongside each file (D6). All fields are
    picklable: :class:`PreprocessConfig` rebuilds its matchers on unpickle,
    ``cache_root`` is a path, and the cap is an int.

    Attributes:
        config: The resolved per-root preprocess rules.
        cache_root: The preprocess output cache root.
        max_emitted_bytes: The emitted-text length cap (D10).
        project_root: The project root; placed on the hook child's
            ``PYTHONPATH`` so a ``command``/``entry_point`` that imports its own
            module tree can do so.
    """

    config: PreprocessConfig
    cache_root: pathlib.Path
    max_emitted_bytes: int
    project_root: pathlib.Path


def load_preprocess_rules(
    root_dir: pathlib.Path,
    *,
    strict: bool = False,
) -> PreprocessConfig:
    """Load and resolve ``.vaultragpreprocess.toml`` from a project root.

    Mirrors ``.vaultragignore`` resolution: root-only, no subtree walk. The
    non-strict default implements the D3 degrade policy; ``strict=True`` raises
    :class:`PreprocessConfigError` on the first defect and backs the
    ``preprocess check`` CLI verb.

    Resolution always retains valid rules, including when execution is switched
    off.  The kill switch is enforced only while materializing worker context,
    so routing and ownership remain available to discovery and reconciliation.

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
    config_file = root_dir / PREPROCESS_CONFIG_FILENAME
    if not config_file.is_file():
        return PreprocessConfig([])

    data: dict[str, object]
    try:
        raw = config_file.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        message = (
            f"{PREPROCESS_CONFIG_FILENAME} at {config_file} "
            f"is unreadable or malformed: {exc}"
        )
        if strict:
            raise PreprocessConfigError(message) from exc
        logger.warning("%s; ignoring preprocess rules", message)
        return PreprocessConfig([])

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
            rules.append(rule)
    resolved = PreprocessConfig(rules, schema_version=version)

    return resolved


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
    are D1/D3: ``pattern`` is required; exactly one of ``command``/
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
    timeout_s = _resolve_timeout(rule_map, reject)
    batch = _resolve_batch(rule_map, command, entry_point, reject)
    path_independent = _resolve_path_independent(rule_map, reject)

    options_raw = rule_map.get("options", {})
    if not isinstance(options_raw, dict):
        raise reject("'options' must be a table")
    options = cast("dict[str, object]", options_raw)

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
    )


def _resolve_path_independent(
    rule_map: dict[str, object],
    reject: Callable[[str], _RuleRejectedError],
) -> bool:
    """Resolve explicit cross-path cache reuse authority."""
    value = rule_map.get("path_independent", False)
    if not isinstance(value, bool):
        raise reject("'path_independent' must be a boolean")
    return value


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


def _resolve_timeout(
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
