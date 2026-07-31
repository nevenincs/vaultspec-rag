"""Unit coverage for service search diagnostic payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_search_index_state_uses_selected_source_preflight_count() -> None:
    from ..server._routes_search import SearchIndexStateInput, _search_index_state

    state = _search_index_state(
        SearchIndexStateInput(
            indexed_count=37,
            requested_root="C:/work/project",
            search_type="codebase",
        )
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
    from ..server._routes_search import _empty_search_diagnostics

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
    from ..server._routes_search import _empty_search_diagnostics

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
    from ..server._routes_search import _empty_search_diagnostics

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
    from ..server._routes_search import _empty_search_diagnostics

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
    from ..server._routes_search import SearchIndexStateInput, _search_index_state

    state = _search_index_state(
        SearchIndexStateInput(
            indexed_count=4,
            requested_root="C:/work/project",
            search_type="codebase",
            published_points=421.0,
        )
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
    from ..server._routes_search import SearchIndexStateInput, _search_index_state

    state = _search_index_state(
        SearchIndexStateInput(
            indexed_count=4,
            requested_root="C:/work/project",
            search_type="codebase",
        )
    )

    assert "shortfall" not in state


def test_one_projection_backs_the_shortfall_block_on_both_search_paths() -> None:
    """The in-process path and the daemon must emit one block shape.

    The local search path builds its own envelope rather than reading the
    daemon's, so the two would drift the moment either spelled the keys for
    itself. Pinning both against the single projection is what makes the
    renderer's lookup safe on either surface.

    Proven able to fail: respelling ``live_count`` as ``held_count`` in
    ``BreadthShortfall.as_index_state_block`` fails this test on the literal
    block assertion below; restoring returns it to green. The daemon equality
    alone cannot carry that proof - both surfaces read the one projection, so
    a respelling moves them together and the comparison stays true. The
    literals are what pin the key names a renderer looks up.
    """
    from .._index_breadth import BreadthShortfall
    from ..server._routes_search import SearchIndexStateInput, _search_index_state

    block = BreadthShortfall(published=421, live=4).as_index_state_block()
    daemon_state = _search_index_state(
        SearchIndexStateInput(
            indexed_count=4,
            requested_root="C:/work/project",
            search_type="codebase",
            published_points=421.0,
        )
    )

    assert block == {
        "published_count": 421,
        "live_count": 4,
        "missing_count": 417,
    }
    assert block == daemon_state["shortfall"]


def test_the_daemon_route_renders_the_service_domain_index_state() -> None:
    """The route must own no part of the index-state shape.

    The block describes the service, not a rendering, so one builder settles
    it and every surface renders what it returns. A route that assembled its
    own would drift from the in-process path the moment either gained a
    field, and a renderer looking up that field would go quiet on whichever
    surface lacked it.

    Proven able to fail: having the route return a hand-built dict without
    ``status`` fails this test on the equality below; restoring the
    delegation returns it to green. The literal assertion is what carries the
    proof - comparing the two builders alone would stay true under a
    respelling that moved both.
    """
    from .._index_breadth import BreadthShortfall
    from .._search_state import BreadthFindings, search_index_state
    from ..server._routes_search import SearchIndexStateInput, _search_index_state

    routed = _search_index_state(
        SearchIndexStateInput(
            indexed_count=4,
            requested_root="C:/work/project",
            search_type="codebase",
            published_points=421.0,
        )
    )

    assert routed == search_index_state(
        indexed_count=4,
        requested_root="C:/work/project",
        search_type="codebase",
        findings=BreadthFindings(shortfall=BreadthShortfall(published=421, live=4)),
    )
    assert set(routed) == {
        "source",
        "indexed_count",
        "indexed_target_root",
        "requested_target_root",
        "target_matches",
        "status",
        "shortfall",
    }


def test_the_daemon_route_carries_the_integrity_verdict_verbatim() -> None:
    """The route renders the service-domain integrity block, owning no key.

    The verdict is settled by one evaluator and projected by one method, so
    the route must pass it through untouched: a route that respelled or
    filtered the block would show the daemon surface a different verdict
    vocabulary than the in-process path renders.

    Proven able to fail: neutering the classification (tolerance widened to
    infinity) fails the shrunken-direction tests on their verdict assertions,
    and dropping the ``integrity=input.integrity`` pass-through fails this
    test on the block lookup below, not on a setup error.
    """
    from .._index_integrity import IndexIntegrity
    from ..server._routes_search import SearchIndexStateInput, _search_index_state

    verdict = IndexIntegrity(
        verdict="shrunken",
        source="code",
        claimed_count=421,
        live_count=4,
        generation_id="generation-route",
        reason=None,
    )
    state = _search_index_state(
        SearchIndexStateInput(
            indexed_count=4,
            requested_root="C:/work/project",
            search_type="codebase",
            integrity=verdict,
        )
    )

    # The literal block pins the key names a renderer looks up on the daemon
    # surface; comparing against as_block() alone would move with a respelling.
    assert state["index_integrity"] == {
        "verdict": "shrunken",
        "source": "code",
        "claimed_count": 421,
        "live_count": 4,
        "generation_id": "generation-route",
        "reason": None,
        "missing_count": 417,
    }


def test_the_search_summary_names_a_demonstrated_shortfall() -> None:
    """An adapter reading only the summary must still learn the index is short.

    The Model Context Protocol surface hands an agent the summary as the
    sentence describing the answer. Leaving the deficit solely in a nested
    field lets that sentence report a confident count over an index known to
    be missing points, which is the reading the completeness signal exists to
    prevent.

    Proven able to fail: returning ``found`` unconditionally from
    ``search_summary`` fails this test on the shortfall-figure assertion
    below, not on a crash; restoring returns it to green. Its companion pins
    the opposite direction, so neither passes on a constant string.
    """
    from ..server._routes import search_summary

    summary = search_summary(
        5,
        {"shortfall": {"published_count": 421, "live_count": 4, "missing_count": 417}},
    )

    assert "Found 5 relevant items." in summary
    assert "4 of the 421 sections" in summary
    assert "not evidence that no such code exists" in summary


def test_the_search_summary_names_a_file_breadth_shortfall() -> None:
    """The deficit a point count cannot express must reach the summary too.

    A publication covering a fraction of the files it names still stamps a
    self-consistent point count, so this is exactly the case the point
    comparison is blind to. The summary named the point shortfall alone and
    returned an unqualified count here, while the command line warned - so the
    agent-facing surface was the one consumer that never learned.

    Proven able to fail: restricting ``search_summary`` to the ``shortfall``
    key fails this test on the deficit assertion below, not on a crash;
    restoring the shared walker returns it to green.
    """
    from ..server._routes import search_summary

    summary = search_summary(
        5,
        {
            "file_shortfall": {
                "named_count": 442,
                "covered_count": 27,
                "missing_count": 415,
            }
        },
    )

    assert "Found 5 relevant items." in summary
    assert "names 442 files but holds content for only 27" in summary
    assert "not evidence that no such code exists" in summary


def test_both_shortfall_kinds_reach_the_summary_together() -> None:
    """Neither deficit may mask the other; the summary carries both.

    Proven able to fail: returning after the first warning in
    ``shortfall_warnings`` fails this test on the file-deficit assertion,
    while its point-deficit companion above stays green.
    """
    from ..server._routes import search_summary

    summary = search_summary(
        5,
        {
            "shortfall": {
                "published_count": 421,
                "live_count": 4,
                "missing_count": 417,
            },
            "file_shortfall": {
                "named_count": 442,
                "covered_count": 27,
                "missing_count": 415,
            },
        },
    )

    assert "4 of the 421 sections" in summary
    assert "names 442 files but holds content for only 27" in summary


def test_the_search_summary_stays_plain_over_an_index_with_no_shortfall() -> None:
    """A complete or unknowable index must not carry a warning.

    Warning whenever breadth cannot be established would fire on every root
    written by a build that recorded none, which trains the reader to skip the
    sentence that matters.

    Proven able to fail: making the warning unconditional in
    ``search_summary`` fails this test on the equality below; restoring
    returns it to green.
    """
    from ..server._routes import search_summary

    assert search_summary(5, {}) == "Found 5 relevant items."


def test_the_mcp_output_model_preserves_the_shortfall_summary() -> None:
    """The agent-facing surface must carry the warning the operator surface prints.

    The command line renders the deficit as its own warning block. The Model
    Context Protocol surface has no renderer, so the same fact has to survive
    output-model validation on the envelope itself or the agent is the one
    consumer that never learns the index is incomplete.

    Proven able to fail: declaring ``model_config = ConfigDict(extra="ignore")``
    on ``SearchResults`` fails this test on the ``index_state`` lookup below;
    restoring ``extra="allow"`` returns it to green.
    """
    from ..mcp._tools import SearchResults

    envelope: dict[str, object] = {
        "results": [],
        "summary": (
            "Found 0 relevant items. Warning: this index holds 4 of the 421 "
            "sections it published, so an absent result is not evidence that "
            "no such code exists."
        ),
        "index_state": {
            "shortfall": {
                "published_count": 421,
                "live_count": 4,
                "missing_count": 417,
            }
        },
    }

    validated = SearchResults.model_validate(envelope).model_dump()

    assert "4 of the 421 sections" in str(validated["summary"])
    index_state = cast("dict[str, object]", validated["index_state"])
    assert index_state["shortfall"] == {
        "published_count": 421,
        "live_count": 4,
        "missing_count": 417,
    }


def test_a_path_filter_note_survives_classification_into_the_empty_block(
    tmp_path: Path,
) -> None:
    """The note the search recorded must reach the envelope's empty block.

    Availability classification stands between the two. It returns a fresh body
    on the unavailable path, so a note carried on the searched body is exactly
    the kind of thing that can be dropped in transit without any test noticing.
    """
    from ..server._routes_search import (
        SearchAvailabilityRequestFacts,
        _classify_search_result,
    )

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
        SearchAvailabilityRequestFacts(
            job_snapshot_before=[],
            root=tmp_path,
            source="code",
            request_id="0" * 32,
            port=8766,
        ),
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
