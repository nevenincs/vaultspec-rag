"""Filter validation logic for vault and codebase search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args

from .. import store_schema
from .._domain import DOMAINS
from .._source_types import PublicSourceType, parse_source_type
from .._store_models import DocumentLocatorKind

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

# The vault doc types that carry semantic content and are searchable. ``index``
# is excluded: feature-index documents are auto-generated navigational
# document-lists with no semantic value. A doc-type filter may name one of these
# or a comma-separated union of them.
INDEXABLE_DOC_TYPES: frozenset[str] = frozenset(
    {"adr", "audit", "exec", "plan", "reference", "research"}
)

# The code-result noise domains a caller may name in --exclude-domain /
# --only-domain / --include-domain. Mirrors ``_domain.DOMAINS``.
SELECTABLE_DOMAINS: frozenset[str] = frozenset(DOMAINS)
PREFER_DOMAINS: frozenset[str] = frozenset({"prod", "tests", "docs"})


@dataclass(frozen=True, slots=True)
class SearchFilterOptions:
    """All optional filters accepted by a public search surface."""

    language: str | None = None
    path: str | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    doc_type: str | None = None
    feature: str | None = None
    date: str | None = None
    tag: str | None = None
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    dedup_locales: bool | None = None
    prefer: str | None = None
    exclude_domains: list[str] | None = None
    only_domains: list[str] | None = None
    include_domains: list[str] | None = None
    source_path: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    locator_kind: str | None = None
    extractor_prefix: str | None = None
    metadata_filters: Mapping[str, Sequence[str]] | None = None


class InvalidPreferValueError(ValueError):
    """Raised when the --prefer value is not supported.

    The refusal sentence is built here rather than by each raiser, because the
    CLI's own long-name normaliser refuses the same values before validation
    ever runs and must show the operator one wording, not a second one that
    drifts from this.
    """

    def __init__(self, prefer_value: str) -> None:
        super().__init__(
            "--prefer must be one of production, tests, or documentation; "
            f"got {prefer_value!r}."
        )
        self.prefer_value = prefer_value


class InvalidFilterForSearchTypeError(ValueError):
    """Raised when filters are supplied that mismatch the search type.

    Every filter refusal derives from this class, so one handler per adapter
    renders all of them. ``error_code`` is the wire code that handler emits;
    a refusal with its own contract overrides it.
    """

    error_code: str = "invalid_filter_for_search_type"

    def __init__(
        self, message: str, filter_kind: str, offending_filters: list[str]
    ) -> None:
        super().__init__(message)
        self.filter_kind = filter_kind
        self.offending_filters = offending_filters


class InvalidDocTypeError(InvalidFilterForSearchTypeError):
    """Raised when a doc-type filter names a non-indexable or unknown type.

    Subclasses ``InvalidFilterForSearchTypeError`` so existing handlers that
    catch the base type render it as a clean exit-2 error without new wiring.
    """

    def __init__(self, message: str, offending: list[str]) -> None:
        super().__init__(message, filter_kind="doc_type", offending_filters=offending)


class InvalidDomainValueError(InvalidFilterForSearchTypeError):
    """Raised when a domain filter names a label outside ``SELECTABLE_DOMAINS``.

    Subclasses ``InvalidFilterForSearchTypeError`` so existing exit-2 handlers
    render it without new wiring (mirrors ``InvalidDocTypeError``).
    """

    def __init__(self, message: str, offending: list[str]) -> None:
        super().__init__(message, filter_kind="domain", offending_filters=offending)


class InvalidFilterValueError(InvalidFilterForSearchTypeError):
    """Raised when a filter names a value its key can never hold."""

    def __init__(self, message: str, filter_kind: str, offending: list[str]) -> None:
        super().__init__(message, filter_kind=filter_kind, offending_filters=offending)


class UnknownFilterKeyError(InvalidFilterForSearchTypeError):
    """Raised when a filter key is not filterable for the collection searched.

    Refused rather than dropped: dropping it returns a wider answer than the
    caller asked for, with nothing to say so.
    """

    error_code = "unknown_filter_key"

    def __init__(self, key: str, accepted: Sequence[str], filter_kind: str) -> None:
        listed = ", ".join(accepted) if accepted else "none"
        super().__init__(
            f"unknown {filter_kind} filter key {key!r}; accepted keys: {listed}.",
            filter_kind=filter_kind,
            offending_filters=[key],
        )
        self.key = key
        self.accepted = tuple(accepted)


class ExtractorPrefixUnboundedError(InvalidFilterForSearchTypeError):
    """Raised when an extractor prefix cannot be resolved exactly.

    The prefix resolves against the distinct ``extractor_id`` values the
    collection holds. Past the bound that set may be truncated, and a filter
    built from a partial set would silently drop matching results.
    """

    error_code = "extractor_prefix_unbounded"

    def __init__(self, bound: int) -> None:
        super().__init__(
            "extractor-prefix cannot be resolved: the document collection holds "
            f"more than {bound} distinct extractor ids. Filter by extractor-id "
            "instead.",
            filter_kind="document",
            offending_filters=["--extractor-prefix"],
        )
        self.bound = bound


#: The metadata-filter prefix shared by the inline token and refusal text.
METADATA_FILTER_PREFIX = "meta."

_LOCATOR_KINDS: frozenset[str] = frozenset(get_args(DocumentLocatorKind))

# Only these document keys take a comma-separated value list. Every other key
# keeps its exact value, even one containing a comma.
_LIST_VALUED_DOCUMENT_KEYS = frozenset({"extractor_id", "locator_kind"})


def split_filter_values(value: str) -> tuple[str, ...]:
    """Split one comma-separated filter value into its non-empty members."""
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_metadata_assignment(assignment: str) -> tuple[str, tuple[str, ...]]:
    """Parse ``key=v1,v2`` into the key and its any-of values.

    The CLI flag and the inline token share this reading. Values split on
    commas, so a value containing a comma is reachable only through a mapping.
    """
    key, sep, raw = assignment.partition("=")
    key = key.strip()
    if not sep or not key:
        raise InvalidFilterValueError(
            f"metadata filter {assignment!r} must have the form key=value[,value].",
            filter_kind="document",
            offending=[assignment],
        )
    return key, split_filter_values(raw)


def metadata_filters_from_assignments(
    assignments: Sequence[str],
) -> dict[str, list[str]] | None:
    """Return the metadata mapping a list of ``key=v1,v2`` assignments names.

    A key given twice is refused: keeping either assignment would silently
    drop the other.
    """
    if not assignments:
        return None
    mapping: dict[str, list[str]] = {}
    for assignment in assignments:
        key, values = parse_metadata_assignment(assignment)
        if key in mapping:
            raise InvalidFilterValueError(
                f"metadata key {key!r} is given more than once; list its "
                "values comma-separated in one assignment.",
                filter_kind="document",
                offending=[f"{METADATA_FILTER_PREFIX}{key}"],
            )
        mapping[key] = list(values)
    return mapping


@dataclass(frozen=True, slots=True)
class DocumentFilterRequest:
    """Every document filter one search asked for, before resolution."""

    source_path: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    locator_kind: str | None = None
    extractor_prefix: str | None = None
    metadata_filters: Mapping[str, Sequence[str]] | None = None
    inline: Mapping[str, str] | None = None


def resolve_document_filters(
    request: DocumentFilterRequest,
    declared: Sequence[store_schema.DeclaredMetadataKey],
    extractor_ids: Callable[[int], Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    """Resolve one document search's filters to any-of conditions per field.

    Returns a mapping from payload field to the values any of which must
    match. A field mapped to no values matches nothing. Explicit arguments win
    over inline query tokens for the same key. *extractor_ids* is called only
    for a prefix filter, with the number of distinct values to ask for.

    Raises:
        UnknownFilterKeyError: A metadata key the root does not declare.
        InvalidFilterValueError: A locator kind outside the closed set, a
            malformed metadata value, or a prefix with an empty segment.
        ExtractorPrefixUnboundedError: The collection holds more distinct
            extractor ids than a prefix may resolve against.
    """
    conditions, prefixes = _static_conditions(request, declared)
    if prefixes is not None:
        kept = _extractor_prefix_values(prefixes, extractor_ids)
        if "extractor_id" in conditions:
            # Both name one field and conditions combine with AND, so the
            # effective any-of set is their intersection.
            allowed = set(kept)
            kept = tuple(v for v in conditions["extractor_id"] if v in allowed)
        conditions["extractor_id"] = kept
    return conditions


def validate_document_filters(
    request: DocumentFilterRequest,
    declared: Sequence[store_schema.DeclaredMetadataKey],
) -> None:
    """Refuse every document filter that can be judged without the index.

    Run before a search counts the collection, so an empty or unbuilt index
    refuses an undeclared key exactly as a populated one does. Only the
    extractor-prefix bound needs the collection, and only resolution checks it.

    Raises:
        UnknownFilterKeyError: A metadata key the root does not declare.
        InvalidFilterValueError: A value the key can never hold.
    """
    _static_conditions(request, declared)


def _static_conditions(
    request: DocumentFilterRequest,
    declared: Sequence[store_schema.DeclaredMetadataKey],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...] | None]:
    """Return the conditions known without the index, and any prefixes."""
    inline = dict(request.inline or {})
    explicit: dict[str, str | None] = {
        "source_path": request.source_path,
        "extractor_id": request.extractor_id,
        "extractor_version": request.extractor_version,
        "locator_kind": request.locator_kind,
    }
    conditions: dict[str, tuple[str, ...]] = {}
    for key in store_schema.DOCUMENT_QUERY_FILTER_KEYS:
        value = explicit.get(key)
        if value is None:
            value = inline.get(key)
        if value is None:
            continue
        conditions[key] = (
            split_filter_values(value)
            if key in _LIST_VALUED_DOCUMENT_KEYS
            else (value,)
        )
    _check_locator_kinds(conditions.get("locator_kind", ()))
    conditions.update(_metadata_conditions(request, inline, declared))
    prefixes = (
        None
        if request.extractor_prefix is None
        else _checked_prefixes(request.extractor_prefix)
    )
    return conditions, prefixes


def _check_locator_kinds(kinds: Sequence[str]) -> None:
    invalid = sorted({kind for kind in kinds if kind not in _LOCATOR_KINDS})
    if invalid:
        raise InvalidFilterValueError(
            "locator-kind must be one or a comma-separated union of: "
            f"{', '.join(sorted(_LOCATOR_KINDS))}; got {', '.join(invalid)}.",
            filter_kind="document",
            offending=invalid,
        )


def _metadata_conditions(
    request: DocumentFilterRequest,
    inline: Mapping[str, str],
    declared: Sequence[store_schema.DeclaredMetadataKey],
) -> dict[str, tuple[str, ...]]:
    requested: dict[str, tuple[str, ...]] = {
        name.removeprefix(METADATA_FILTER_PREFIX): split_filter_values(value)
        for name, value in inline.items()
        if name.startswith(METADATA_FILTER_PREFIX)
    }
    for key, values in (request.metadata_filters or {}).items():
        requested[key] = _metadata_values(key, values)
    by_key = {item.key: item for item in declared}
    conditions: dict[str, tuple[str, ...]] = {}
    for key, values in requested.items():
        item = by_key.get(key)
        if item is None:
            raise UnknownFilterKeyError(
                f"{METADATA_FILTER_PREFIX}{key}",
                [f"{METADATA_FILTER_PREFIX}{name}" for name in sorted(by_key)],
                "document",
            )
        conditions[item.field] = values
    return conditions


def _metadata_values(key: str, values: object) -> tuple[str, ...]:
    # A bare string is refused rather than read as one value: a caller sending
    # "a,b" would otherwise match only the literal "a,b" and see no error.
    if isinstance(values, (list, tuple)):
        members: list[object] = list(values)
        if all(isinstance(member, str) for member in members):
            return tuple(str(member) for member in members)
    raise InvalidFilterValueError(
        f"metadata filter {key!r} must map to a list of strings.",
        filter_kind="document",
        offending=[f"{METADATA_FILTER_PREFIX}{key}"],
    )


def _checked_prefixes(raw: str) -> tuple[str, ...]:
    prefixes = split_filter_values(raw)
    malformed = [p for p in prefixes if any(not part for part in p.split("."))]
    if malformed or not prefixes:
        raise InvalidFilterValueError(
            "extractor-prefix must be one or a comma-separated list of dotted "
            f"prefixes with no empty segment; got {raw!r}.",
            filter_kind="document",
            offending=malformed or [raw],
        )
    return prefixes


def _extractor_prefix_values(
    prefixes: Sequence[str], extractor_ids: Callable[[int], Sequence[str]]
) -> tuple[str, ...]:
    bound = store_schema.EXTRACTOR_ID_FACET_BOUND
    values = extractor_ids(bound + 1)
    if len(values) > bound:
        raise ExtractorPrefixUnboundedError(bound)
    return tuple(
        sorted(
            {
                value
                for value in values
                for prefix in prefixes
                if value == prefix or value.startswith(f"{prefix}.")
            }
        )
    )


def _format_flags(names: list[str]) -> list[str]:
    flags: list[str] = []
    for name in names:
        flag = name.replace("_", "-")
        if not flag.startswith("--"):
            flag = f"--{flag}"
        flags.append(flag)
    return sorted(flags)


def _validate_prefer(prefer: str | None) -> None:
    if prefer is not None and prefer not in PREFER_DOMAINS:
        raise InvalidPreferValueError(prefer)


def _validate_domains(
    *,
    exclude_domains: list[str] | None,
    only_domains: list[str] | None,
    include_domains: list[str] | None,
) -> None:
    requested: list[str] = []
    for group in (exclude_domains, only_domains, include_domains):
        if group:
            requested.extend(d.strip().lower() for d in group if d.strip())
    invalid = sorted({d for d in requested if d not in SELECTABLE_DOMAINS})
    if not invalid:
        return
    allowed = ", ".join(sorted(SELECTABLE_DOMAINS))
    raise InvalidDomainValueError(
        f"domain filters must name one of: {allowed}; got {', '.join(invalid)}.",
        offending=invalid,
    )


def _validate_doc_type(doc_type: str | None) -> None:
    if doc_type is None:
        return
    requested = [t.strip() for t in doc_type.split(",") if t.strip()]
    invalid = [t for t in requested if t not in INDEXABLE_DOC_TYPES]
    if not invalid:
        return
    allowed = ", ".join(sorted(INDEXABLE_DOC_TYPES))
    raise InvalidDocTypeError(
        (
            f"doc-type must be one or a comma-separated union of: {allowed} "
            f"(the auto-generated 'index' type is not searchable); "
            f"got {', '.join(invalid)}."
        ),
        offending=invalid,
    )


def _supplied_filters(
    options: SearchFilterOptions,
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """Return code, vault, document, glob, and postprocess filter names."""
    # Keyed off the schema's filter vocabulary rather than a second list of the
    # same names. Indexing is deliberate: a key added to the schema and not
    # here raises instead of quietly dropping out of the supplied set, which
    # is what would let a filter meant for another search type slip through
    # unreported.
    supplied_values: dict[str, object] = {
        "language": options.language,
        "path": options.path,
        "node_type": options.node_type,
        "function_name": options.function_name,
        "class_name": options.class_name,
        "doc_type": options.doc_type,
        "feature": options.feature,
        "date": options.date,
        "tag": options.tag,
        "source_path": options.source_path,
        "extractor_id": options.extractor_id,
        "extractor_version": options.extractor_version,
        "locator_kind": options.locator_kind,
    }

    def _supplied(keys: tuple[str, ...]) -> list[str]:
        return [name for name in keys if supplied_values[name] is not None]

    code_supplied = _supplied(store_schema.CODE_FILTER_KEYS)
    vault_supplied = _supplied(store_schema.VAULT_FILTER_KEYS)
    document_supplied = _supplied(store_schema.DOCUMENT_FILTER_KEYS)
    if options.extractor_prefix is not None:
        document_supplied.append("extractor_prefix")
    if options.metadata_filters:
        document_supplied.append("meta")
    glob_supplied = [
        flag
        for flag, supplied in (
            ("include_path", bool(options.include_paths)),
            ("exclude_path", bool(options.exclude_paths)),
            ("exclude_domain", bool(options.exclude_domains)),
            ("only_domain", bool(options.only_domains)),
            ("include_domain", bool(options.include_domains)),
        )
        if supplied
    ]
    postproc_supplied = [
        flag
        for flag, supplied in (
            ("dedup_locales", options.dedup_locales is not None),
            ("prefer", options.prefer is not None),
        )
        if supplied
    ]
    return (
        code_supplied,
        vault_supplied,
        document_supplied,
        glob_supplied,
        postproc_supplied,
    )


def _reject_filters_for_mismatched_search_type(
    kind: str, search_type: str, offending: list[str]
) -> None:
    if not offending:
        return
    offending_flags = _format_flags(offending)
    raise InvalidFilterForSearchTypeError(
        (
            f"{kind}-search filters ({', '.join(sorted(offending_flags))}) "
            f"require --type {kind}; got --type {search_type}."
        ),
        filter_kind=kind,
        offending_filters=offending_flags,
    )


def validate_search_filters(
    search_type: str | PublicSourceType,
    options: SearchFilterOptions | None = None,
    *,
    include_documents: bool = True,
) -> None:
    """Validate that the search filters match the requested search_type.

    Raises:
        InvalidPreferValueError: If the prefer option is invalid.
        InvalidFilterForSearchTypeError: If a filter is supplied that is
            incompatible with the search_type (including an unknown domain).
    """
    if options is None:
        options = SearchFilterOptions()
    canonical = parse_source_type(search_type, allow_aliases=True)
    canonical_name = canonical.value
    _validate_prefer(options.prefer)
    _validate_doc_type(options.doc_type)
    _validate_domains(
        exclude_domains=options.exclude_domains,
        only_domains=options.only_domains,
        include_domains=options.include_domains,
    )

    (
        code_supplied,
        vault_supplied,
        document_supplied,
        glob_supplied,
        postproc_supplied,
    ) = _supplied_filters(options)

    if canonical not in {PublicSourceType.CODE, PublicSourceType.COMBINED}:
        _reject_filters_for_mismatched_search_type(
            "code", canonical_name, [*code_supplied, *glob_supplied, *postproc_supplied]
        )
    if canonical not in {PublicSourceType.VAULT, PublicSourceType.COMBINED}:
        _reject_filters_for_mismatched_search_type(
            "vault", canonical_name, vault_supplied
        )
    if (
        canonical is PublicSourceType.COMBINED
        and not include_documents
        and document_supplied
    ):
        raise InvalidFilterForSearchTypeError(
            "Document filters require include_documents=true "
            "(CLI: --type combined or --type document).",
            "document",
            document_supplied,
        )
    if canonical not in {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}:
        _reject_filters_for_mismatched_search_type(
            "document", canonical_name, document_supplied
        )
