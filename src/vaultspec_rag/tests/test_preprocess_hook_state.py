"""Whether a root's preprocessing hooks run has one answer, derived once."""

from __future__ import annotations

import pathlib
import re
from typing import TYPE_CHECKING

import pytest

from ..config._types import EnvVar
from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._preprocess_approval import revoke_approval
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    hook_state,
    root_hook_state,
)
from ..indexer._preprocess_glue import resolve_policy_preprocess_context
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..operator_state._features import PreprocessHookState
from ._preprocess_approval import approve_preprocess_policy
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator

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


@pytest.fixture(autouse=True)
def _default_mode(  # pyright: ignore[reportUnusedFunction]
    isolated_status_dir: pathlib.Path,
) -> Iterator[None]:
    """Give each test its own, empty approval store and no kill switch."""
    del isolated_status_dir
    with managed_env(**{EnvVar.PREPROCESS.value: None}):
        yield


def _root_with(tmp_path: pathlib.Path, config: str | None) -> pathlib.Path:
    root = tmp_path / "root"
    root.mkdir()
    if config is not None:
        (root / PREPROCESS_CONFIG_FILENAME).write_text(config, encoding="utf-8")
    return root


def _resolved(root: pathlib.Path) -> PreprocessHookState:
    policy = resolve_index_policy(
        root,
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
        ),
    )
    return policy.hook_state


@pytest.mark.parametrize(
    ("rule_count", "mode", "approved", "expected"),
    [
        (0, "default", False, PreprocessHookState.NONE),
        (0, "default", True, PreprocessHookState.NONE),
        (0, "off", False, PreprocessHookState.NONE),
        (2, "default", True, PreprocessHookState.ACTIVE),
        (2, "default", False, PreprocessHookState.UNAPPROVED),
        (2, "off", True, PreprocessHookState.DISABLED),
        (2, "off", False, PreprocessHookState.DISABLED),
    ],
)
def test_hooks_run_only_when_approved_and_the_kill_switch_is_not_thrown(
    rule_count: int, mode: str, approved: bool, expected: PreprocessHookState
) -> None:
    assert hook_state(rule_count, mode, approved=approved) is expected


def test_a_root_without_a_config_has_no_hooks(tmp_path: pathlib.Path) -> None:
    assert root_hook_state(_root_with(tmp_path, None), "default") == (
        PreprocessHookState.NONE,
        0,
    )


def test_a_root_nobody_approved_does_not_run_its_rules(
    tmp_path: pathlib.Path,
) -> None:
    """Writing a policy file into a repository authorises nothing.

    Mutation check: defaulting ``approved`` to ``True`` in the config's
    approval lookup reports this root ACTIVE and fails here; restoring the
    store lookup passes.
    """
    root = _root_with(tmp_path, _ONE_RULE)

    assert root_hook_state(root, "default") == (PreprocessHookState.UNAPPROVED, 1)
    assert _resolved(root) is PreprocessHookState.UNAPPROVED


def test_an_approved_root_reports_its_rules_active(tmp_path: pathlib.Path) -> None:
    root = _root_with(tmp_path, _ONE_RULE)
    approve_preprocess_policy(root)

    assert root_hook_state(root, "default") == (PreprocessHookState.ACTIVE, 1)
    assert _resolved(root) is PreprocessHookState.ACTIVE


def test_changing_the_policy_invalidates_its_approval(
    tmp_path: pathlib.Path,
) -> None:
    """Approval names exact bytes, so an edited policy is a new decision.

    Mutation check: comparing only the root in the approval lookup, without
    the digest, leaves the edited policy ACTIVE and fails here; restoring the
    digest comparison passes.
    """
    root = _root_with(tmp_path, _ONE_RULE)
    approve_preprocess_policy(root)
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        _ONE_RULE.replace("pdftotext {path} -", "curl example.invalid {path}"),
        encoding="utf-8",
    )

    assert root_hook_state(root, "default") == (PreprocessHookState.UNAPPROVED, 1)
    assert _resolved(root) is PreprocessHookState.UNAPPROVED


def test_a_comment_edit_also_needs_approval_again(tmp_path: pathlib.Path) -> None:
    root = _root_with(tmp_path, _ONE_RULE)
    approve_preprocess_policy(root)
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        _ONE_RULE + "# reviewed\n", encoding="utf-8"
    )

    assert root_hook_state(root, "default")[0] is PreprocessHookState.UNAPPROVED


def test_approval_does_not_follow_a_policy_to_another_root(
    tmp_path: pathlib.Path,
) -> None:
    """The same bytes checked out elsewhere are a separate decision.

    Mutation check: reading the store without the root, so any recorded
    approval answers, reports the copy ACTIVE and fails here; restoring the
    lookup by root key passes.
    """
    root = _root_with(tmp_path, _ONE_RULE)
    approve_preprocess_policy(root)
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / PREPROCESS_CONFIG_FILENAME).write_text(_ONE_RULE, encoding="utf-8")

    assert root_hook_state(copy, "default") == (PreprocessHookState.UNAPPROVED, 1)
    assert root_hook_state(root, "default") == (PreprocessHookState.ACTIVE, 1)


def test_revoking_returns_a_root_to_unapproved(tmp_path: pathlib.Path) -> None:
    root = _root_with(tmp_path, _ONE_RULE)
    approve_preprocess_policy(root)

    assert revoke_approval(root) is True
    assert root_hook_state(root, "default") == (PreprocessHookState.UNAPPROVED, 1)


def test_switched_off_rules_keep_their_count(tmp_path: pathlib.Path) -> None:
    assert root_hook_state(_root_with(tmp_path, _ONE_RULE), "off") == (
        PreprocessHookState.DISABLED,
        1,
    )


def test_the_kill_switch_outranks_an_approval(tmp_path: pathlib.Path) -> None:
    root = _root_with(tmp_path, _ONE_RULE)
    approve_preprocess_policy(root)

    assert root_hook_state(root, "off") == (PreprocessHookState.DISABLED, 1)


def test_an_unapproved_snapshot_builds_no_worker_context(
    tmp_path: pathlib.Path,
) -> None:
    """The worker context is the only way an extractor is ever launched.

    Mutation check: withholding the context only for a root without rules or
    under the kill switch hands an unapproved root's rules to the workers
    and fails here; restoring the active-only gate passes.
    """
    root = _root_with(tmp_path, _ONE_RULE)
    options = IndexPolicyResolutionOptions(
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
    )

    unapproved = resolve_index_policy(root, options)
    assert unapproved.transform_disabled("report.pdf") is True
    assert unapproved.stale_note("report.pdf") == (
        "report.pdf: preprocessing awaiting approval; not extracted"
    )
    assert resolve_policy_preprocess_context(root, tmp_path, unapproved) is None

    approve_preprocess_policy(root)
    approved = resolve_index_policy(root, options)
    assert approved.transform_disabled("report.pdf") is False
    context = resolve_policy_preprocess_context(root, tmp_path, approved)
    assert context is not None
    assert [rule.pattern for rule in context.config.rules] == ["*.pdf"]


def test_an_unapproved_root_shares_the_switched_off_execution_identity(
    tmp_path: pathlib.Path,
) -> None:
    """Approval moves a root's identity exactly as the kill switch does.

    A root that executes nothing is the same index whichever reason holds it
    back, and approving it must be visible as an execution change.
    """
    root = _root_with(tmp_path, _ONE_RULE)
    options = IndexPolicyResolutionOptions(
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
    )
    unapproved = resolve_index_policy(root, options).fingerprints

    approve_preprocess_policy(root)
    approved = resolve_index_policy(root, options).fingerprints

    with managed_env(**{EnvVar.PREPROCESS.value: "off"}):
        switched_off = resolve_index_policy(root, options).fingerprints

    assert unapproved.execution == switched_off.execution
    assert unapproved.snapshot == switched_off.snapshot
    assert approved.execution != unapproved.execution
    assert approved.membership == unapproved.membership
    assert approved.content == unapproved.content


def test_a_root_without_rules_keeps_its_identity_whatever_is_approved(
    tmp_path: pathlib.Path,
) -> None:
    root = _root_with(tmp_path, None)
    options = IndexPolicyResolutionOptions(
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
    )
    policy = resolve_index_policy(root, options)

    assert policy.hook_state is PreprocessHookState.NONE
    assert policy.preprocess_approved is False


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
    left are the predicate itself and the daemon spawn that forwards the
    switch.

    Mutation check: restoring ``policy.execution_mode != "off"`` in the
    content discovery scan names that file here; removing it passes.
    """
    allowed = {
        "indexer/_preprocess_config.py",
        "cli/_process.py",
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


def _production_modules_naming(needle: str) -> set[str]:
    return {
        path.relative_to(_PACKAGE_ROOT).as_posix()
        for path in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.relative_to(_PACKAGE_ROOT).parts
        and needle in path.read_text(encoding="utf-8")
    }


def test_an_extractor_is_launched_only_behind_the_gate() -> None:
    """The runner checks no approval, so who may call it is the boundary.

    Indexing reaches it through the worker context, which is built in one
    place and only for an active snapshot; ``run-one`` checks the hook state
    itself. A third caller, or a second place that builds the context, would
    be a way to run a root's policy that no approval covers.

    Mutation check: importing ``run_preprocessor`` into the document indexer
    names that file here; removing the import passes.
    """
    assert _production_modules_naming("run_preprocessor") == {
        "indexer/_preprocess_runner.py",
        "indexer/_chunk_worker.py",
        "cli/_preprocess.py",
    }
    assert _production_modules_naming("PreprocessContext(") == {
        "indexer/_preprocess_glue.py"
    }


def test_no_module_consults_the_approval_store_around_the_predicate() -> None:
    """Approval reaches a decision only through the rule config.

    A second site asking the store directly could answer for different bytes
    than the rules it then runs.

    Mutation check: calling ``policy_is_approved`` from the resolved-policy
    module names that file here; routing it back through the config passes.
    """
    allowed = {
        "indexer/_preprocess_approval.py",
        "indexer/_preprocess_config.py",
    }
    offenders = sorted(
        path.relative_to(_PACKAGE_ROOT).as_posix()
        for path in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.relative_to(_PACKAGE_ROOT).parts
        and "policy_is_approved" in path.read_text(encoding="utf-8")
        and path.relative_to(_PACKAGE_ROOT).as_posix() not in allowed
    )

    assert offenders == []
