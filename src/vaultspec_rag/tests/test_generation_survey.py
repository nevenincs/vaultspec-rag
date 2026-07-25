"""Detection of superseded code generations, and what it refuses to report."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DERIVED = "r0123456789ab_codebase_docs"


class TestGenerationSurvey:
    """Report what a root serves and what it has left behind - and nothing else."""

    def test_a_superseded_generation_is_reported_as_unreferenced(
        self, tmp_path: Path
    ) -> None:
        """The collection the pointer left behind is what an operator needs named.

        Proven able to fail: dropping the ``name != served`` term reports the
        served collection as unreferenced and fails the served assertion below.
        """
        from .._store_models import publish_served_code_collection
        from ..generation_survey import survey_generations

        publish_served_code_collection(tmp_path, f"{_DERIVED}_gnew")
        reports = survey_generations(
            {str(tmp_path): _DERIVED},
            [_DERIVED, f"{_DERIVED}_gold", f"{_DERIVED}_gnew"],
        )

        assert len(reports) == 1
        assert reports[0].served == f"{_DERIVED}_gnew"
        assert reports[0].unreferenced == (f"{_DERIVED}_gold",)
        assert reports[0].has_debt is True

    def test_a_root_that_never_published_carries_no_debt(self, tmp_path: Path) -> None:
        """No pointer means the derived name serves, and nothing is stranded."""
        from ..generation_survey import survey_generations

        reports = survey_generations({str(tmp_path): _DERIVED}, [_DERIVED])

        assert reports[0].served == _DERIVED
        assert reports[0].unreferenced == ()
        assert reports[0].has_debt is False

    def test_the_derived_collection_is_never_called_unreferenced(
        self, tmp_path: Path
    ) -> None:
        """The base name is not a generation, so it is never reclamation debt.

        A root between publications is served by it. Listing it as unreferenced
        would nominate the live index for removal.

        Proven able to fail: dropping the ``_is_generation_collection`` term
        reports the derived name and fails the equality below.
        """
        from .._store_models import publish_served_code_collection
        from ..generation_survey import survey_generations

        publish_served_code_collection(tmp_path, f"{_DERIVED}_gnew")
        reports = survey_generations(
            {str(tmp_path): _DERIVED}, [_DERIVED, f"{_DERIVED}_gnew"]
        )

        assert reports[0].unreferenced == ()

    def test_another_roots_generation_is_never_claimed(self, tmp_path: Path) -> None:
        """Debt is per root; a foreign prefix must never be attributed here."""
        from ..generation_survey import survey_generations

        foreign = "rffffffffffff_codebase_docs_gother"
        reports = survey_generations({str(tmp_path): _DERIVED}, [_DERIVED, foreign])

        assert reports[0].unreferenced == ()

    def test_a_root_with_an_unreadable_pointer_is_omitted(self, tmp_path: Path) -> None:
        """An illegible pointer is not evidence that nothing points anywhere.

        Reporting this root's generations as unreferenced would be the first
        step toward deleting a live index on the strength of an offline share
        or a permissions blip.

        Proven able to fail: dropping the ``if not pointer.verifiable: continue``
        guard emits a report for this root and fails the emptiness assertion.
        """
        from .._store_models import served_code_pointer_path
        from ..generation_survey import survey_generations

        path = served_code_pointer_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")

        reports = survey_generations(
            {str(tmp_path): _DERIVED}, [_DERIVED, f"{_DERIVED}_gold"]
        )

        assert reports == ()
