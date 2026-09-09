"""Filter validation logic for vault and codebase search."""

from __future__ import annotations

from dataclasses import dataclass

from .. import store_schema
from .._domain import DOMAINS
from .._source_types import PublicSourceType, parse_source_type

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
    """Raised when filters are supplied that mismatch the search type."""

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


def _format_flags(names: list[str]) -> list[str]:
    flags: list[str] = []
    for name in names:
        flag = name.replace("_", "-")
        if not flag.startswith("--"):
            flag = f"--{flag}"
        flags.append(flag)
    return sorted(flags)


def _validate_prefer(prefer: str | None) -> None:
    if prefer is not None and prefer not in {"prod", "tests", "docs"}:
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
    if canonical not in {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}:
        _reject_filters_for_mismatched_search_type(
            "document", canonical_name, document_supplied
        )
