"""A release exists only once it is complete, and it is published last.

A published GitHub Release cannot be filled in afterwards, so this chain does
not publish one until every artifact it claims is attached and proven. The
release object is created unpublished; every lane attaches to that draft; one
step, at the end of the publication lane, takes it out of draft.

Three properties hold that order up, and each of them fails silently if it
drifts:

- **The draft needs its tag forced.** GitHub creates no git tag for a draft
  release, and every job in the lane checks out the tag for its source. Without
  ``force-tag-creation`` the release is created and nothing can build it.

- **The index is written before the flip and after the proof.** An upload to
  PyPI cannot be withdrawn; a draft can simply be left unpublished. So PyPI is
  dispatched by the gate that already found the draft complete, and the flip
  follows the upload - a release published first would advertise a version the
  index does not carry.

- **Nothing edits a release into shape.** Demote-and-promote existed because
  the release was published before its assets and had to be walked back. A
  draft cannot reach those states, and a dormant recovery path is
  indistinguishable from a working one until the day it is needed.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from dev.guards import _workflows as workflows
from dev.guards._ci_names import Workflow

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The one step that may name a release's prerelease flag, and the flag it
#: carries there. At the moment of publication the flag is a publication
#: choice; anywhere else it is a hold, and nothing promotes a release back.
PUBLICATION_FLAG = "--draft=false"

#: The package-index stage's job ids: the admission, the upload, then the
#: publication.
ADMISSION_JOB = "admit-package-index"
UPLOAD_JOB = "publish-pypi"
PUBLICATION_JOB = "publish-release"


def _source(workflow: str) -> str:
    """Return one workflow file's text."""
    path = workflows.repository_root() / ".github" / "workflows" / workflow
    return path.read_text(encoding="utf-8")


def _raw_jobs(workflow: str) -> dict[str, dict[str, Any]]:
    """Return one workflow's jobs mapping, unresolved."""
    jobs = workflows.document(workflow).get("jobs")
    assert isinstance(jobs, dict), f"{workflow} has no jobs"
    return cast("dict[str, dict[str, Any]]", jobs)


def _needed(workflow: str, job_id: str) -> set[str]:
    """Return every job *job_id* depends on, transitively."""
    jobs = _raw_jobs(workflow)
    found: set[str] = set()
    pending = [job_id]
    while pending:
        needs = jobs.get(pending.pop(), {}).get("needs")
        names = [needs] if isinstance(needs, str) else list(needs or [])
        for name in names:
            if str(name) not in found:
                found.add(str(name))
                pending.append(str(name))
    return found


def _steps(workflow: str, job_id: str) -> list[dict[str, Any]]:
    """Return one job's steps, in order."""
    steps = _raw_jobs(workflow).get(job_id, {}).get("steps")
    return [step for step in (steps or []) if isinstance(step, dict)]


def _index_of(workflow: str, job_id: str, needle: str) -> int:
    """Return the position of the only step of *job_id* whose script holds *needle*."""
    matches = [
        index
        for index, step in enumerate(_steps(workflow, job_id))
        if needle in str(step.get("run") or "")
    ]
    assert len(matches) == 1, (
        f"{workflow}:{job_id} has {len(matches)} steps running {needle!r}; "
        "exactly one is expected"
    )
    return matches[0]


def test_the_release_is_held_as_a_draft_until_the_lane_publishes_it() -> None:
    """release-please must create the release unpublished, and its tag anyway.

    A published release cannot be filled in afterwards, so the release object
    is created as a draft and published by the lane that has proved it.
    ``force-tag-creation`` is the other half: GitHub creates no git tag for a
    draft release, and every job in the lane checks out the tag for its source,
    so without it the build has no ref to build.

    Mutation proof: deleting ``"draft": true`` from the package made this fail
    on the draft assertion, and deleting ``"force-tag-creation": true`` made it
    fail on the tag assertion; restoring each made it pass.
    """
    path = workflows.repository_root() / "release-please-config.json"
    config = cast(
        "dict[str, dict[str, dict[str, object]]]",
        json.loads(path.read_text(encoding="utf-8")),
    )
    package = config["packages"]["."]
    assert package.get("draft") is True, (
        "release-please must create the release as a draft; a published "
        "release cannot receive the assets that justify it"
    )
    assert package.get("force-tag-creation") is True, (
        "a draft release creates no git tag, and the whole lane builds from "
        "the tag - release-please must force it into existence"
    )


def test_pypi_is_published_only_once_every_binary_is_proven() -> None:
    """The publication stage is dispatched from the gate that judged the draft.

    PyPI is the one irreversible act in the release: a version number is spent
    the moment it lands on the index, and no re-dispatch takes it back. So it
    is dispatched last, by the gate that has already found every declared
    target attached to the draft - not beside the build that produces them.

    Mutation proof: deleting ``if: ${{ success() }}`` from the handoff step
    made this fail on the condition assertion, and dispatching
    ``stage=release`` instead made it fail on the stage assertion; restoring
    each made it pass.
    """
    gate = _raw_jobs(Workflow.BINARIES).get("verify-release-assets")
    assert isinstance(gate, dict), f"{Workflow.BINARIES} has no release-proven gate"
    dispatching = [
        step
        for step in _steps(Workflow.BINARIES, "verify-release-assets")
        if "gh workflow run publish.yml" in str(step.get("run") or "")
    ]
    assert len(dispatching) == 1, (
        "exactly one step in the release-proven gate must dispatch the "
        f"publication; found {len(dispatching)}"
    )
    run = str(dispatching[0].get("run") or "")
    assert "stage=package-index" in run, (
        "the gate must dispatch the package-index stage; the release stage "
        "would rebuild and re-attach instead of publishing"
    )
    assert dispatching[0].get("if") == "${{ success() }}", (
        "the publication dispatch must be conditioned on the gate succeeding, "
        "or an incomplete release publishes to PyPI anyway"
    )


def test_the_release_is_published_last_and_only_once() -> None:
    """One step takes the release out of draft, after everything that fills it.

    The release is created unpublished and every lane attaches to that draft,
    so the flip to published is the statement that the release is complete. It
    belongs at the end of the publication lane - after the index upload, which
    is the other one-way act - and nowhere else. It holds no ``id-token``,
    because the two lanes it then dispatches carry credentials of their own.

    Mutation proof: adding ``id-token: write`` to ``publish-release`` made this
    fail on the permission assertion; pointing that job's ``needs`` at
    ``resolve-target`` instead of the upload job made it fail on the ordering
    assertion; a second ``--draft=false`` edit made it fail on the count
    assertion; moving the publication step below both dispatches made it fail
    naming the channel pointer; pointing the upload job's ``needs`` at
    ``resolve-target`` alone made it fail on the admission assertion;
    restoring each made it pass.
    """
    source = _source(Workflow.PUBLISH)
    assert source.count(PUBLICATION_FLAG) == 1, (
        f"{Workflow.PUBLISH} names {PUBLICATION_FLAG} "
        f"{source.count(PUBLICATION_FLAG)} times; exactly one step publishes "
        "the release"
    )

    jobs = _raw_jobs(Workflow.PUBLISH)
    holders = [
        job_id
        for job_id in jobs
        if any(
            PUBLICATION_FLAG in str(step.get("run") or "")
            for step in _steps(Workflow.PUBLISH, job_id)
        )
    ]
    assert holders == [PUBLICATION_JOB], (
        f"the release is published by {holders}; expected {[PUBLICATION_JOB]}"
    )

    permissions = jobs[PUBLICATION_JOB].get("permissions")
    assert isinstance(permissions, dict)
    assert "id-token" not in cast("dict[str, object]", permissions), (
        f"{PUBLICATION_JOB} holds `id-token`, which is not scoped to one "
        "audience: any step in a job carrying it can mint an OIDC token for "
        "whatever audience it names. Trusted publishing needs it; publishing "
        "a release does not"
    )

    assert UPLOAD_JOB in _needed(Workflow.PUBLISH, PUBLICATION_JOB), (
        "the release is published without waiting for the index upload. Both "
        "acts are one-way, but a failed upload should leave an unpublished "
        "draft rather than a release advertising a version PyPI does not carry"
    )
    # The upload sends the release's own attached distribution, so the release
    # must be proven to carry it before anything reaches the index. The proof
    # is the admission job's, because reading a draft takes a grant the job
    # holding `id-token` must not have.
    _index_of(Workflow.PUBLISH, ADMISSION_JOB, "gh release view")
    assert ADMISSION_JOB in _needed(Workflow.PUBLISH, UPLOAD_JOB), (
        "the index is written before the release is checked for its distribution"
    )
    _index_of(Workflow.PUBLISH, UPLOAD_JOB, "uv publish")

    flip = _index_of(Workflow.PUBLISH, PUBLICATION_JOB, PUBLICATION_FLAG)
    for advertisement, why in (
        ("gh workflow run channels.yml", "a channel pointer"),
        ("gh workflow run acquisition.yml", "the acquisition check"),
    ):
        position = _index_of(Workflow.PUBLISH, PUBLICATION_JOB, advertisement)
        assert position > flip, (
            f"{why} is dispatched for a release that is still a draft, whose "
            "download URLs serve nothing"
        )


def test_an_incomplete_release_is_never_edited_into_shape() -> None:
    """No lane demotes, promotes, or holds a release with the prerelease flag.

    That machinery existed because the release was published before its assets
    and had to be walked back. A draft cannot reach those states, so the
    mechanism has no domain left - and a dormant recovery path is
    indistinguishable from a working one until the day it is needed.

    The flag survives in exactly one place: the step that publishes the
    release, where a prerelease-named tag is published AS a prerelease. That is
    a publication choice made once, not a hold something else must undo.

    Mutation proof: restoring ``gh release edit "${TAG}" --prerelease`` to the
    cut made this fail naming ``release-please.yml``; adding a ``Hold the
    release`` step to the publication job made it fail naming that step;
    restoring each made it pass.
    """
    for workflow in (Workflow.BINARIES, Workflow.RELEASE_PLEASE, Workflow.CHANNELS):
        assert "--prerelease" not in _source(workflow), (
            f"{workflow} still edits a release's prerelease flag. The release "
            "is held as a draft now; holding it out of `latest` as well "
            "publishes it as a prerelease, because nothing promotes it back"
        )
    offenders = [
        str(step.get("name") or "")
        for job_id in _raw_jobs(Workflow.PUBLISH)
        for step in _steps(Workflow.PUBLISH, job_id)
        if "--prerelease" in str(step.get("run") or "")
        and PUBLICATION_FLAG not in str(step.get("run") or "")
    ]
    assert not offenders, (
        f"{offenders} name the prerelease flag outside the publication step. "
        "In this chain that flag is published WITH the release or not at all"
    )


def test_nothing_reacts_to_a_tag_or_a_release_event() -> None:
    """No workflow starts on a pushed tag or on a release event.

    Both events are traps here. A tag push would start a second publication of
    the same bytes beside the one the cut dispatches. A ``release`` event is
    inert for releases the default token creates, so a lane waiting for one
    never runs at all - and the whole chain's releases are created that way.
    Every release lane is dispatched explicitly, by the lane before it.

    Mutation proof: adding ``release: {types: [published]}`` to
    ``acquisition.yml`` made this fail naming that file and the release event,
    and adding ``push: {tags: ['vaultspec-rag-v*']}`` made it fail naming the
    tag filter; removing each made it pass.
    """
    findings: list[str] = []
    for name, document in workflows.documents():
        declared = workflows.triggers(document)
        if not isinstance(declared, dict):
            continue
        events = cast("dict[object, object]", declared)
        if "release" in events:
            findings.append(
                f"{name} starts on a release event, which never fires for a "
                "release the default token publishes"
            )
        push = events.get("push")
        if isinstance(push, dict) and "tags" in cast("dict[object, object]", push):
            findings.append(
                f"{name} starts on a pushed tag, which races the dispatch the "
                "cut already makes for that tag"
            )
    assert not findings, "\n".join(findings)
