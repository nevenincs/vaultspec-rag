"""Noise@k benchmark: verify the code-search noise profile lifts production.

Builds a controlled polyglot corpus where each production concept is shadowed by
a test mirror, a doc page, four locale variants, a vendored copy, a generated
file, and an agent worktree clone - the exact noise classes the
`search-noise-filtering` ADR targets. Indexes it with real GPU embeddings into a
real (local) Qdrant collection, then measures the fraction of each top-k page
that is non-production with the noise profile OFF (every domain re-admitted)
versus ON (the shipped default), asserting a material reduction.

Real model + real Qdrant per the testing mandate; no mocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._domain import classify_domain

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...search import VaultSearcher

pytestmark = [pytest.mark.performance]

# Production concepts; each becomes a prod module plus a full shadow of noise.
_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    (
        "auth",
        "authenticate_user",
        "validate a user credential and issue a session token",
    ),
    ("cache", "evict_expired_entries", "remove stale entries from the in-memory cache"),
    ("payment", "charge_credit_card", "capture a payment against a stored credit card"),
    ("search", "rank_results", "rank candidate documents by relevance score"),
    ("upload", "stream_file_chunks", "stream a large file upload in bounded chunks"),
    ("report", "aggregate_metrics", "aggregate request metrics into a summary report"),
)

_QUERIES: tuple[str, ...] = (
    "authenticate a user credential and issue a session token",
    "evict stale expired entries from the in-memory cache",
    "capture a payment charge against a stored credit card",
    "rank candidate documents by relevance score",
    "stream a large file upload in bounded chunks",
    "aggregate request metrics into a summary report",
)

_TOP_K = 10
_ALL_NOISE = ["tests", "docs", "locale", "generated", "vendored", "worktree"]


def _prod_module(name: str, func: str, summary: str) -> str:
    return (
        f'"""Production {name} module: {summary}."""\n\n\n'
        f"def {func}(request):\n"
        f'    """{summary}."""\n'
        f"    result = _{name}_core(request)\n"
        f"    return result\n\n\n"
        f"def _{name}_core(request):\n"
        f"    # {summary}\n"
        f"    return {{'ok': True, 'op': '{name}', 'detail': '{summary}'}}\n"
    )


def _test_module(name: str, func: str, summary: str) -> str:
    return (
        f'"""Tests for the {name} module: {summary}."""\n\n'
        f"from src.{name} import {func}\n\n\n"
        f"def test_{func}():\n"
        f"    # {summary}\n"
        f"    assert {func}({{'id': 1}})['ok'] is True\n"
    )


def _doc_page(name: str, func: str, summary: str) -> str:
    return (
        f"# {name} guide\n\n"
        f"The `{func}` function will {summary}. This document explains how to "
        f"{summary} and how the {name} subsystem behaves.\n"
    )


def _locale_yaml(name: str, summary: str, lang: str) -> str:
    return f'{name}_title: "{summary}"\n{name}_action: "{summary} ({lang})"\n'


def _build_corpus(root: Path) -> None:
    src = root / "src"
    tests = root / "tests"
    docs = root / "docs"
    locales = root / "locales"
    vendor = root / "vendor" / "thirdparty"
    generated = root / "src" / "proto"
    worktree = root / ".claude" / "worktrees" / "agent-1" / "src"
    for d in (src, tests, docs, locales, vendor, generated, worktree):
        d.mkdir(parents=True, exist_ok=True)

    for name, func, summary in _CONCEPTS:
        (src / f"{name}.py").write_text(
            _prod_module(name, func, summary), encoding="utf-8"
        )
        (tests / f"test_{name}.py").write_text(
            _test_module(name, func, summary), encoding="utf-8"
        )
        (docs / f"{name}.md").write_text(
            _doc_page(name, func, summary), encoding="utf-8"
        )
        # A vendored copy and a generated copy carry the same vocabulary.
        (vendor / f"{name}_vendored.py").write_text(
            _prod_module(name, func, summary), encoding="utf-8"
        )
        (generated / f"{name}_pb2.py").write_text(
            _prod_module(name, func, summary), encoding="utf-8"
        )
        # An agent worktree clone duplicates production verbatim (index-excluded).
        (worktree / f"{name}.py").write_text(
            _prod_module(name, func, summary), encoding="utf-8"
        )

    # Four near-identical locale variants of one i18n table.
    for name, _func, summary in _CONCEPTS:
        for lang in ("en", "es", "ca", "hu"):
            (locales / f"{lang}.yml").write_text(
                _locale_yaml(name, summary, lang), encoding="utf-8", errors="ignore"
            )
    # Rewrite locales so each lang file carries every concept (true parallel set).
    for lang in ("en", "es", "ca", "hu"):
        body = "".join(_locale_yaml(n, s, lang) for n, _f, s in _CONCEPTS)
        (locales / f"{lang}.yml").write_text(body, encoding="utf-8")


@pytest.fixture(scope="module")
def noise_searcher(
    embedding_model: EmbeddingModel,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[tuple[VaultSearcher, Path]]:
    import os

    from ... import CodebaseIndexer, VaultSearcher, VaultStore
    from ...config import reset_config
    from ...progress import NullProgressReporter

    # The noise policy (hide/demote/dedup) runs after rerank and is independent
    # of it; disabling the CrossEncoder keeps this benchmark deterministic and
    # sidesteps an intermittent Windows transformers model-load fault, while the
    # dense+sparse RRF ordering still drives a realistic candidate set.
    prev = os.environ.get("VAULTSPEC_RAG_RERANKER_ENABLED")
    os.environ["VAULTSPEC_RAG_RERANKER_ENABLED"] = "0"
    reset_config()
    root = tmp_path_factory.mktemp("noise-corpus")
    _build_corpus(root)
    store = VaultStore(root)
    CodebaseIndexer(root, embedding_model, store).full_index(
        reporter=NullProgressReporter()
    )
    searcher = VaultSearcher(root, embedding_model, store)
    yield searcher, root
    store.close()
    if prev is None:
        os.environ.pop("VAULTSPEC_RAG_RERANKER_ENABLED", None)
    else:
        os.environ["VAULTSPEC_RAG_RERANKER_ENABLED"] = prev
    reset_config()


# Domains the shipped profile hides outright (vendored is demoted, not hidden).
_HIDDEN = frozenset({"generated", "worktree"})


def _domain_tally(
    searcher: VaultSearcher,
    queries: tuple[str, ...],
    *,
    include_domains: list[str] | None = None,
    dedup_locales: bool | None = None,
) -> dict[str, int]:
    """Aggregate the domain composition of the top-k pages across queries."""
    tally: dict[str, int] = {}
    for q in queries:
        results = searcher.search_codebase(
            q,
            top_k=_TOP_K,
            include_domains=include_domains,
            dedup_locales=dedup_locales,
        )
        for r in results:
            domain = classify_domain(r.path)
            tally[domain] = tally.get(domain, 0) + 1
    return tally


def _noise_fraction(tally: dict[str, int]) -> float:
    total = sum(tally.values())
    prod = tally.get("prod", 0)
    return ((total - prod) / total) if total else 0.0


class TestNoiseAtK:
    def test_worktree_clones_never_indexed(
        self, noise_searcher: tuple[VaultSearcher, Path]
    ) -> None:
        searcher, _root = noise_searcher
        for q in _QUERIES:
            results = searcher.search_codebase(
                q, top_k=_TOP_K, include_domains=_ALL_NOISE, dedup_locales=False
            )
            assert not any("worktrees" in r.path for r in results), (
                "agent worktree clones must be excluded at index time"
            )

    def test_profile_reduces_noise_at_k(
        self, noise_searcher: tuple[VaultSearcher, Path]
    ) -> None:
        searcher, _root = noise_searcher
        # OFF: re-admit every noise domain and disable dedup -> unfiltered page.
        off_tally = _domain_tally(
            searcher, _QUERIES, include_domains=_ALL_NOISE, dedup_locales=False
        )
        # ON: shipped defaults (hide generated/vendored, demote tests/docs/locale,
        # dedup locales).
        on_tally = _domain_tally(searcher, _QUERIES)
        off = _noise_fraction(off_tally)
        on = _noise_fraction(on_tally)
        msg = f"on={on:.2f} off={off:.2f} on_tally={on_tally} off_tally={off_tally}"

        # The unfiltered page genuinely surfaces hidden-domain duplicates...
        off_hidden = sum(off_tally.get(d, 0) for d in _HIDDEN)
        assert off_hidden > 0, f"corpus did not exercise hidden domains: {msg}"
        # ...and the default profile removes every hidden-domain result entirely.
        on_hidden = sum(on_tally.get(d, 0) for d in _HIDDEN)
        assert on_hidden == 0, f"hidden domains leaked into results: {msg}"

        # Overall noise drops materially and production rises.
        assert on < off, f"profile did not reduce noise: {msg}"
        assert off - on >= 0.2, f"noise reduction too small: {msg}"
        assert on_tally.get("prod", 0) > off_tally.get("prod", 0), (
            f"production share did not rise: {msg}"
        )

    def test_only_domain_restricts_to_tests(
        self, noise_searcher: tuple[VaultSearcher, Path]
    ) -> None:
        searcher, _root = noise_searcher
        results = searcher.search_codebase(
            _QUERIES[0], top_k=_TOP_K, only_domains=["tests"]
        )
        assert results, "only:tests should still return the test mirrors"
        assert all(classify_domain(r.path) == "tests" for r in results)
