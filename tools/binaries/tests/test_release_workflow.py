"""Guards for the public binary-release workflow boundary."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_HANDOFF = "- name: Hand the proven draft to the publication lane"


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
    """Artifact production exposes only its intentional release entrypoints.

    Mutation proof: restoring the publish tag-push trigger failed the trigger
    assertion; removing it passed immediately.
    """
    path = repo_root / ".github" / "workflows" / workflow
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on", document.get(True))

    assert set(triggers) == {"workflow_dispatch"}
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
    """The publication handoff follows the exact target archive gate.

    Mutation proof: removing the ``expected_name`` assertion from the release
    gate made this test fail at the named contract assertion; the guard was
    restored before the passing run.
    """
    text = _workflow(repo_root)
    ready = text.index("- name: Assert every declared target archive ready")
    upload = text.index('run: gh release upload "${TAG}" dist-bundles/* --clobber')
    verify = text.index("- name: Require every declared target on the draft release")
    handoff = text.index(_HANDOFF)

    release_gate = text[ready:upload]
    verify_gate = text[verify:handoff]

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
    assert verify < handoff
    assert "if: ${{ success() }}" in text[handoff:]


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
    lock = "group: release-artifacts-${{ inputs.tag }}"

    assert lock in binaries
    assert lock in publish
    assert "cancel-in-progress: false" in binaries
    assert "cancel-in-progress: false" in publish

    # A `./*` glob writes `./name` entries that never equal the release asset
    # names, so the final exact-coverage gate refuses publication.
    assert "sha256sum -- * > SHA256SUMS" in publish
    assert 'gh release download "${TAG}" --repo "$GITHUB_REPOSITORY"' in publish
    assert "--pattern SHA256SUMS --output inherited.txt" in publish
    assert "cat inherited.txt >> SHA256SUMS" in publish
    assert "LC_ALL=C sort -k2 -o SHA256SUMS SHA256SUMS" in publish
    assert 'gh release upload "${TAG}" dist/*' in publish
    assert '--repo "$GITHUB_REPOSITORY"' in publish


def test_release_artifacts_stay_bound_to_one_exact_commit(repo_root: Path) -> None:
    """The source checkout and every handoff carry one immutable release SHA.

    Mutation proof: substituting ``github.sha`` for the resolved build output
    failed the build SHA assertion; restoring it passed immediately.
    """
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
    assert publish["jobs"]["build"]["outputs"]["sha"] == (
        "${{ needs.resolve-target.outputs.sha }}"
    )
    assert publish["jobs"]["smoke-test"]["outputs"]["sha"] == (
        "${{ needs.build.outputs.sha }}"
    )
    assert publish["jobs"]["github-release"]["outputs"]["sha"] == (
        "${{ needs.smoke-test.outputs.sha }}"
    )
    assert publish["jobs"]["publish-pypi"]["outputs"] == {
        "tag": "${{ needs.resolve-target.outputs.tag }}",
        "sha": "${{ needs.resolve-target.outputs.sha }}",
    }
    publication = publish["jobs"]["publish-release"]
    assert publication["env"]["TAG"] == "${{ needs.publish-pypi.outputs.tag }}"

    publish_text = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    binaries_text = (repo_root / ".github" / "workflows" / "binaries.yml").read_text(
        encoding="utf-8"
    )
    assert "name: dist-${{ needs.resolve-target.outputs.sha }}" in publish_text
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


def test_release_please_proves_then_publish_dispatches_binaries(
    repo_root: Path,
) -> None:
    """The proven release tag starts packages, then their binary consumers.

    Mutation proof: inverting the tag-to-proven-commit comparison failed its
    assertion; restoring the comparison passed immediately.
    """
    text = (repo_root / ".github" / "workflows" / "release-please.yml").read_text(
        encoding="utf-8"
    )
    prove = text.index("- name: Require the tag on the proven commit")
    publish = text.index("- name: Trigger Publish workflow")
    proof_section = text[prove:publish]
    publish_section = text[publish:]

    assert "CREATED: ${{ steps.release.outputs.release_created }}" in proof_section
    assert "TAG: ${{ steps.release.outputs.tag_name }}" in proof_section
    assert "COMMIT: ${{ steps.merge.outputs.commit }}" in proof_section
    assert '[ "${CREATED}" != "true" ] || [ -z "${TAG}" ]' in proof_section
    assert '[ "${tagged}" != "${COMMIT}" ]' in proof_section
    assert "exit 1" in proof_section
    assert "TAG: ${{ steps.release.outputs.tag_name }}" in publish_section
    assert "--ref main" in publish_section
    assert '--field tag="${TAG}"' in publish_section
    assert "Trigger Binaries workflow" not in text

    config = json.loads(
        (repo_root / "release-please-config.json").read_text(encoding="utf-8")
    )
    assert config["packages"]["."]["draft"] is True
    assert config["packages"]["."]["force-tag-creation"] is True
    cut = _load(repo_root, "release-please.yml")["jobs"]
    assert cut["prove-gate"]["uses"] == "./.github/workflows/merge-gate.yml"
    assert cut["prove-gate"]["with"]["ref"] == "${{ needs.candidate.outputs.sha }}"
    assert cut["prove-hardware"]["uses"] == "./.github/workflows/hardware.yml"
    assert cut["prove-hardware"]["with"]["target_sha"] == (
        "${{ needs.candidate.outputs.sha }}"
    )
    assert set(cut["cut"]["needs"]) == {"candidate", "prove-gate", "prove-hardware"}
    steps = cut["cut"]["steps"]
    scripts = [str(step.get("run", "")) for step in steps]
    tag = next(
        i for i, run in enumerate(scripts) if '"${tagged}" != "${COMMIT}"' in run
    )
    dispatch = next(
        i for i, run in enumerate(scripts) if "gh workflow run publish.yml" in run
    )
    assert tag < dispatch
    assert '"${CREATED}" != "true"' in scripts[tag]
    assert '--field tag="${TAG}"' in scripts[dispatch]
    assert "--ref main" in scripts[dispatch]
    assert "--prerelease" not in "\n".join(scripts)


def test_publish_attaches_packages_before_dispatching_binaries(repo_root: Path) -> None:
    """Checksum-bearing draft packages precede the binary production request.

    Mutation proof: moving the binary dispatch before the package upload in a
    temporary workflow copy failed the ordering assertion; restoration passed.
    """
    downstream = _load(repo_root, "publish.yml")["jobs"]
    assert downstream["build"]["needs"] == "resolve-target"
    assert downstream["github-release"]["needs"] == ["resolve-target", "smoke-test"]
    attach = downstream["github-release"]["steps"]
    scripts = [str(step.get("run", "")) for step in attach]
    upload = next(i for i, run in enumerate(scripts) if "gh release upload" in run)
    dispatch = next(
        i for i, run in enumerate(scripts) if "gh workflow run binaries.yml" in run
    )
    assert upload < dispatch
    assert '--field target_sha="${TARGET_SHA}"' in scripts[dispatch]

    downstream = (repo_root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    draft = downstream.index("- name: Ensure a draft release exists for the tag")
    attach = downstream.index("- name: Attach wheel, sdist, and checksums")
    dispatch = downstream.index("- name: Trigger Binaries workflow")
    dispatch_section = downstream[dispatch:]
    assert "--draft" in downstream[draft:attach]
    assert "--verify-tag" in downstream[draft:attach]
    assert "needs: [resolve-target, smoke-test]" in downstream
    assert draft < attach < dispatch
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
    """Name every way *document* lets an unproven release request reach a job."""
    jobs = document["jobs"]
    findings: list[str] = []
    if any("uses" in step for step in jobs[resolver].get("steps") or []):
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
def test_a_release_request_is_proven_before_any_other_job(
    repo_root: Path, workflow: str, resolver: str
) -> None:
    """The dispatched tag is validated before any other job can see it.

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


def test_published_bundle_acquisition_checks_digests_and_producer_commit(
    repo_root: Path,
) -> None:
    """Public bundles are acquired after publication with verified provenance.

    Mutation proof: changing the dispatch producer to ``github.sha`` failed
    the producer environment assertion; restoring it passed immediately.
    """
    acquisition = (repo_root / ".github" / "workflows" / "acquisition.yml").read_text(
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

    document = _load(repo_root, "acquisition.yml")
    assert set(document.get("on", document.get(True))) == {
        "schedule",
        "workflow_dispatch",
    }
    publication = _load(repo_root, "publish.yml")["jobs"]["publish-release"]
    steps = publication["steps"]
    flip = next(i for i, step in enumerate(steps) if "--draft=false" in step["run"])
    dispatch = next(
        i
        for i, step in enumerate(steps)
        if "gh workflow run acquisition.yml" in step["run"]
    )
    assert flip < dispatch
    assert steps[dispatch]["env"]["TARGET_SHA"] == (
        "${{ needs.publish-pypi.outputs.sha }}"
    )
    assert '-f target_sha="$TARGET_SHA"' in steps[dispatch]["run"]


def test_package_index_publication_uses_the_proven_drafts_packages(
    repo_root: Path,
) -> None:
    """PyPI receives the checked distribution before the draft is published.

    An index upload cannot be withdrawn, so it must follow the archive gate.
    Running it alongside artifact production could publish an incomplete set.

    Mutation proof: pointing ``publish-pypi`` back at ``smoke-test`` failed the
    ``needs`` assertion; inverting the package asset check failed the missing
    distribution assertion. Each passed again once restored.
    Removing the per-package uniqueness checks failed the exact-entry
    assertion; it passed immediately after restoration.
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
    distribution = next(i for i, run in enumerate(steps) if "gh release view" in run)
    upload = next(i for i, run in enumerate(steps) if "uv publish" in run)
    assert "--json isDraft,assets" in steps[distribution]
    assert "[ ${#missing[@]} -ne 0 ]" in steps[distribution]
    assert '"vaultspec_rag-${version}-py3-none-any.whl"' in steps[distribution]
    assert '"vaultspec_rag-${version}.tar.gz" SHA256SUMS' in steps[distribution]
    assert "exit 1" in steps[distribution]
    assert distribution < upload
    assert "sha256sum -c ../packages.sha256" in steps[upload]
    assert steps[upload].index("sha256sum -c") < steps[upload].index("uv publish")
    for package in ("wheel", "sdist"):
        assert (
            f'awk -v name="${{{package}}}" \'$2 == name {{ count++ }} '
            "END { print count+0 }'"
        ) in steps[upload], "each package needs exactly one checksum entry"

    final = jobs["publish-release"]
    assert final["needs"] == "publish-pypi"
    assert "id-token" not in final["permissions"]
    scripts = [str(step.get("run", "")) for step in final["steps"]]
    flip = next(i for i, run in enumerate(scripts) if "--draft=false" in run)
    assert sum("--draft=false" in run for run in scripts) == 1
    assert '--prerelease="${prerelease}"' in scripts[flip]
    for advertisement in ("channels.yml", "acquisition.yml"):
        dispatch = next(
            i
            for i, run in enumerate(scripts)
            if f"gh workflow run {advertisement}" in run
        )
        assert flip < dispatch
    for job_id in ("build", "smoke-test", "github-release"):
        assert "publish-pypi" not in _upstream(jobs, job_id), job_id
    assert jobs["build"]["if"] == "${{ inputs.stage != 'package-index' }}"
    for job_id in jobs:
        if job_id in {"resolve-target", "build", "publish-pypi", "publish-release"}:
            continue
        assert "publish-pypi" not in _upstream(jobs, job_id), job_id
        assert "build" in _upstream(jobs, job_id), job_id

    binaries = _workflow(repo_root)
    verify = binaries.index(
        "- name: Require every declared target on the draft release"
    )
    handoff = binaries.index(_HANDOFF)
    assert verify < handoff
    assert "gh release edit" not in binaries
    assert "pypi.org" not in binaries[verify:handoff]
    finalizer = binaries[handoff:]
    assert "if: ${{ success() }}" in finalizer
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
