"""Per-intent persona ranking testimonials against the real vault.

Extends the scripted-persona discipline of ``test_cli_ux_testimonial`` to search
ranking: one persona per intent issues a realistic live query against a real GPU
index of the project vault and records a structured verdict against an authority
document declared *before* the search runs. Because the expectation is
pre-committed (not read off the retriever's output), a satisfied verdict is
evidence, and a failing one carries the full ranked list for diagnosis.

The recorded testimonials are the human-credible qualitative gate the ADR's D8
calls for; the assertions are the machine gate. They are the same data viewed
two ways.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from ... import VaultSearcher
    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.quality]

_TOP_K = 5
_SATISFIED_RANK = 3


@dataclass
class _Scenario:
    """A persona's pre-declared search expectation."""

    persona: str
    intent: str
    query: str
    expected_authority: str  # doc_id that should lead for this persona


@dataclass
class _Testimonial:
    """The recorded outcome of running a scenario against the live index."""

    persona: str
    intent: str
    query: str
    expected_authority: str
    observed_top: list[str]
    verdict: str
    note: str = field(default="")


# Personas map one-to-one to intents. Each expected_authority is the document
# the persona expects to lead, declared before any search runs.
_SCENARIOS: list[_Scenario] = [
    _Scenario(
        persona="orienting newcomer",
        intent="orientation",
        query="decision on gpu lock scope",
        expected_authority="adr/2026-06-12-service-concurrency-adr",
    ),
    _Scenario(
        persona="orienting newcomer",
        intent="orientation",
        query="qdrant server mode with provisioned binary verification",
        expected_authority="adr/2026-06-12-qdrant-server-provisioning-adr",
    ),
    _Scenario(
        persona="debugging maintainer",
        intent="debugging",
        query="narrow the gpu lock to model forward calls in the search path",
        expected_authority=(
            "exec/2026-06-12-service-concurrency/"
            "2026-06-12-service-concurrency-W03-P06-S15"
        ),
    ),
]


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".vault").is_dir():
            return parent
    msg = "could not locate project .vault/ above the test module"
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
def testimonial_searcher(
    embedding_model: EmbeddingModel,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[VaultSearcher]:
    """Index a hermetic copy of the project vault and yield a searcher."""
    from ... import VaultSearcher
    from ..conftest import _index_corpus

    root = tmp_path_factory.mktemp("testimonial-vault")
    shutil.copytree(
        _repo_root() / ".vault",
        root / ".vault",
        ignore=shutil.ignore_patterns("data", "*.lock"),
    )
    (root / ".vaultspec").mkdir(parents=True, exist_ok=True)
    components = _index_corpus(root, embedding_model)
    searcher = VaultSearcher(root, components["model"], components["store"])
    try:
        yield searcher
    finally:
        components["store"].close()


def _run_scenario(searcher: VaultSearcher, scenario: _Scenario) -> _Testimonial:
    results = searcher.search_vault(
        scenario.query, top_k=_TOP_K, intent=scenario.intent
    )
    observed = [r.id for r in results]
    if scenario.expected_authority not in observed:
        verdict, note = "off-topic", "expected authority absent from the top results"
    elif observed.index(scenario.expected_authority) < _SATISFIED_RANK:
        verdict, note = "satisfied", "expected authority led the results"
    else:
        verdict, note = "wrong-role", "expected authority present but ranked low"
    return _Testimonial(
        persona=scenario.persona,
        intent=scenario.intent,
        query=scenario.query,
        expected_authority=scenario.expected_authority,
        observed_top=observed,
        verdict=verdict,
        note=note,
    )


class TestRankingTestimonials:
    """Each persona's pre-declared authority must lead its query."""

    def test_personas_are_satisfied(self, testimonial_searcher: VaultSearcher) -> None:
        testimonials = [_run_scenario(testimonial_searcher, s) for s in _SCENARIOS]
        unsatisfied = [t for t in testimonials if t.verdict != "satisfied"]
        assert not unsatisfied, "\n".join(
            f"[{t.persona} / {t.intent}] {t.verdict}: {t.note}\n"
            f"  query: {t.query}\n"
            f"  expected: {t.expected_authority}\n"
            f"  observed top {_TOP_K}: {t.observed_top}"
            for t in unsatisfied
        )
