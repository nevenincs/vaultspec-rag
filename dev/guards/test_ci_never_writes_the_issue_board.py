"""No workflow files an advisory on the issue board.

A scheduled job that opens an issue whenever it dislikes what it sees turns
the board into a log. Nineteen issues reporting the same stalled queue buried
the handful a person actually wrote, and every one of them had to be closed by
hand. The board is for work someone intends to do; CI reports through its own
run status, which is already the durable record of what passed.

So no workflow may open an issue, and none may comment on one. Two routes
reach the board and both are closed here: the token permission that would
allow it, and the call that would do it.

LABELS ARE NOT THE BOARD. The merge gate deletes a label a maintainer applied,
and release-please opens the release pull request that IS the release
mechanism. Neither files an advisory, so `pull-requests: write` stays legal
and `issues: write` does not.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The permission that lets a token open or comment on an issue. `read` is
#: fine - the assistant workflow reads issues it is asked about.
ISSUE_WRITE = "write"

#: Calls that file something on the board. `gh issue comment` and the REST
#: route underneath it are both spelled out, because a workflow reaching for
#: one when the other is blocked is the same defect wearing a different hat.
_BOARD_WRITES = re.compile(
    r"""(
        gh\s+issue\s+(create|comment|reopen)
      | issues\.(create|createComment|update)\b
      | /issues(/\d+/comments)?['"]?\s*$
      | --method\s+POST\s+[^\n]*?/issues\b
      | peter-evans/create-issue
    )""",
    re.VERBOSE | re.MULTILINE,
)


def _documents() -> list[tuple[str, dict[str, Any]]]:
    """Return every workflow as ``(filename, parsed document)``."""
    root = workflows.repository_root() / ".github" / "workflows"
    return [
        (path.name, cast("dict[str, Any]", yaml.safe_load(path.read_text("utf-8"))))
        for path in sorted([*root.glob("*.yml"), *root.glob("*.yaml")])
    ]


def _permission_blocks(node: Any) -> list[dict[str, Any]]:
    """Return every ``permissions:`` mapping anywhere in *node*."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        block = node.get("permissions")
        if isinstance(block, dict):
            found.append(block)
        for value in node.values():
            found.extend(_permission_blocks(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_permission_blocks(value))
    return found


def test_no_workflow_takes_issue_write() -> None:
    """A token that cannot write the board cannot pollute it."""
    offenders = [
        f"{name}: issues: {block['issues']}"
        for name, document in _documents()
        for block in _permission_blocks(document)
        if str(block.get("issues", "")).strip() == ISSUE_WRITE
    ]
    assert not offenders, (
        "a workflow grants itself `issues: write`, which is what lets CI file "
        f"advisories on the board: {offenders}"
    )


def test_no_workflow_step_files_an_issue() -> None:
    """Belt to the permission's braces: no step calls the board either."""
    root = workflows.repository_root() / ".github"
    offenders = [
        f"{path.relative_to(root)}: {match.group(0).strip()}"
        for path in sorted(root.rglob("*.yml"))
        for match in _BOARD_WRITES.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "a workflow step opens or comments on an issue; CI reports through its "
        f"run status, not the board: {offenders}"
    )
