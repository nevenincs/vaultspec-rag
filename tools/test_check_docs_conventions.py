"""Guard tests for the manual-conventions gate.

Each test below builds a throwaway markdown fixture, so the gate is proven to
SEE the shape it claims to catch on synthetic input, never merely that it
runs clean against the live tree. Every assertion here was run against a
broken form of the checked function - observed to fail on the named
assertion - and against a fixed form - observed to pass - in one
uninterrupted sequence before being committed.
"""

from __future__ import annotations

import pytest

from . import check_docs_conventions as gate

pytestmark = [pytest.mark.unit]

_DUMMY_PATH = gate.DOCS_DIR / "dummy.md"

#: The three markers every declaration must carry, spelled out once so a test
#: that wants "declared" text does not have to hand-roll the sentence.
_DECLARATION = (
    "Examples use the `uv run` prefix. If you installed vaultspec-rag as a "
    "standalone tool, drop the prefix and call `vaultspec-rag` directly; see "
    "the [installation guide](installation.md) for lane selection.\n\n"
)


def test_lane_mixing_is_reported_by_name() -> None:
    """Two lanes in one page's examples must be named, not silently allowed."""
    text = (
        _DECLARATION
        + '```bash\nuv run vaultspec-rag search "x"\n```\n\n'
        + '```bash\nvaultspec-rag search "y"\n```\n'
    )
    problems = gate.check_lane_mixing(_DUMMY_PATH, text)
    assert problems, "a page mixing uv-run and bare lanes must be flagged"
    assert "mixes invocation lanes" in problems[0]
    assert "uv-run" in problems[0]
    assert "bare" in problems[0]


def test_single_lane_is_not_mixing() -> None:
    text = _DECLARATION + '```bash\nuv run vaultspec-rag search "x"\n```\n'
    assert gate.check_lane_mixing(_DUMMY_PATH, text) == []


def test_output_fence_is_excluded_from_lane_scan() -> None:
    """A captured status render is not an instruction, even if it names the CLI."""
    text = (
        _DECLARATION
        + "```bash\nuv run vaultspec-rag server status\n```\n\n"
        + '```text\nNext action:\n  vaultspec-rag search "<query>"\n```\n'
    )
    assert gate.check_lane_mixing(_DUMMY_PATH, text) == []


def test_lane_declaration_is_required_when_cli_is_invoked() -> None:
    text = '```bash\nvaultspec-rag search "x"\n```\n'
    problems = gate.check_lane_declaration(_DUMMY_PATH, text)
    assert problems, (
        "a page invoking the CLI without declaring its lane must be flagged"
    )
    assert "does not declare its invocation lane" in problems[0]


def test_lane_declaration_survives_a_hard_wrap() -> None:
    """A declaration split across wrapped lines must still satisfy the gate."""
    wrapped = (
        "Examples use the `uv run`\nprefix. If you installed vaultspec-rag as a\n"
        "standalone tool, drop the prefix and call `vaultspec-rag` directly; see\n"
        "the [installation guide](installation.md)\nfor lane selection.\n\n"
    )
    text = wrapped + '```bash\nuv run vaultspec-rag search "x"\n```\n'
    assert gate.check_lane_declaration(_DUMMY_PATH, text) == []


def test_no_cli_invocation_needs_no_declaration() -> None:
    text = "Just prose about vaultspec-rag with no fenced examples at all.\n"
    assert gate.check_lane_declaration(_DUMMY_PATH, text) == []


def test_env_only_example_without_explanation_is_flagged() -> None:
    text = (
        "Set the profile before starting the service.\n\n"
        "```bash\nVAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local\n```\n"
    )
    problems = gate.check_env_only_examples(_DUMMY_PATH, text)
    assert problems, "an unexplained env-var-only block must be flagged"
    assert "is not called out as an environment variable" in problems[0]


def test_env_only_example_with_explanation_passes() -> None:
    text = (
        "Set this environment variable before starting the service.\n\n"
        "```bash\nVAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local\n```\n"
    )
    assert gate.check_env_only_examples(_DUMMY_PATH, text) == []


def test_version_mismatch_ordering_requires_a_newer_client() -> None:
    text = "This vaultspec-rag client is 0.4.21 but the running service is 0.4.22.\n"
    problems = gate.check_version_mismatch_example(_DUMMY_PATH, text)
    assert problems, "client <= service must be rejected"
    assert "client 0.4.21 <= service 0.4.22" in problems[0]


def test_version_mismatch_ordering_accepts_a_newer_client() -> None:
    text = "This vaultspec-rag client is 0.4.22 but the running service is 0.4.21.\n"
    assert gate.check_version_mismatch_example(_DUMMY_PATH, text) == []


def test_version_mismatch_flags_page_wide_inconsistency() -> None:
    text = (
        "release: 0.4.19 (matches this client)\n\n"
        "This vaultspec-rag client is 0.4.22 but the running service is 0.4.21.\n"
    )
    problems = gate.check_version_mismatch_example(_DUMMY_PATH, text)
    assert problems, (
        "a healthy release that disagrees with the mismatch example must be flagged"
    )
    assert "not internally consistent" in problems[0]


def test_mcp_path_checks_require_all_three_platforms() -> None:
    text = "```bash\nwhich vaultspec-search-mcp\n```\n"
    problems = gate.check_mcp_path_and_version_scope(_DUMMY_PATH, text)
    messages = "\n".join(problems)
    assert "missing the PowerShell PATH check" in messages
    assert "missing the Command Prompt PATH check" in messages
    assert "missing a POSIX PATH check" not in messages


def test_mcp_version_scope_caveat_must_state_its_own_expiry() -> None:
    text = (
        "```bash\nwhich vaultspec-search-mcp\n```\n"
        "```powershell\nGet-Command vaultspec-search-mcp\n```\n"
        "```\nwhere.exe vaultspec-search-mcp\n```\n"
        "This is vaultspec-core#404, fixed by vaultspec-core#428.\n"
    )
    problems = gate.check_mcp_path_and_version_scope(_DUMMY_PATH, text)
    assert any("state the condition" in problem for problem in problems)


def test_mcp_platform_and_version_scope_all_present_passes() -> None:
    text = (
        "```bash\ncommand -v vaultspec-search-mcp\n```\n"
        "```powershell\nGet-Command vaultspec-search-mcp\n```\n"
        "```\nwhere.exe vaultspec-search-mcp\n```\n"
        "This is vaultspec-core#404, fixed by vaultspec-core#428, and no "
        "longer applies on 0.2.0.\n"
    )
    assert gate.check_mcp_path_and_version_scope(_DUMMY_PATH, text) == []
