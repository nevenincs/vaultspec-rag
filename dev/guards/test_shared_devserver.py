"""Keep the shared lifecycle script identical to the adopted source.

Verified mutation proof: appending one newline to dev/devserver.py failed the
digest assertion; restoring the file passed. A local fork cannot be synced safely.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from dev.ci_names import Workflow
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def test_shared_devserver_matches_adopted_source() -> None:
    script = Path(__file__).resolve().parents[1] / "devserver.py"
    source = script.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(source).hexdigest() == (
        "7f62533a10a3becd8016f37b02338fc87ed0c26158cbb0f3159aa12c42e9761b"
    ), "The lifecycle script differs from the adopted shared source."


def test_shared_workflow_matches_adopted_template() -> None:
    """Verified: renaming the workflow failed parity; restoring it passed."""
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "dev" / "devserver.py").read_text(encoding="utf-8"))
    template = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "WORKFLOW"
            for target in node.targets
        )
    )
    workflow = root / ".github" / "workflows" / "devserver.yml"
    assert workflow.read_text(encoding="utf-8") == template, (
        "The lifecycle workflow differs from the adopted shared template."
    )


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (("OWNER", False, "owner/repo", "opened", "", "User"), workflows.TRUE),
        (
            ("COLLABORATOR", False, "owner/repo", "synchronize", "", "User"),
            workflows.TRUE,
        ),
        (("OWNER", True, "owner/repo", "opened", "", "User"), workflows.FALSE),
        (("CONTRIBUTOR", False, "owner/repo", "opened", "", "User"), workflows.FALSE),
        (("NONE", False, "owner/repo", "opened", "", "Bot"), workflows.FALSE),
        (("OWNER", False, "outside/fork", "opened", "", "User"), workflows.FALSE),
        (("NONE", True, "owner/repo", "labeled", "ci:full", "User"), workflows.TRUE),
        (("NONE", False, "owner/repo", "labeled", "ci:full", "Bot"), workflows.FALSE),
        (
            ("NONE", False, "outside/fork", "labeled", "ci:full", "User"),
            workflows.FALSE,
        ),
        (
            ("NONE", False, "owner/repo", "labeled", "unrelated", "User"),
            workflows.FALSE,
        ),
    ],
)
def test_shared_workflow_admits_only_reviewed_pull_requests(
    case: tuple[str, bool, str, str, str, str],
    expected: workflows.Tri,
) -> None:
    """Verified: replacing author admission with true failed; restoration passed."""
    association, draft, head_repo, action, label, sender = case
    job = next(iter(workflows.load_jobs(Workflow.DEVSERVER)))
    bindings = {
        "github.repository": "owner/repo",
        "github.event.pull_request.head.repo.full_name": head_repo,
        "github.event.pull_request.author_association": association,
        "github.event.pull_request.draft": draft,
        "github.event.action": action,
        "github.event.label.name": label,
        "github.event.sender.type": sender,
    }
    assert workflows.evaluate(job.condition or "", "pull_request", bindings) == expected
