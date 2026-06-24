"""Filter validation logic for vault and codebase search."""

from __future__ import annotations

from typing import Literal

# The vault doc types that carry semantic content and are searchable. ``index``
# is excluded: feature-index documents are auto-generated navigational
# document-lists with no semantic value. A doc-type filter may name one of these
# or a comma-separated union of them.
INDEXABLE_DOC_TYPES: frozenset[str] = frozenset(
    {"adr", "audit", "exec", "plan", "reference", "research"}
)


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


def _format_flags(names: list[str]) -> list[str]:
    flags: list[str] = []
    for name in names:
        flag = name.replace("_", "-")
        if not flag.startswith("--"):
            flag = f"--{flag}"
        flags.append(flag)
    return sorted(flags)


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
    dedup_locales: bool = False,
    prefer: str | None = None,
) -> None:
    """Validate that the search filters match the requested search_type.

    Raises:
        InvalidPreferValueError: If the prefer option is invalid.
        InvalidFilterForSearchTypeError: If a filter is supplied that is
            incompatible with the search_type.
    """
    if prefer is not None and prefer not in {"prod", "tests", "docs"}:
        raise InvalidPreferValueError(
            (
                "--prefer must be one of production, tests, or documentation; "
                f"got {prefer!r}."
            ),
            prefer_value=prefer,
        )

    if doc_type is not None:
        requested = [t.strip() for t in doc_type.split(",") if t.strip()]
        invalid = [t for t in requested if t not in INDEXABLE_DOC_TYPES]
        if invalid:
            allowed = ", ".join(sorted(INDEXABLE_DOC_TYPES))
            raise InvalidDocTypeError(
                (
                    f"doc-type must be one or a comma-separated union of: {allowed} "
                    f"(the auto-generated 'index' type is not searchable); "
                    f"got {', '.join(invalid)}."
                ),
                offending=invalid,
            )

    code_filter_fields = [
        ("language", language),
        ("path", path),
        ("node_type", node_type),
        ("function_name", function_name),
        ("class_name", class_name),
    ]
    vault_filter_fields = [
        ("doc_type", doc_type),
        ("feature", feature),
        ("date", date),
        ("tag", tag),
    ]

    code_filters_supplied = [
        name for name, val in code_filter_fields if val is not None
    ]
    vault_filters_supplied = [
        name for name, val in vault_filter_fields if val is not None
    ]

    glob_filters_supplied: list[str] = []
    if include_paths:
        glob_filters_supplied.append("include_path")
    if exclude_paths:
        glob_filters_supplied.append("exclude_path")

    postproc_supplied: list[str] = []
    if dedup_locales:
        postproc_supplied.append("dedup_locales")
    if prefer is not None:
        postproc_supplied.append("prefer")

    if search_type != "code":
        offending: list[str] = []
        offending.extend(code_filters_supplied)
        offending.extend(glob_filters_supplied)
        offending.extend(postproc_supplied)
        if offending:
            offending_flags = _format_flags(offending)
            raise InvalidFilterForSearchTypeError(
                f"code-search filters ({', '.join(sorted(offending_flags))}) require "
                f"--type code; got --type {search_type}.",
                filter_kind="code",
                offending_filters=offending_flags,
            )

    if search_type not in {"vault", "docs"} and vault_filters_supplied:
        offending_flags = _format_flags(vault_filters_supplied)
        raise InvalidFilterForSearchTypeError(
            (
                f"vault-search filters ({', '.join(sorted(offending_flags))}) "
                f"require --type vault; got --type {search_type}."
            ),
            filter_kind="vault",
            offending_filters=offending_flags,
        )
