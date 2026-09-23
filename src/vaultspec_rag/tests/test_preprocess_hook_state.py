"""Whether a root's preprocessing hooks run has one answer, derived once."""

from __future__ import annotations

import pathlib
import re

import pytest

from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    hook_state,
    root_hook_state,
)
from ..operator_state._features import PreprocessHookState

pytestmark = [pytest.mark.unit]

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]

_ONE_RULE = """version = 2

[[rule]]
pattern = "*.pdf"
target = "document"
extractor_version = "1.0.0"
command = 'pdftotext {path} -'
on_error = "skip"
"""


def _root_with(tmp_path: pathlib.Path, config: str | None) -> pathlib.Path:
    root = tmp_path / "root"
    root.mkdir()
    if config is not None:
        (root / PREPROCESS_CONFIG_FILENAME).write_text(config, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("rule_count", "mode", "expected"),
    [
        (0, "default", PreprocessHookState.NONE),
        (0, "off", PreprocessHookState.NONE),
        (2, "default", PreprocessHookState.ACTIVE),
        (2, "off", PreprocessHookState.DISABLED),
    ],
)
def test_hooks_run_only_when_rules_exist_and_the_kill_switch_is_not_thrown(
    rule_count: int, mode: str, expected: PreprocessHookState
) -> None:
    assert hook_state(rule_count, mode) is expected


def test_a_root_without_a_config_has_no_hooks(tmp_path: pathlib.Path) -> None:
    assert root_hook_state(_root_with(tmp_path, None), "default") == (
        PreprocessHookState.NONE,
        0,
    )


def test_a_root_with_rules_reports_them_active(tmp_path: pathlib.Path) -> None:
    assert root_hook_state(_root_with(tmp_path, _ONE_RULE), "default") == (
        PreprocessHookState.ACTIVE,
        1,
    )


def test_switched_off_rules_keep_their_count(tmp_path: pathlib.Path) -> None:
    assert root_hook_state(_root_with(tmp_path, _ONE_RULE), "off") == (
        PreprocessHookState.DISABLED,
        1,
    )


def test_a_malformed_config_degrades_instead_of_raising(
    tmp_path: pathlib.Path,
) -> None:
    """A status read must answer for a broken config, as indexing does.

    Mutation check: letting the config error propagate out of the resolver
    fails this test with the parse error instead of the invalid state;
    restoring the degrade passes.
    """
    root = _root_with(tmp_path, "version = [not toml")

    assert root_hook_state(root, "default") == (
        PreprocessHookState.INVALID_CONFIG,
        0,
    )


def test_no_module_rederives_whether_hooks_run() -> None:
    """Every "will hooks run" answer comes from the one predicate.

    Seven sites once answered it, and they disagreed about whether a missing
    file mattered. The only comparisons of a preprocess mode against ``off``
    left are the predicate itself, the daemon spawn that forwards the switch,
    and the per-path routing check that is a different question.

    Mutation check: restoring ``policy.execution_mode != "off"`` in the
    content discovery scan names that file here; removing it passes.
    """
    allowed = {
        "indexer/_preprocess_config.py",
        "cli/_process.py",
        "indexer/_resolved_policy.py",
    }
    pattern = re.compile(
        r"(preprocess_mode|execution_mode|effective_mode|\bmode)\s*(!=|==)\s*\"off\""
    )
    offenders = sorted(
        path.relative_to(_PACKAGE_ROOT).as_posix()
        for path in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.relative_to(_PACKAGE_ROOT).parts
        and pattern.search(path.read_text(encoding="utf-8"))
        and path.relative_to(_PACKAGE_ROOT).as_posix() not in allowed
    )

    assert offenders == []
