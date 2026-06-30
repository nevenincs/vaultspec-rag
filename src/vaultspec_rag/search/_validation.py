"""Filter validation logic for vault and codebase search."""

from __future__ import annotations

from typing import Literal

from .._domain import DOMAINS

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


class InvalidPreferValueError(ValueError):
    """Raised when the --prefer value is not supported."""

    def __init__(self, message: str, prefer_value: str) -> None:
        super().__init__(message)
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
        raise InvalidPreferValueError(
            (
                "--prefer must be one of production, tests, or documentation; "
                f"got {prefer!r}."
            ),
            prefer_value=prefer,
        )


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
    *,
    language: str | None,
    path: str | None,
    node_type: str | None,
    function_name: str | None,
    class_name: str | None,
    doc_type: str | None,
    feature: str | None,
    date: str | None,
    tag: str | None,
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    dedup_locales: bool | None,
    prefer: str | None,
    exclude_domains: list[str] | None,
    only_domains: list[str] | None,
    include_domains: list[str] | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return the (code, vault, glob, postproc) filter names actually supplied."""
    code_supplied = [
        name
        for name, val in (
            ("language", language),
            ("path", path),
            ("node_type", node_type),
            ("function_name", function_name),
            ("class_name", class_name),
        )
        if val is not None
    ]
    vault_supplied = [
        name
        for name, val in (
            ("doc_type", doc_type),
            ("feature", feature),
            ("date", date),
            ("tag", tag),
        )
        if val is not None
    ]
    glob_supplied = [
        flag
        for flag, supplied in (
            ("include_path", bool(include_paths)),
            ("exclude_path", bool(exclude_paths)),
            ("exclude_domain", bool(exclude_domains)),
            ("only_domain", bool(only_domains)),
            ("include_domain", bool(include_domains)),
        )
        if supplied
    ]
    postproc_supplied = [
        flag
        for flag, supplied in (
            ("dedup_locales", dedup_locales is not None),
            ("prefer", prefer is not None),
        )
        if supplied
    ]
    return code_supplied, vault_supplied, glob_supplied, postproc_supplied


def _reject_code_filters_for_non_code(search_type: str, offending: list[str]) -> None:
    if not offending:
        return
    offending_flags = _format_flags(offending)
    raise InvalidFilterForSearchTypeError(
        f"code-search filters ({', '.join(sorted(offending_flags))}) require "
        f"--type code; got --type {search_type}.",
        filter_kind="code",
        offending_filters=offending_flags,
    )


def _reject_vault_filters_for_non_vault(
    search_type: str, vault_supplied: list[str]
) -> None:
    if not vault_supplied:
        return
    offending_flags = _format_flags(vault_supplied)
    raise InvalidFilterForSearchTypeError(
        (
            f"vault-search filters ({', '.join(sorted(offending_flags))}) "
            f"require --type vault; got --type {search_type}."
        ),
        filter_kind="vault",
        offending_filters=offending_flags,
    )


def validate_search_filters(
    search_type: Literal["vault", "docs", "code"],
    *,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool | None = None,
    prefer: str | None = None,
    exclude_domains: list[str] | None = None,
    only_domains: list[str] | None = None,
    include_domains: list[str] | None = None,
) -> None:
    """Validate that the search filters match the requested search_type.

    Raises:
        InvalidPreferValueError: If the prefer option is invalid.
        InvalidFilterForSearchTypeError: If a filter is supplied that is
            incompatible with the search_type (including an unknown domain).
    """
    _validate_prefer(prefer)
    _validate_doc_type(doc_type)
    _validate_domains(
        exclude_domains=exclude_domains,
        only_domains=only_domains,
        include_domains=include_domains,
    )

    code_supplied, vault_supplied, glob_supplied, postproc_supplied = _supplied_filters(
        language=language,
        path=path,
        node_type=node_type,
        function_name=function_name,
        class_name=class_name,
        doc_type=doc_type,
        feature=feature,
        date=date,
        tag=tag,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        dedup_locales=dedup_locales,
        prefer=prefer,
        exclude_domains=exclude_domains,
        only_domains=only_domains,
        include_domains=include_domains,
    )

    if search_type != "code":
        _reject_code_filters_for_non_code(
            search_type, [*code_supplied, *glob_supplied, *postproc_supplied]
        )
    if search_type not in {"vault", "docs"}:
        _reject_vault_filters_for_non_vault(search_type, vault_supplied)
