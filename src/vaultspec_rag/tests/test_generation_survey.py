"""Detection of superseded code generations, and what it refuses to report."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from ..storage_survey import NamespaceSurvey

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


class TestNamesResolveThroughThePointer:
    """No caller may derive a code collection name the pointer has superseded."""

    def test_migrate_reads_the_served_collection_not_the_derived_one(
        self, tmp_path: Path
    ) -> None:
        """Migration must copy what the root serves, or it copies nothing.

        A root that has published a rebuild serves ``<derived>_g<generation>``.
        Keying the source map on the derived name copies a superseded
        generation, or - when the base never existed - silently migrates no
        code at all while reporting success.

        Proven able to fail: returning ``derived`` unconditionally from the
        ``_source`` helper restores the derived key and fails the source-name
        assertion below.
        """
        from .._store_models import publish_served_code_collection
        from ..cli._service_storage import _migrate_name_map
        from ..store_schema import CODE_COLLECTION

        publish_served_code_collection(tmp_path, f"{CODE_COLLECTION}_gserved")
        name_map = _migrate_name_map(str(tmp_path), to_server=True)

        assert f"{CODE_COLLECTION}_gserved" in name_map
        assert CODE_COLLECTION not in name_map
        # The target stays the derived base: the destination has no pointer, so
        # landing there is served immediately without carrying generation
        # history across.
        assert name_map[f"{CODE_COLLECTION}_gserved"].endswith(CODE_COLLECTION)

    def test_migrate_leaves_other_kinds_on_their_derived_names(
        self, tmp_path: Path
    ) -> None:
        """Only the code kind has a pointer; the rest must be untouched.

        Proven able to fail: dropping the kind check in ``_source`` resolves
        every kind through the code pointer and fails this.
        """
        from .._store_models import publish_served_code_collection
        from ..cli._service_storage import _migrate_name_map
        from ..store_schema import VAULT_COLLECTION

        publish_served_code_collection(tmp_path, "codebase_docs_gserved")
        name_map = _migrate_name_map(str(tmp_path), to_server=True)

        assert VAULT_COLLECTION in name_map

    def test_a_donor_is_consulted_at_the_collection_it_serves(
        self, tmp_path: Path
    ) -> None:
        """Reuse must read the donor's served collection, not a guessed name.

        Proven able to fail: returning ``derived`` unconditionally from
        ``_served_donor_collection`` fails the served-name assertion.
        """
        from .._store_models import publish_served_code_collection
        from ..indexer._donor_candidates import (
            CollectionKind,
            _served_donor_collection,
        )

        publish_served_code_collection(tmp_path, "rabc_codebase_docs_gserved")

        assert (
            _served_donor_collection(
                str(tmp_path), CollectionKind.CODE, "rabc_codebase_docs"
            )
            == "rabc_codebase_docs_gserved"
        )

    def test_a_donor_with_no_recorded_root_falls_back_to_the_derived_name(
        self,
    ) -> None:
        """An unresolvable donor must not invent a collection.

        The derived name either appears in that donor's recorded collections,
        so reuse proceeds against real data, or it does not and the donor is
        skipped. Neither outcome fabricates a target.
        """
        from ..indexer._donor_candidates import (
            CollectionKind,
            _served_donor_collection,
        )

        assert (
            _served_donor_collection(None, CollectionKind.CODE, "rabc_codebase_docs")
            == "rabc_codebase_docs"
        )


def _namespace_of(payload: dict[str, object], root: str | None) -> dict[str, object]:
    """Return the one namespace entry the shaped payload holds for *root*."""
    namespaces = cast("list[dict[str, object]]", payload["namespaces"])
    return next(item for item in namespaces if item["root"] == root)


def _shape(surveys: list[NamespaceSurvey]) -> dict[str, object]:
    """Shape *surveys* through the real route shaper, unfiltered."""
    from ..server._routes_storage import _shape_survey_payload

    return _shape_survey_payload(
        surveys,
        None,
        10,
        None,
        computed_at="2026-07-25T00:00:00+00:00",
        source="fresh",
    )


class TestGenerationDebtInTheSurveyPayload:
    """The route reports generation debt per namespace, and withholds guesses."""

    def test_a_superseded_generation_is_named_in_the_payload(
        self, tmp_path: Path
    ) -> None:
        """An operator reading the survey can see what the rebuild left behind."""
        from .._store_models import publish_served_code_collection
        from ..storage_survey import NamespaceSurvey

        root = str(tmp_path)
        publish_served_code_collection(tmp_path, f"{_DERIVED}_gnew")
        survey = NamespaceSurvey(
            prefix="r0123456789ab_",
            root=root,
            status="live",
            collections=[f"{_DERIVED}_gold", f"{_DERIVED}_gnew"],
        )

        namespace = _namespace_of(_shape([survey]), root)

        assert namespace["served_code_collection"] == f"{_DERIVED}_gnew"
        assert namespace["unreferenced_generations"] == [f"{_DERIVED}_gold"]

    def test_an_unreadable_pointer_reports_null_not_an_empty_debt_list(
        self, tmp_path: Path
    ) -> None:
        """An illegible pointer must not read as a clean bill of health.

        ``None`` says nothing is known about this root; ``[]`` would say the
        root is carrying nothing, which is the claim that invites a later
        reclamation pass to drop a live served collection. This is the same
        distinction ``ServedPointer.verifiable`` draws, carried out to the
        response so an adapter cannot quietly collapse it.

        Proven able to fail: returning ``{"unreferenced_generations": []}``
        from the ``report is None`` branch of ``_generation_fields`` passes an
        ``== []`` assertion and fails the ``is None`` assertion below.
        """
        from .._store_models import served_code_pointer_path
        from ..storage_survey import NamespaceSurvey

        root = str(tmp_path)
        path = served_code_pointer_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        survey = NamespaceSurvey(
            prefix="r0123456789ab_",
            root=root,
            status="live",
            collections=[f"{_DERIVED}_gold"],
        )

        namespace = _namespace_of(_shape([survey]), root)

        assert namespace["served_code_collection"] is None
        assert namespace["unreferenced_generations"] is None

    def test_an_unattributable_namespace_claims_no_generations(self) -> None:
        """A namespace with no root has no pointer to resolve, so it reports none."""
        from ..storage_survey import NamespaceSurvey

        survey = NamespaceSurvey(
            prefix="r0123456789ab_",
            root=None,
            status="unknown",
            collections=[f"{_DERIVED}_gold"],
        )

        namespace = _namespace_of(_shape([survey]), None)

        assert namespace["served_code_collection"] is None
        assert namespace["unreferenced_generations"] is None
