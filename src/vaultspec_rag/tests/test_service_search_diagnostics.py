"""Unit coverage for service search diagnostic payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path


def test_search_index_state_uses_selected_source_preflight_count() -> None:
    from ..server._routes import _search_index_state

    state = _search_index_state(
        indexed_count=37,
        requested_root="C:/work/project",
        search_type="codebase",
    )

    assert state == {
        "source": "code",
        "indexed_count": 37,
        "indexed_target_root": "C:/work/project",
        "requested_target_root": "C:/work/project",
        "target_matches": True,
        "status": "available",
    }


def test_empty_search_diagnostics_use_supported_jobs_filter() -> None:
    from ..server._routes import _empty_search_diagnostics

    diagnostics = _empty_search_diagnostics(
        {
            "source": "code",
            "indexed_count": 0,
        },
        port=8766,
    )

    remediation = cast("list[object]", diagnostics["remediation"])
    assert isinstance(remediation, list)
    assert "vaultspec-rag server jobs --state active --port 8766" in remediation
    assert all("--running" not in str(item) for item in remediation)


def test_empty_search_diagnostics_name_the_path_filter_that_emptied_the_page() -> None:
    """An emptied page must say the path filter did it, and name the pattern.

    Without this the envelope reported a plain no-match, which reads as "the
    query found nothing" and sends the reader off tuning the query while a
    pattern that matches no indexed path sits in the command.
    """
    from ..server._routes import _empty_search_diagnostics

    diagnostics = _empty_search_diagnostics(
        {
            "source": "code",
            "indexed_count": 1284,
        },
        port=8766,
        path_filter={
            "patterns": ["src/vaultspec_rag/indexr/**"],
            "candidates_before_filter": 50,
        },
    )

    # Asserting the reason as well as the sentence: several branches render a
    # message, and a substring match on prose alone would pass whichever fired.
    assert diagnostics["reason"] == "no_match_path_filter"
    message = str(diagnostics["message"])
    assert "src/vaultspec_rag/indexr/**" in message
    assert "50 indexed items matched the query" in message


def test_empty_search_diagnostics_stay_a_plain_no_match_without_a_path_filter() -> None:
    from ..server._routes import _empty_search_diagnostics

    diagnostics = _empty_search_diagnostics(
        {
            "source": "code",
            "indexed_count": 1284,
        },
        port=8766,
    )

    assert diagnostics["reason"] == "no_match"


def test_an_empty_index_outranks_a_path_filter_explanation() -> None:
    """With nothing indexed, the path filter is not the actionable cause."""
    from ..server._routes import _empty_search_diagnostics

    diagnostics = _empty_search_diagnostics(
        {
            "source": "code",
            "indexed_count": 0,
        },
        port=8766,
        path_filter={"patterns": ["src/**"], "candidates_before_filter": 0},
    )

    assert diagnostics["reason"] == "index_missing"


def test_search_index_state_carries_a_published_breadth_shortfall() -> None:
    """A short collection must reach the adapters as a settled conclusion.

    The service decides completeness once and carries the figures, so no
    adapter compares counts for itself. Asserting the whole block, not just
    its presence, pins the figures a renderer names: a deficit reported
    without them tells an operator nothing to act on.

    Proven able to fail: inverting the emission guard to
    ``if published_points is None`` drops the block and fails this test on the
    shortfall lookup below, not on a setup error; restoring returns it to
    green. Its companion pins the opposite direction under a different
    mutation, so neither can pass on a constant.
    """
    from ..server._routes import _search_index_state

    state = _search_index_state(
        indexed_count=4,
        requested_root="C:/work/project",
        search_type="codebase",
        published_points=421.0,
    )

    assert state["shortfall"] == {
        "published_count": 421,
        "live_count": 4,
        "missing_count": 417,
    }
    assert state["indexed_count"] == 4
    assert state["status"] == "available"


def test_search_index_state_omits_the_shortfall_when_breadth_is_unknown() -> None:
    """No published figure is "cannot tell", never a shortfall.

    A root written by a build that recorded no breadth has nothing to compare
    against. Emitting a shortfall here would warn on every such root and train
    the reader to ignore the warning.

    Proven able to fail: making the emission unconditional - ``if True`` with
    ``int(published_points or 0)`` - fails this test on the assertion below,
    not on a crash; restoring returns it to green. The inverted-guard mutation
    was rejected as the proof for this test because it fails inside the
    production call instead of on the assertion, which proves the branch
    raises, not that the test is watching it.
    """
    from ..server._routes import _search_index_state

    state = _search_index_state(
        indexed_count=4,
        requested_root="C:/work/project",
        search_type="codebase",
    )

    assert "shortfall" not in state


def test_a_path_filter_note_survives_classification_into_the_empty_block(
    tmp_path: Path,
) -> None:
    """The note the search recorded must reach the envelope's empty block.

    Availability classification stands between the two. It returns a fresh body
    on the unavailable path, so a note carried on the searched body is exactly
    the kind of thing that can be dropped in transit without any test noticing.
    """
    from ..server._routes import _classify_search_result

    searched: dict[str, object] = {
        "results": [],
        "index_state": {
            "source": "code",
            "indexed_count": 1284,
            "indexed_target_root": str(tmp_path),
            "requested_target_root": str(tmp_path),
            "target_matches": True,
            "status": "available",
        },
        "path_filter": {
            "patterns": ["src/vaultspec_rag/indexr/**"],
            "candidates_before_filter": 50,
        },
    }

    classification = _classify_search_result(
        searched,
        job_snapshot_before=[],
        root=tmp_path,
        source="code",
        request_id="0" * 32,
        port=8766,
    )

    assert classification.status_code == 200
    empty = cast("dict[str, object]", classification.response["empty"])
    # Asserting the reason, not the prose: every empty page renders a message,
    # and a substring match would pass on whichever branch happened to fire.
    assert empty["reason"] == "no_match_path_filter"
    assert "src/vaultspec_rag/indexr/**" in str(empty["message"])


def test_the_mcp_output_model_preserves_the_path_filter_diagnostic() -> None:
    """The MCP tools must hand the agent the same diagnostic the CLI renders.

    Both adapters read one service envelope, but the MCP surface validates it
    through a declared output model on the way out. A model that dropped the
    unlisted diagnostic fields would leave agents with a bare empty result and
    no way to tell a path-filter mistake from a query that matched nothing.
    """
    from ..mcp._tools import SearchResults

    envelope: dict[str, object] = {
        "results": [],
        "summary": "Found 0 relevant items.",
        "path_filter": {
            "patterns": ["src/vaultspec_rag/indexr/**"],
            "candidates_before_filter": 50,
        },
        "empty": {
            "reason": "no_match_path_filter",
            "message": "50 indexed items matched the query, and the path filter "
            "(src/vaultspec_rag/indexr/**) excluded every one.",
            "remediation": ["rerun without the path filter"],
        },
    }

    validated = SearchResults.model_validate(envelope).model_dump()

    assert validated["results"] == []
    empty = cast("dict[str, object]", validated["empty"])
    assert empty["reason"] == "no_match_path_filter"
    path_filter = cast("dict[str, object]", validated["path_filter"])
    assert path_filter["patterns"] == ["src/vaultspec_rag/indexr/**"]
