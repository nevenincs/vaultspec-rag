"""Per-intent persona ranking testimonials against the real vault.

Extends the scripted-persona discipline of ``test_cli_ux_testimonial`` to search
ranking: one persona per intent issues a realistic live query against a real GPU
index of the project vault and records a structured verdict against an authority
document declared *before* the search runs. Because the expectation is
pre-committed (not read off the retriever's output), a satisfied verdict is
evidence, and a failing one carries the full ranked list for diagnosis.

The searches run in the shared bounded worker (see ``_frozen_corpus_evidence``),
which declares the personas and their authorities and reports only what it
observed; the verdicts are reached here. The recorded testimonials are the
human-credible qualitative gate; the assertions are the machine gate. They are
the same data viewed two ways.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from ._frozen_corpus_evidence import TESTIMONIAL_TOP_K

if TYPE_CHECKING:
    from ._frozen_corpus_evidence import FrozenCorpusEvidence, TestimonialEvidence

pytestmark = [pytest.mark.integration, pytest.mark.quality]

_SATISFIED_RANK = 3


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


def _testimonial(observed: TestimonialEvidence) -> _Testimonial:
    """Reach a verdict on one persona's observed ranking."""
    observed_top = observed["observed_top"]
    expected_authority = observed["expected_authority"]
    if expected_authority not in observed_top:
        verdict, note = "off-topic", "expected authority absent from the top results"
    elif observed_top.index(expected_authority) < _SATISFIED_RANK:
        verdict, note = "satisfied", "expected authority led the results"
    else:
        verdict, note = "wrong-role", "expected authority present but ranked low"
    return _Testimonial(
        persona=observed["persona"],
        intent=observed["intent"],
        query=observed["query"],
        expected_authority=expected_authority,
        observed_top=observed_top,
        verdict=verdict,
        note=note,
    )


class TestRankingTestimonials:
    """Each persona's pre-declared authority must lead its query."""

    def test_personas_are_satisfied(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        observations = frozen_corpus_evidence["testimonials"]
        assert observations, "the persona scenario set must not be empty"
        testimonials = [_testimonial(observed) for observed in observations]
        unsatisfied = [t for t in testimonials if t.verdict != "satisfied"]
        assert not unsatisfied, "\n".join(
            f"[{t.persona} / {t.intent}] {t.verdict}: {t.note}\n"
            f"  query: {t.query}\n"
            f"  expected: {t.expected_authority}\n"
            f"  observed top {TESTIMONIAL_TOP_K}: {t.observed_top}"
            for t in unsatisfied
        )
