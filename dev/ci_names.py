"""Every name the CI plane is addressed by, defined once.

A name that appears in two places is a name that can disagree with itself, and
the merge box is where disagreement is silent. Branch protection matches a
required check by its STRING. Rename the job and the check it requires is
never reported, which GitHub renders as "expected" - not failed - so every
pull request becomes unmergeable with nothing red to explain it. A label typed
one way in a trigger condition and another in the step that releases it leaves
a button that fires once and never clears.

So the names live here, and nothing else defines one:

- **Python reads them by import.** A guard that needs the gate's job id, the
  label that starts a full run, or the workflow a lane belongs to takes it
  from this module. No guard writes a name of its own.
- **YAML cannot import**, so the guard beside this module asserts the literals
  in the workflows equal what is defined here. That assertion IS the
  derivation: the workflow is checked against the canon on every run of the
  suite, and a rename that touches one and not the other fails before it can
  reach the merge box.
- **The remote ruleset cannot be read offline.** :data:`GATE_CHECK` is the
  context ``protect-main`` requires; changing it is a repository settings
  change as well as a code change, and :func:`job_name` composing it from the
  grammar is what keeps that a deliberate edit rather than a typo.

Names are COMPOSED, not typed. ``Check: Merge gate (Linux)`` is
:class:`Kind`, a subject, and :class:`Platform` put together by
:func:`job_name`, so the grammar the fleet reads is the grammar this module
can produce, and a job name that does not fit the grammar cannot be spelled
here at all.
"""

from __future__ import annotations

import re
from enum import StrEnum

__all__ = [
    "FULL_RUN_CONDITION",
    "FULL_RUN_LABEL",
    "FULL_RUN_PRESSED",
    "GATE_CHECK",
    "GATE_JOB",
    "JOB_NAME",
    "LABEL_ENV",
    "LEG",
    "LINT_RUN_CONDITION",
    "MEASURING_GROUPS",
    "MERGE_BOX",
    "PRODUCT",
    "SAME_REPO_CLAUSE",
    "WORKFLOW_NAME",
    "Kind",
    "Platform",
    "Workflow",
    "collapse",
    "job_name",
    "listed",
    "normalise",
    "workflow_name",
]


class Kind(StrEnum):
    """What a job's result means, and the first word of its name.

    Three consequences, matching the justfile's consequence groups: a
    ``check`` or ``audit`` recipe reports under :attr:`CHECK`, a ``test``
    recipe under :attr:`TEST`, and a ``build`` recipe under :attr:`BUILD`.
    Reading the Kind tells a reviewer what kind of failure they are looking
    at before they open anything.
    """

    CHECK = "Check"
    TEST = "Test"
    BUILD = "Build"


class Platform(StrEnum):
    """The operating system a job lands on.

    The only parenthesis a job name may carry, because the platform is the
    one thing about a red row a reviewer needs before opening it: a failure
    on one operating system and a failure on all three are different defects.
    """

    LINUX = "Linux"
    WINDOWS = "Windows"
    MACOS = "macOS"


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

#: The gate job's key under ``jobs:`` in :attr:`Workflow.MERGE_GATE`.
GATE_JOB = "gate"

#: The label that starts a full run. A momentary pushbutton, not a toggle:
#: adding a label that is already present fires no ``labeled`` event, so the
#: gate releases it again and pressing it twice means adding it twice.
FULL_RUN_LABEL = "ci:full"

#: The clause that excludes a fork's pull request. Present so that a job in
#: THIS repository's copy of a workflow cannot quietly lose it; it is not what
#: contains a fork, because a fork's pull request runs the fork's own copy of
#: the file. See the merge gate's header on what actually holds that line.
SAME_REPO_CLAUSE = "github.event.pull_request.head.repo.full_name == github.repository"


#: The stand-in a matrix interpolation collapses to before a name is matched,
#: so a leg's name is checked for SHAPE rather than for its resolved value.
LEG = "Xx"

#: An expression inside a job name, replaced by :data:`LEG` before matching.
_INTERPOLATION = re.compile(r"\$\{\{[^}]*\}\}")

#: An all-capitals acronym: the one capitalised word allowed mid-subject.
_ACRONYM = r"[A-Z0-9]{2,}"

#: A Subject: a capitalised first word, then lower-case words or acronyms.
_SUBJECT = rf"(?:[A-Z][a-z]*|{_ACRONYM})(?: (?:[a-z0-9][a-z0-9-]*|{_ACRONYM}))*"

#: The optional trailing parenthesis: a platform then legs, or legs alone.
_PLACE = (
    rf"(?:(?:{'|'.join(platform.value for platform in Platform)})"
    rf"(?:, {LEG})*|{LEG}(?:, {LEG})*)"
)

#: What a job name must look like once its interpolations are collapsed. The
#: same grammar :func:`job_name` composes to, read from the other end: a name
#: this rejects is a name that module cannot produce.
JOB_NAME = re.compile(
    rf"^(?:{'|'.join(kind.value for kind in Kind)}): {_SUBJECT}(?: \({_PLACE}\))?$"
)

#: What a workflow name must look like: ``<Product> <Purpose>`` in title case.
WORKFLOW_NAME = re.compile(rf"^{PRODUCT}(?: [A-Z][A-Za-z]*)+$")


def listed(vocabulary: type[Kind] | type[Platform]) -> str:
    """Return *vocabulary*'s members as prose, for a finding a human reads.

    Args:
        vocabulary: The enum whose members to list.

    Returns:
        The member values, comma-separated.
    """
    return ", ".join(member.value for member in vocabulary)


def collapse(name: str) -> str:
    """Return *name* with every expression replaced by :data:`LEG`.

    Args:
        name: A job name as the workflow spells it, interpolations and all.

    Returns:
        The same name with each ``${{ ... }}`` replaced by the stand-in.
    """
    return _INTERPOLATION.sub(LEG, name)


def normalise(expression: str) -> str:
    """Return *expression* with every run of whitespace collapsed to one space.

    A workflow ``if:`` is folded YAML, and folding is indentation-sensitive: a
    continuation line indented further than the block keeps its newline, one
    indented level with it does not. Comparing raw strings would therefore
    make a guard fail on a re-indent that changed no logic, and re-indenting
    to satisfy it would be editing the workflow to please the test.

    Args:
        expression: A workflow expression as YAML parsed it.

    Returns:
        The same expression with its whitespace normalised.
    """
    return " ".join(expression.split())


def job_name(kind: Kind, subject: str, place: Platform | str | None = None) -> str:
    """Compose a job name in the fleet's check-set grammar.

    The grammar is ``<Kind>: <Subject> [(<Platform>[, <leg>])]``. *subject* is
    sentence case and says WHAT IS COVERED, never which tool covers it: a tool
    name goes stale the day the tool changes, and the merge box then advertises
    a command nobody runs.

    Args:
        kind: What the job's result means.
        subject: What the job covers, in sentence case.
        place: The platform the job lands on, optionally with its matrix leg;
            ``None`` only for a job that calls a reusable workflow, whose
            called jobs carry their own.

    Returns:
        The composed job name.
    """
    body = f"{kind.value}: {subject}"
    if place is None:
        return body
    return f"{body} ({place.value if isinstance(place, Platform) else place})"


def workflow_name(purpose: str) -> str:
    """Compose a workflow name as ``<Product> <Purpose>`` in title case.

    Args:
        purpose: What the workflow is for, in title case.

    Returns:
        The composed workflow name.
    """
    return f"{PRODUCT} {purpose}"


#: The one check ``protect-main`` requires on a pull request's head commit.
#: Branch protection matches it by string, so this constant and the gate job's
#: ``name:`` and the ruleset's context are three copies of one fact - the
#: first two are tied together by the guard, and the third is the repository
#: setting that has to be changed alongside any edit here.
GATE_CHECK = job_name(Kind.CHECK, "Merge gate", Platform.LINUX)

#: The workflow-level ``env`` key that carries :data:`FULL_RUN_LABEL` into the
#: steps that read it, so a step never retypes the label.
LABEL_ENV = "FULL_RUN_LABEL"

#: The button being pressed on a pull request in this repository: the label
#: added, by someone who could add it here. Written once, and composed into
#: the two conditions below that need it.
FULL_RUN_PRESSED = normalise(
    "github.event_name == 'pull_request' && "
    "github.event.action == 'labeled' && "
    f"github.event.label.name == '{FULL_RUN_LABEL}' && {SAME_REPO_CLAUSE}"
)

#: The condition every measuring job in the merge gate carries. GitHub gives a
#: job-level ``if:`` no ``env`` context and honours no YAML anchor, so the four
#: jobs cannot share a token and each spells this out; the guard asserts they
#: spell the same thing, and that it is this.
FULL_RUN_CONDITION = normalise(
    "github.event_name != 'pull_request' || "
    f"({SAME_REPO_CLAUSE} && "
    "((github.event.action == 'labeled' && "
    f"github.event.label.name == '{FULL_RUN_LABEL}') || "
    "(github.event.action != 'labeled' && github.event.pull_request.draft == false)))"
)

#: Lint also measures drafts on lifecycle events, while an unrelated label
#: preserves the prior verdict without starting another self-hosted job.
LINT_RUN_CONDITION = normalise(
    "github.event_name != 'pull_request' || "
    f"({SAME_REPO_CLAUSE} && "
    "(github.event.action != 'labeled' || "
    f"github.event.label.name == '{FULL_RUN_LABEL}'))"
)
