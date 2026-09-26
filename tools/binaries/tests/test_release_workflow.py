"""Guards for the public binary-release workflow boundary."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_PROMOTE = "- name: Promote the release, then publish it to the package index"


def _workflow(repo_root: Path) -> str:
    """Read the workflow whose release edge these assertions protect."""
    return (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
        encoding="utf-8"
    )


def _assert_immutable_action_pins(text: str) -> None:
    """Assert every action reference in *text* names a full commit SHA."""
    uses = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", text, re.M)
    assert uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in uses), uses


@pytest.mark.parametrize("workflow", ["binaries.yml", "publish.yml"])
def test_artifact_workflows_are_release_only(repo_root: Path, workflow: str) -> None:
    """Artifact production exposes only its intentional release entrypoints."""
    path = repo_root / ".github" / "workflows" / workflow
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))

    expected = {"workflow_dispatch"}
    if workflow == "publish.yml":
        expected.add("push")
        assert triggers["push"] == {"tags": ["vaultspec-rag-v*"]}
    assert set(triggers) == expected
    assert "tag" in triggers["workflow_dispatch"]["inputs"]


def test_binary_release_actions_are_immutably_pinned(repo_root: Path) -> None:
    """Privileged release actions resolve only reviewed immutable commits."""
    _assert_immutable_action_pins(_workflow(repo_root))


def test_binary_release_action_pin_guard_rejects_a_mutable_tag() -> None:
    """Mutation proof: a release action tag cannot satisfy the pin guard."""
    with pytest.raises(AssertionError, match="v7"):
        _assert_immutable_action_pins("    uses: astral-sh/setup-uv@v7\n")


def test_release_workflow_publishes_only_a_complete_archive_set(
    repo_root: Path,
) -> None:
    """Publication and promotion are downstream of the exact target archive gate.

    Mutation proof: removing the ``expected_name`` assertion from the release
    gate made this test fail at the named contract assertion; the guard was
    restored before the passing run.
    """
    text = _workflow(repo_root)
    ready = text.index("- name: Assert every declared target archive ready")
    upload = text.index('run: gh release upload "${TAG}" dist-bundles/* --clobber')
    verify = text.index("- name: Require artifacts on the published release")
    promote = text.index(_PROMOTE)

    release_gate = text[ready:upload]
    verify_gate = text[verify:promote]

    assert ready < upload
    assert 'expected_name="${TAG}-${triple}${suffix}"' in release_gate
    assert 'expected_names+=("${expected_name}")' in release_gate
    assert "raw=()" in release_gate
    assert "unexpected=()" in release_gate
    assert "exit 1" in release_gate

    assert 'expected_name="${TAG}-${triple}${suffix}"' in verify_gate
    assert "bundle_archives=()" in verify_gate
    assert "raw=()" in verify_gate
    assert "RELEASE_RESULT" in verify_gate
    assert 'wheel="vaultspec_rag-${version}-py3-none-any.whl"' in verify_gate
    assert 'sdist="vaultspec_rag-${version}.tar.gz"' in verify_gate
    assert "sha256sum -c SHA256SUMS" in verify_gate
    assert "vaultspec-rag-*|vaultspec-search-mcp-*)" in verify_gate
    assert verify < promote
    assert "if: ${{ success() }}" in text[promote:]


def test_python_and_binary_release_workflows_share_the_checksum_lock(
    repo_root: Path,
) -> None:
    """The two asset publishers serialize their shared checksum update.

    Mutation proof: changing the publish workflow back to its private
    ``publish-*`` concurrency group made the shared-lock assertion fail; the
    common per-tag group was restored before the passing run. Reverting the
    checksum producer to ``sha256sum ./*`` made the bare-name assertion fail;
    the bare-name producer was restored before the passing run.
    """
    binaries = _workflow(repo_root)
    publish = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    lock = "group: release-artifacts-${{ inputs.tag || github.ref_name }}"

    assert lock in binaries
    assert lock in publish
    assert "cancel-in-progress: false" in binaries
    assert "cancel-in-progress: false" in publish

    # A `./*` glob writes `./name` entries that never equal the release asset
    # names, so the final exact-coverage gate demotes every release.
    assert "sha256sum -- * > SHA256SUMS" in publish
    assert 'gh release download "${TAG}" --repo "$GITHUB_REPOSITORY"' in publish
    assert "--pattern SHA256SUMS --output inherited.txt" in publish
    assert "cat inherited.txt >> SHA256SUMS" in publish
    assert "LC_ALL=C sort -k2 -o SHA256SUMS SHA256SUMS" in publish
    assert 'gh release upload "${TAG}" dist/*' in publish
    assert '--repo "$GITHUB_REPOSITORY"' in publish


def test_release_artifacts_stay_bound_to_one_exact_commit(repo_root: Path) -> None:
    """The source checkout and every handoff carry one immutable release SHA."""
    publish = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "publish.yml").read_text(
            encoding="utf-8"
        )
    )
    binaries = yaml.safe_load(
        (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
            encoding="utf-8"
        )
    )

    assert publish["jobs"]["resolve-target"]["outputs"]["sha"] == (
        "${{ steps.commit.outputs.sha }}"
    )
    assert publish["jobs"]["hold-release"]["outputs"]["sha"] == (
        "${{ needs.resolve-target.outputs.sha }}"
    )
    assert publish["jobs"]["build"]["outputs"]["sha"] == (
        "${{ needs.hold-release.outputs.sha }}"
    )
    assert publish["jobs"]["smoke-test"]["outputs"]["sha"] == (
        "${{ needs.build.outputs.sha }}"
    )
    assert publish["jobs"]["github-release"]["outputs"]["sha"] == (
        "${{ needs.smoke-test.outputs.sha }}"
    )

    publish_text = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    binaries_text = (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
        encoding="utf-8"
    )
    assert "name: dist-${{ needs.hold-release.outputs.sha }}" in publish_text
    assert "name: dist-${{ needs.build.outputs.sha }}" in publish_text
    assert "name: dist-${{ needs.smoke-test.outputs.sha }}" in publish_text
    assert '--field target_sha="${TARGET_SHA}"' in publish_text
    triggers = binaries.get("on", binaries.get(True))
    assert triggers["workflow_dispatch"]["inputs"]["target_sha"]["required"] is True
    assert "name: project-wheel-${{ inputs.target_sha }}" in binaries_text
    assert "name: binaries-${{ inputs.target_sha }}-${{ matrix.name }}" in binaries_text
    assert "pattern: binaries-${{ inputs.target_sha }}-*" in binaries_text
    assert "ref: ${{ inputs.target_sha }}" in binaries_text
    assert "git rev-parse HEAD" in binaries_text


def test_release_please_holds_then_publish_dispatches_binaries(
    repo_root: Path,
) -> None:
    """Release Please holds stable/latest and starts the sequenced publisher.

    Mutation proof: removing the prerelease hold made this assertion fail on
    the named release-state guard; the hold was restored before the passing
    run.
    """
    text = (repo_root / ".github" / "workflows" / "release-please.yml").read_text(
        encoding="utf-8"
    )
    hold = text.index(
        "- name: Hold the release out of latest until artifacts are complete"
    )
    publish = text.index("- name: Trigger Publish workflow")
    hold_section = text[hold:publish]
    publish_section = text[publish:]

    assert "--prerelease" in hold_section
    assert "steps.release.outputs.tag_name" in hold_section
    assert "steps.release.outputs.release_created == 'true'" in publish_section
    assert "TAG: ${{ steps.release.outputs.tag_name }}" in publish_section
    assert "--ref main" in publish_section
    assert '--field tag="${TAG}"' in publish_section
    assert "Trigger Binaries workflow" not in text

    downstream = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    hold = downstream.index("- name: Hold the release as a prerelease")
    dispatch = downstream.index("- name: Trigger Binaries workflow")
    dispatch_section = downstream[dispatch:]
    assert "needs: hold-release" in downstream
    assert "--prerelease" in downstream[hold:dispatch]
    assert "needs: [resolve-target, github-release]" in downstream
    assert "gh workflow run binaries.yml \\" in dispatch_section
    assert '--field tag="${TAG}"' in dispatch_section


def _load(repo_root: Path, workflow: str) -> dict:
    """Return *workflow* parsed as YAML."""
    return yaml.safe_load(
        (repo_root / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    )


def _upstream(jobs: dict, job_id: str) -> set[str]:
    """Return every job *job_id* transitively needs."""
    seen: set[str] = set()
    pending = [job_id]
    while pending:
        needs = jobs[pending.pop()].get("needs") or []
        for name in [needs] if isinstance(needs, str) else needs:
            if name not in seen:
                seen.add(name)
                pending.append(name)
    return seen


def _release_request_findings(document: dict, resolver: str) -> list[str]:
    """Name every way *document* lets an unproven release request reach the fleet."""
    jobs = document["jobs"]
    findings: list[str] = []
    resolving = jobs[resolver]
    if resolving.get("runs-on") != "ubuntu-24.04":
        findings.append(f"{resolver} does not run on a hosted runner")
    if any("uses" in step for step in resolving.get("steps") or []):
        findings.append(f"{resolver} runs an action before the request is proven")
    for job_id, body in jobs.items():
        if job_id == resolver:
            continue
        if "uses" not in body and resolver not in _upstream(jobs, job_id):
            findings.append(f"{job_id} does not wait for {resolver}")
    if "github.ref_name" in yaml.safe_dump(jobs):
        findings.append("a job still falls back to github.ref_name")
    return findings


@pytest.mark.parametrize(
    ("workflow", "resolver"),
    [("publish.yml", "resolve-target"), ("binaries.yml", "validate")],
)
def test_a_release_request_is_proven_on_a_hosted_runner_first(
    repo_root: Path, workflow: str, resolver: str
) -> None:
    """The dispatched tag is validated before any fleet job can see it.

    Mutation proof: pointing the binaries ``wheel`` job's ``needs`` away from
    ``validate`` made this fail naming ``wheel``; restoring it made it pass.
    """
    assert _release_request_findings(_load(repo_root, workflow), resolver) == []


def test_the_release_request_resolvers_check_format_and_existence(
    repo_root: Path,
) -> None:
    """Both resolvers pin the tag format and read the tag off the remote."""
    for workflow, resolver in (
        ("publish.yml", "resolve-target"),
        ("binaries.yml", "validate"),
    ):
        script = "\n".join(
            str(step.get("run", ""))
            for step in _load(repo_root, workflow)["jobs"][resolver]["steps"]
        )
        assert "^vaultspec-rag-v[0-9]+\\.[0-9]+\\.[0-9]+" in script, workflow
        assert "git ls-remote --tags" in script, workflow
        assert '"^{}"' in script, workflow
    binaries = "\n".join(
        str(step.get("run", ""))
        for step in _load(repo_root, "binaries.yml")["jobs"]["validate"]["steps"]
    )
    assert '[ "${sha}" != "${TARGET_SHA}" ]' in binaries


def test_promotion_waits_for_checksum_verified_bundle_acquisition(
    repo_root: Path,
) -> None:
    """Public x64/ARM bundles must load before a stable release is promoted."""
    acquisition = (repo_root / ".github" / "workflows" / "acquisition.yml").read_text(
        encoding="utf-8"
    )
    binaries = (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
        encoding="utf-8"
    )

    assert "${tag}-${TRIPLE}${ARCHIVE_SUFFIX}" in acquisition
    assert '"${release_url}/SHA256SUMS"' in acquisition
    assert 'sha256sum -c "${archive}.sha256"' in acquisition
    assert "producer_sha=$(jq -er '.source_revision" in acquisition
    assert '[ "${producer_sha}" = "${TARGET_SHA}" ]' in acquisition
    assert 'tar -xOzf "${archive}"' in acquisition
    assert 'unzip -p "${archive}"' in acquisition
    assert "vaultspec-rag-${TRIPLE}" not in acquisition
    assert "vaultspec-search-mcp-${TRIPLE}" not in acquisition

    wait = binaries.index("- name: Require the acquisition check for this release")
    promote = binaries.index(_PROMOTE)
    section = binaries[wait:promote]
    assert '-f target_sha="$TARGET_SHA"' in section
    assert "before_id=$(gh run list" in section
    assert ".databaseId > ${before_id}" in section
    assert 'gh run watch "$run_id"' in section
    assert "--exit-status" in section
    assert wait < promote


def test_package_index_publication_follows_promotion(repo_root: Path) -> None:
    """PyPI receives only a release the final archive gate promoted.

    An index upload cannot be withdrawn, so it must come after the gate and
    the promotion, never before them in the release chain.

    Mutation proof: pointing ``publish-pypi`` back at ``smoke-test`` failed the
    ``needs`` assertion; dispatching the package-index stage ahead of the
    promotion failed the ordering assertion; dropping the full-release check
    failed the ``isDraft or .isPrerelease`` assertion. Each passed again once
    restored.
    """
    publish = _load(repo_root, "publish.yml")
    jobs = publish["jobs"]
    stage = publish.get("on", publish.get(True))["workflow_dispatch"]["inputs"]["stage"]
    assert stage["type"] == "choice"
    assert stage["options"] == ["release", "package-index"]
    assert stage["default"] == "release"

    index = jobs["publish-pypi"]
    assert index["needs"] == "resolve-target"
    assert index["if"] == "${{ inputs.stage == 'package-index' }}"
    assert index["environment"] == {"name": "pypi"}
    assert index["permissions"]["id-token"] == "write"
    steps = [str(step.get("run", "")) for step in index["steps"]]
    promoted = next(i for i, run in enumerate(steps) if "isPrerelease" in run)
    upload = next(i for i, run in enumerate(steps) if "uv publish" in run)
    assert "if .isDraft or .isPrerelease then error(" in steps[promoted]
    assert promoted < upload
    assert "sha256sum -c ../packages.sha256" in steps[upload]

    # The release stage never waits on the index, and every job in it is
    # skipped with the hardware gate when only the index stage was requested.
    assert jobs["hardware-validation"]["if"] == (
        "${{ inputs.stage != 'package-index' }}"
    )
    for job_id in jobs:
        if job_id in {"resolve-target", "hardware-validation", "publish-pypi"}:
            continue
        assert "publish-pypi" not in _upstream(jobs, job_id), job_id
        assert "hardware-validation" in _upstream(jobs, job_id), job_id

    binaries = _workflow(repo_root)
    verify = binaries.index("- name: Require artifacts on the published release")
    promote = binaries.index(_PROMOTE)
    assert "pypi.org" not in binaries[verify:promote]
    finalizer = binaries[promote:]
    assert "if: ${{ success() }}" in finalizer
    assert finalizer.index("--prerelease=false") < finalizer.index(
        "gh workflow run publish.yml"
    )
    assert "-f stage=package-index" in finalizer


#: The inherited-manifest rewrite in a checksum merge, as the workflow spells it.
_BARE_NAMES = re.compile(
    r"sed -i -E 's#(?P<pattern>[^#]+)#(?P<replacement>[^#]*)#' inherited\.txt"
)


@pytest.mark.parametrize("workflow", ["publish.yml", "binaries.yml"])
def test_checksum_merge_reads_legacy_names_bare(repo_root: Path, workflow: str) -> None:
    """A re-run repairs a manifest that still lists ``./name`` entries.

    Such an entry never equals its release asset name, so unless the merge
    rewrites it before replacing entries by name, a re-run keeps it and the
    exact-coverage gate refuses the release again.

    Mutation proof: deleting the rewrite failed the ``found`` assertion, and a
    rewrite that kept the ``./`` failed the manifest comparison, for both
    workflows. Each passed again once restored.
    """
    text = (repo_root / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    merge = text.index("--pattern SHA256SUMS --output inherited.txt")
    replace = text.index('grep -v -- "  ${name}$" inherited.txt', merge)
    found = _BARE_NAMES.search(text, merge, replace)
    assert found is not None, workflow

    digest = "0" * 64
    inherited = (
        f"{digest}  ./vaultspec_rag-1.0.0.tar.gz\n"
        f"{digest}  vaultspec-rag-v1.0.0-x86_64-pc-windows-msvc.zip\n"
    )
    rewritten = re.sub(found["pattern"], found["replacement"], inherited, flags=re.M)
    assert rewritten == (
        f"{digest}  vaultspec_rag-1.0.0.tar.gz\n"
        f"{digest}  vaultspec-rag-v1.0.0-x86_64-pc-windows-msvc.zip\n"
    )
