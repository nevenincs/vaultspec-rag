"""The package is built once, and every artifact carries those bytes.

Publish builds the wheel and sdist, smoke-tests them, attaches them to the
release and records their digests in SHA256SUMS. PyPI uploads the attached
files, checked against that manifest, and the binaries embed the attached
wheel, checked the same way. A second build anywhere in the release plane
would put different bytes behind the same version: a wheel build is
reproducible only as far as nothing asserts it is.
"""

from __future__ import annotations

import pathspec
import pytest

from dev.guards import _workflows as workflows
from dev.guards._ci_names import Workflow

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The one job that builds the package.
BUILDER = (Workflow.PUBLISH, "build")

#: Commands that produce a wheel or an sdist.
_BUILDING = ("uv build", "just build-python", "python -m build", "pip wheel")


#: The condition of a step that runs in a rehearsal and at no other time. A
#: rehearsal reaches no release, so it has no attached wheel to take and no
#: release its own build could put different bytes behind.
REHEARSAL_ONLY = "${{ inputs.rehearse }}"


def _runs(job: workflows.Job) -> list[str]:
    """Return every ``run:`` script in *job*."""
    return [str(step.get("run") or "") for step in job.steps]


def test_only_publish_builds_the_package() -> None:
    """No job but Publish's build produces a wheel or an sdist for a release.

    Mutation proof: restoring ``uv build --wheel --out-dir dist`` to the
    Binaries wheel job made this fail naming ``binaries.yml:wheel``;
    removing it made this pass. Taking the rehearsal condition off that job's
    rehearsal build failed the same way; restoring the condition passed.
    """
    builders = sorted(
        f"{job.workflow}:{job.job_id}"
        for job in workflows.load_jobs()
        if any(
            command in str(step.get("run") or "") and step.get("if") != REHEARSAL_ONLY
            for step in job.steps
            for command in _BUILDING
        )
    )
    assert builders == [f"{BUILDER[0]}:{BUILDER[1]}"], (
        f"the package is built by {builders}; only "
        f"{BUILDER[0]}:{BUILDER[1]} may build it, and every other job consumes "
        "the release's attached files"
    )


def test_the_binaries_embed_the_attached_wheel_checked_against_its_digest() -> None:
    """The wheel inside the binaries is the release's, verified before use.

    Mutation proof: deleting the ``sha256sum -c`` line made this fail on the
    missing digest check; restoring it made this pass.
    """
    wheel = next(
        job for job in workflows.load_jobs(Workflow.BINARIES) if job.job_id == "wheel"
    )
    script = "\n".join(_runs(wheel))
    assert "gh release download" in script, "the wheel is not taken from the release"
    assert "--pattern SHA256SUMS" in script, "the release manifest is not fetched"
    assert "sha256sum -c" in script, "the attached wheel is used unverified"


#: The action that writes artifacts into the job's checkout.
_DOWNLOAD_ACTION = "actions/download-artifact@"


def test_the_builder_downloads_nothing_its_sdist_would_carry() -> None:
    """Every artifact the builder downloads lies outside the sdist.

    The build backend collects the sdist from the checkout, leaving out only
    what version control ignores, so a download into an unignored directory
    is packed into the source distribution. The finalized monitors are
    hundreds of megabytes: carried there, they push the sdist past the
    package index's size limit and the upload is refused after the wheel
    has already gone out.

    Mutation proof: deleting ``/dist-monitor/`` from ``.gitignore`` made
    this fail naming ``dist-monitor/``; restoring it made this pass.
    """
    root = workflows.repository_root()
    ignored = pathspec.GitIgnoreSpec.from_lines(
        (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    )
    builder = next(
        job for job in workflows.load_jobs(BUILDER[0]) if job.job_id == BUILDER[1]
    )
    downloads = [
        str(step["with"].get("path") or ".") if "with" in step else "."
        for step in builder.steps
        if str(step.get("uses") or "").startswith(_DOWNLOAD_ACTION)
    ]
    assert downloads, f"{BUILDER[0]}:{BUILDER[1]} no longer downloads anything"
    carried = [
        path
        for path in downloads
        if not ignored.match_file(f"{path.rstrip('/')}/artifact")
    ]
    assert carried == [], (
        f"{BUILDER[0]}:{BUILDER[1]} downloads into {carried}, which version "
        "control does not ignore, so the sdist carries the downloaded files"
    )
