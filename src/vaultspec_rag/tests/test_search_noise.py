"""Unit tests for the code-search noise policy."""

from __future__ import annotations

from typing import ClassVar

import pytest

from ..config import get_config, reset_config
from ..search._models import SearchResult
from ..search._noise import (
    NoisePolicy,
    apply_domain_demotion,
    partition_hard_domains,
    resolve_noise_policy,
)


def _mk(path: str, score: float) -> SearchResult:
    return SearchResult(
        id=path, path=path, title=path, score=score, snippet="x", source="codebase"
    )


class TestResolveNoisePolicy:
    pytestmark: ClassVar = [pytest.mark.unit]

    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_defaults(self) -> None:
        policy = resolve_noise_policy(get_config())
        assert policy.hide == frozenset({"worktree", "generated"})
        assert policy.demote == frozenset({"tests", "docs", "locale", "vendored"})
        assert policy.only == frozenset()
        assert policy.penalty == pytest.approx(0.3)
        assert policy.has_hard_filter is True

    def test_include_readmits_a_demoted_domain(self) -> None:
        policy = resolve_noise_policy(get_config(), include_domains=["tests"])
        assert "tests" not in policy.demote
        assert "tests" not in policy.hide

    def test_exclude_adds_to_hide(self) -> None:
        policy = resolve_noise_policy(get_config(), exclude_domains=["tests"])
        assert "tests" in policy.hide
        # Once hidden it is no longer merely demoted.
        assert "tests" not in policy.demote

    def test_only_restricts(self) -> None:
        policy = resolve_noise_policy(get_config(), only_domains=["tests"])
        assert policy.only == frozenset({"tests"})

    def test_unknown_domain_tokens_dropped(self) -> None:
        policy = resolve_noise_policy(
            get_config(), exclude_domains=["bogus", "prod", "tests"]
        )
        # ``bogus`` is not a domain and ``prod`` is never noise.
        assert "bogus" not in policy.hide
        assert "prod" not in policy.hide
        assert "tests" in policy.hide


class TestPartitionHardDomains:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_hide_drops_and_counts(self) -> None:
        policy = NoisePolicy(
            hide=frozenset({"worktree"}),
            only=frozenset(),
            demote=frozenset(),
            penalty=0,
        )
        raw: list[dict[str, object]] = [
            {"path": "src/a.py", "domain": "prod"},
            {"path": ".claude/worktrees/x/src/a.py", "domain": "worktree"},
            {"path": ".claude/worktrees/y/src/b.py", "domain": "worktree"},
        ]
        kept, dropped = partition_hard_domains(raw, policy)
        assert [r["path"] for r in kept] == ["src/a.py"]
        assert dropped == {"worktree": 2}

    def test_payload_absent_falls_back_to_path_classification(self) -> None:
        policy = NoisePolicy(
            hide=frozenset({"tests"}), only=frozenset(), demote=frozenset(), penalty=0
        )
        # No stored ``domain`` -> classify the path.
        raw: list[dict[str, object]] = [
            {"path": "tests/test_x.py"},
            {"path": "src/x.py"},
        ]
        kept, dropped = partition_hard_domains(raw, policy)
        assert [r["path"] for r in kept] == ["src/x.py"]
        assert dropped == {"tests": 1}

    def test_only_keeps_just_the_named_domains(self) -> None:
        policy = NoisePolicy(
            hide=frozenset(),
            only=frozenset({"tests"}),
            demote=frozenset(),
            penalty=0,
        )
        raw: list[dict[str, object]] = [
            {"path": "tests/test_x.py", "domain": "tests"},
            {"path": "src/x.py", "domain": "prod"},
        ]
        kept, _ = partition_hard_domains(raw, policy)
        assert [r["path"] for r in kept] == ["tests/test_x.py"]

    def test_no_hard_filter_is_passthrough(self) -> None:
        policy = NoisePolicy(
            hide=frozenset(), only=frozenset(), demote=frozenset({"tests"}), penalty=0.3
        )
        raw: list[dict[str, object]] = [{"path": "tests/test_x.py", "domain": "tests"}]
        kept, dropped = partition_hard_domains(raw, policy)
        assert kept == raw
        assert dropped == {}


class TestDomainQueryTokens:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_exclude_token_parsed_and_stripped(self) -> None:
        from ..search import parse_query

        parsed = parse_query("gpu lock exclude:tests")
        assert parsed.text == "gpu lock"
        assert parsed.filters["exclude_domain"] == "tests"

    def test_only_and_include_tokens(self) -> None:
        from ..search import parse_query

        parsed = parse_query("encode only:prod include:docs")
        assert parsed.filters["only_domain"] == "prod"
        assert parsed.filters["include_domain"] == "docs"
        assert parsed.text == "encode"

    def test_comma_and_repeat_accumulate(self) -> None:
        from ..search import parse_query

        parsed = parse_query("q exclude:tests,docs exclude:locale")
        assert parsed.filters["exclude_domain"] == "tests,docs,locale"


class TestDomainValidation:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_unknown_domain_rejected(self) -> None:
        from ..search import InvalidFilterForSearchTypeError, validate_search_filters

        with pytest.raises(InvalidFilterForSearchTypeError):
            validate_search_filters("code", exclude_domains=["bogus"])

    def test_known_domains_accepted(self) -> None:
        from ..search import validate_search_filters

        # Does not raise.
        validate_search_filters(
            "code", exclude_domains=["tests"], only_domains=["prod"]
        )

    def test_domain_filters_require_code_type(self) -> None:
        from ..search import InvalidFilterForSearchTypeError, validate_search_filters

        with pytest.raises(InvalidFilterForSearchTypeError):
            validate_search_filters("vault", exclude_domains=["tests"])


class TestApplyDomainDemotion:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_demoted_result_sinks_below_production(self) -> None:
        policy = NoisePolicy(
            hide=frozenset(),
            only=frozenset(),
            demote=frozenset({"tests"}),
            penalty=0.3,
        )
        # A test result initially out-scores production by 0.1.
        results = [_mk("tests/test_x.py", 0.80), _mk("src/x.py", 0.70)]
        apply_domain_demotion(results, policy)
        assert results[0].path == "src/x.py"
        assert results[1].path == "tests/test_x.py"
        assert results[1].score == pytest.approx(0.50)

    def test_zero_penalty_is_noop(self) -> None:
        policy = NoisePolicy(
            hide=frozenset(), only=frozenset(), demote=frozenset({"tests"}), penalty=0.0
        )
        results = [_mk("tests/test_x.py", 0.80), _mk("src/x.py", 0.70)]
        apply_domain_demotion(results, policy)
        assert results[0].path == "tests/test_x.py"
