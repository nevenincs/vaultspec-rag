"""Unit coverage for service search diagnostic payloads."""

from __future__ import annotations

from typing import cast


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
