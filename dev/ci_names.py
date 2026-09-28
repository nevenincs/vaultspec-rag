"""Every name the CI plane is addressed by, defined once.

Branch protection matches a required check by its STRING: rename the gate job
and the check it requires is never reported, which GitHub renders as
"expected" rather than failed. So the names live here, guards read them by
import, and the guards beside this module assert the workflows spell the same
literals.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "FLEET_OWNED",
    "FULL_RUN_LABEL",
    "GATE_CHECK",
    "GATE_JOB",
    "LABEL_ENV",
    "MEASURING_GROUPS",
    "MERGE_BOX",
    "PRODUCT",
    "SAME_REPO_CLAUSE",
    "Workflow",
]


class Workflow(StrEnum):
    """The workflow files, by the name the Actions API addresses them by.

    The API accepts the file name in place of the numeric id, so this is the
    same string a ``gh api actions/workflows/<name>/runs`` call uses.
    """

    CHEAP_LANE = "ci.yml"
    MERGE_GATE = "merge-gate.yml"
    HARDWARE = "hardware.yml"
    RELEASE_PLEASE = "release-please.yml"
    BINARIES = "binaries.yml"
    ACQUISITION = "acquisition.yml"
    PUBLISH = "publish.yml"
    CODE_HEALTH = "code-health.yml"
    RUNNER_POLICY = "runner-policy.yml"


#: The product every workflow name starts with, so this repository's runs
#: group together beside its siblings' in a fleet-wide view.
PRODUCT = "RAG"

#: The workflow that measures pull requests and reports merge readiness.
#: Release and scheduled hardware workflows answer different questions.
MERGE_BOX = (Workflow.MERGE_GATE,)

#: The justfile consequence groups whose recipes measure the tree, as opposed
#: to provisioning it. ``init`` running in every job is not a repeat; two jobs
#: running the same gate is.
MEASURING_GROUPS = frozenset({"check", "audit", "test"})

#: The gate job's key under ``jobs:`` in :attr:`Workflow.MERGE_GATE`. The runner
#: admission policy recognises the job by this id and grants it the no-slot
#: class, so a rename also makes the gate queue behind the jobs it judges.
GATE_JOB = "gate"

#: The label that starts a full run. A momentary pushbutton, not a toggle:
#: adding a label that is already present fires no ``labeled`` event, so the
#: gate releases it again and pressing it twice means adding it twice.
FULL_RUN_LABEL = "ci:full"

#: Workflows the fleet generates and deploys into this repository. They are
#: kept byte-for-byte as rendered, so this repository's own naming rules do
#: not apply to them; the fleet's drift check does.
FLEET_OWNED = frozenset({Workflow.RUNNER_POLICY})

#: The clause that excludes a fork's pull request. Present so that a job in
#: THIS repository's copy of a workflow cannot quietly lose it; it is not what
#: contains a fork, because a fork's pull request runs the fork's own copy of
#: the file. See the merge gate's header on what actually holds that line.
SAME_REPO_CLAUSE = "github.event.pull_request.head.repo.full_name == github.repository"

#: The one check ``protect-main`` requires on a pull request's head commit.
#: The ruleset's context is a repository setting outside the tree, so a change
#: here is a settings change too.
GATE_CHECK = "Check: Merge gate (Linux)"

#: The workflow-level ``env`` key that carries :data:`FULL_RUN_LABEL` into the
#: steps that read it, so a step never retypes the label.
LABEL_ENV = "FULL_RUN_LABEL"
