"""Immutable construction controls and per-domain search option values.

Owns the typed keyword surfaces and their resolved values shared by search
orchestration. Result models and filter validation live in their own modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from sentence_transformers import CrossEncoder
    from vaultspec_core.graph import VaultGraph


class VaultSearcherConfigurationArguments(TypedDict, total=False):
    """Named construction controls retained by the searcher boundary."""

    graph_ttl_seconds: float | None
    graph_provider: Callable[[], VaultGraph | None] | None
    gpu_lock: threading.Lock | None
    reranker: CrossEncoder | None
    local_files_only: bool


@dataclass(frozen=True, slots=True)
class VaultSearcherConfiguration:
    """Immutable dependencies and controls for one searcher instance."""

    graph_ttl_seconds: float | None = None
    graph_provider: Callable[[], VaultGraph | None] | None = None
    gpu_lock: threading.Lock | None = None
    reranker: CrossEncoder | None = None
    local_files_only: bool = False


class VaultSearchOptionArguments(TypedDict, total=False):
    """Named vault filters accepted by the stable direct-search surface."""

    doc_type: str | None
    feature: str | None
    date: str | None
    tag: str | None
    intent: str | None
    like_ids: list[str | int] | None
    unlike_ids: list[str | int] | None


@dataclass(frozen=True, slots=True)
class VaultSearchOptions:
    """Immutable optional controls for a vault search."""

    doc_type: str | None = None
    feature: str | None = None
    date: str | None = None
    tag: str | None = None
    intent: str | None = None
    like_ids: list[str | int] | None = None
    unlike_ids: list[str | int] | None = None


class CodebaseSearchOptionArguments(TypedDict, total=False):
    """Named codebase filters accepted by the stable direct-search surface."""

    language: str | None
    path: str | None
    node_type: str | None
    function_name: str | None
    class_name: str | None
    include_paths: list[str] | None
    exclude_paths: list[str] | None
    dedup_locales: bool | None
    prefer: str | None
    exclude_domains: list[str] | None
    only_domains: list[str] | None
    include_domains: list[str] | None
    like_ids: list[str | int] | None
    unlike_ids: list[str | int] | None
    notes: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class CodebaseSearchOptions:
    """Immutable optional controls for a codebase search."""

    language: str | None = None
    path: str | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    dedup_locales: bool | None = None
    prefer: str | None = None
    exclude_domains: list[str] | None = None
    only_domains: list[str] | None = None
    include_domains: list[str] | None = None
    like_ids: list[str | int] | None = None
    unlike_ids: list[str | int] | None = None
    notes: dict[str, object] | None = None


class DocumentSearchOptionArguments(TypedDict, total=False):
    """Named document filters accepted by the stable direct-search surface."""

    source_path: str | None
    extractor_id: str | None
    extractor_version: str | None
    locator_kind: str | None


@dataclass(frozen=True, slots=True)
class DocumentSearchOptions:
    """Immutable optional controls for a document search."""

    source_path: str | None = None
    extractor_id: str | None = None
    extractor_version: str | None = None
    locator_kind: str | None = None


class CombinedSearchOptionArguments(
    VaultSearchOptionArguments,
    CodebaseSearchOptionArguments,
    DocumentSearchOptionArguments,
):
    """Named filters accepted by the stable combined-search surface."""


@dataclass(frozen=True, slots=True)
class CombinedSearchOptions:
    """Per-domain optional controls for one combined search."""

    vault: VaultSearchOptions = VaultSearchOptions()
    codebase: CodebaseSearchOptions = CodebaseSearchOptions()
    document: DocumentSearchOptions = DocumentSearchOptions()

    @classmethod
    def from_arguments(
        cls, arguments: CombinedSearchOptionArguments
    ) -> CombinedSearchOptions:
        """Partition the stable flat surface into domain-owned option values."""
        return cls(
            vault=VaultSearchOptions(
                doc_type=arguments.get("doc_type"),
                feature=arguments.get("feature"),
                date=arguments.get("date"),
                tag=arguments.get("tag"),
                intent=arguments.get("intent"),
            ),
            codebase=CodebaseSearchOptions(
                language=arguments.get("language"),
                path=arguments.get("path"),
                node_type=arguments.get("node_type"),
                function_name=arguments.get("function_name"),
                class_name=arguments.get("class_name"),
                include_paths=arguments.get("include_paths"),
                exclude_paths=arguments.get("exclude_paths"),
                dedup_locales=arguments.get("dedup_locales"),
                prefer=arguments.get("prefer"),
                exclude_domains=arguments.get("exclude_domains"),
                only_domains=arguments.get("only_domains"),
                include_domains=arguments.get("include_domains"),
            ),
            document=DocumentSearchOptions(
                source_path=arguments.get("source_path"),
                extractor_id=arguments.get("extractor_id"),
                extractor_version=arguments.get("extractor_version"),
                locator_kind=arguments.get("locator_kind"),
            ),
        )
