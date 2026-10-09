# Releasing vaultspec-rag

This is the maintainer runbook for publishing the Python package, standalone
binary bundles, and package-manager pointers. The release pipeline is
autonomous after a maintainer merges the release PR. The proposal must pass full
checks and Dev Server proof before merge; no further dispatch or pin review is needed.
This document records
the artifact contract, the gates a release must pass before it is published at
all, and the recovery paths when a lane stalls.

## Release contract

Release tags use the form `vaultspec-rag-v<version>`. A complete GitHub
Release carries the Python wheel and source distribution, one validated binary
archive for every supported target, and one merged `SHA256SUMS` file covering
all of those top-level artifacts.

The RAG binary matrix currently supports these targets:

| Target         | Public archive                                              | Channel  |
| -------------- | ----------------------------------------------------------- | -------- |
| Windows x86-64 | `vaultspec-rag-v<version>-x86_64-pc-windows-msvc.zip`       | Scoop    |
| Linux x86-64   | `vaultspec-rag-v<version>-x86_64-unknown-linux-gnu.tar.gz`  | Homebrew |
| Linux arm64    | `vaultspec-rag-v<version>-aarch64-unknown-linux-gnu.tar.gz` | Homebrew |
| macOS arm64    | `vaultspec-rag-v<version>-aarch64-apple-darwin.tar.gz`      | Homebrew |

The RAG backend uses CUDA on Windows/Linux and MPS on Apple silicon. Intel Macs
are unsupported. The monitor frontend starts independently of an accelerator.
Linux archives require the glibc floor
recorded in their `manifest.json`; the Homebrew formula repeats the applicable
caveat.

Each archive contains exactly these release members:

- `vaultspec-rag` (or `vaultspec-rag.exe` on Windows)
- `vaultspec-search-mcp` (or `vaultspec-search-mcp.exe` on Windows)
- `vaultspec-rag-monitor` (or `vaultspec-rag-monitor.exe` on Windows)
- `LICENSE`
- `README.txt`
- `manifest.json`

The target-qualified executable names used in the build directory are staging
names. They are not public download names and must never be uploaded to a
release. The archive-local manifest describes the product, version, target,
per-component runtimes and requirements, platform floor, and SHA-256 of each member.
Schema `vaultspec.release-bundle.v2` distinguishes the Bun frontend from the PyApp
backend commands. Monitor evidence binds its final hash, producer, npm lock and common
frontend manifest digest to native browser verification. The enclosing Linux floor
remains glibc 2.39; the monitor records its own measured requirement. The manifest does not
contain the enclosing archive's digest; that digest belongs in the release's
top-level `SHA256SUMS` file.

The user-facing installation and verification commands are in
[the installation guide](docs/installation.md#install-without-python).

## How the release runs

A release is invisible until it is complete. The GitHub Release is created as a
**draft**, every lane attaches to that draft, and one step at the very end of
the chain takes it out of draft. A draft has no download URLs and never answers
as `latest`, so a failure anywhere leaves a draft nobody has been sent to
rather than a live release to be walked back.

Nothing in the chain reacts to a pushed tag or to a `release` event. Each lane
is dispatched explicitly by the lane before it, in this order:

1. `release-please.yml` opens and updates the release PR from conventional
   commits on pushes to `main`. After the final lockfile refresh it dispatches
   the full merge gate and the canonical Dev Server check on the release branch.
   The required aggregate includes the actual Dev Server verdict on the exact SHA;
   light or skipped measuring jobs cannot authorize the release proposal. The full
   dispatch releases the bot PR's held merge gate automatically.
1. Merging that PR starts the cut automatically. It proves the merged commit
   with the full merge gate and both accelerator tiers, then has release-please
   force the tag and create the draft Release. The cut checks the tag against
   the proven commit and dispatches `RAG Publish`. Manual dispatch is recovery only.
1. `RAG Publish`, release stage, builds the wheel and source distribution,
   smoke-tests both across the supported Python versions, and attaches them
   with a merged `SHA256SUMS` to the draft. It creates the draft itself only if
   one is missing, for a tag a maintainer pushed by hand. It never edits an
   existing release's flags, and it does not upload to PyPI in this stage. It
   then dispatches `RAG Binaries`.
1. `RAG Binaries` takes the release's own attached wheel, checked against
   `SHA256SUMS`, and verifies that it contains the exact canonical monitor lifecycle
   and inventory owners. One job restores `package-lock.json` with npm and builds
   Vite once. Every native target receives that exact handoff, verifies its digest,
   and compiles the server with the committed Bun archive/executable pins.
   Windows resources, macOS signing and Unix modes are finalized before hashing.
   Each target must pass the isolated executable and installed-browser probe before
   packaging. An isolated job attests the four finalized archives with GitHub/Sigstore
   provenance after their native proof; it holds the OIDC grant without checking out
   project code or writing release assets. Its release job aggregates the archive checksums, passes
   the complete-target gate, and attaches only the public archives and the
   merged checksum file to the draft.
1. `RAG Binaries` always runs `verify-release-assets` after its release job.
   The verifier derives the expected targets from the matrix and requires every
   correctly named archive, the exact wheel and source distribution, no raw
   executables, exact `SHA256SUMS` coverage with valid digests, and a
   successful binary release job. It verifies all four monitor proofs against the
   common frontend digest and authenticated repository/workflow/tag/source identity.
   Missing or invalid attestation fails the draft verifier; generated checksums alone
   do not authorize publication.
1. Only on success, that gate dispatches `RAG Publish` in its `package-index`
   stage. Its admission job requires the release to carry its wheel, source
   distribution, and `SHA256SUMS`, downloads the release's own packages, checks
   them against the release's `SHA256SUMS`, and independently admits all four
   archives against their authenticated provenance. Its upload job receives exactly
   those package bytes, checks them against the digests admission read, and
   sends them to PyPI through the trusted publisher. The two are separate jobs
   because reading a draft takes a token that may write releases, and the job
   holding `id-token` holds nothing else. An already-published release is
   accepted so a failed upload can be retried; PyPI skips files it already
   holds.
1. A third job in that same run then publishes the release, as the last act
   of the chain. It holds no `id-token`. PyPI comes first deliberately: both
   acts are one-way, and a failed upload leaves an unpublished draft that a
   re-dispatch repairs, while a release published first would advertise a
   version the index does not carry. A tag containing `rc`, `alpha`, `beta`, or
   `dev` is published as a prerelease and stays off `latest`.
1. That job then dispatches `RAG Channels` and `RAG Acquisition` for the tag.
   Both advertise or consume public download URLs, so neither can run before
   the flip: the channel lane refuses a draft outright, and the acquisition
   check downloads unauthenticated and cannot see one. A failure in either does
   not retract the release; re-dispatch that lane for the same tag.

`RAG Publish` and `RAG Binaries` share the concurrency group
`release-artifacts-<tag>` with `cancel-in-progress: false`. This serializes
updates to the one remote `SHA256SUMS` asset while allowing a failed lane to be
rerun for the same tag.

## Cutting a release

1. Merge feature work to `main` with conventional commit messages such as
   `feat:`, `fix:`, or `perf:`.
1. Review the release PR's version, changelog, manifest and lockfile. Wait for
   full lint, both Linux interpreters, Windows tests, dependency audit and Dev Server
   proof. The bot dispatches those checks and releases its held required gate;
   no label or workflow approval is needed.
1. Press the release PR's merge button. This is the only human release action.
   The merge starts exact-commit checks, CUDA/MPS proof, tag/draft creation,
   package and binary builds, provenance verification, PyPI upload, GitHub
   publication and the channel/acquisition handoffs automatically.

The release stays a draft until all artifacts are verified and PyPI accepts the
packages. A failure reports red and leaves the draft unpublished where possible.
Recovery commands below are for failed releases, not normal release steps.
Do not use the administrator bypass to merge before the full proposal gate passes.

## What a cut needs from the fleet

The fleet must continuously provide these prerequisites; the workflow does not ask
for per-release setup.

- **Release Please may open pull requests.** The repository setting "Allow
  GitHub Actions to create and approve pull requests" must be on, or the
  proposal branch is pushed and no pull request appears:

  ```sh
  gh api repos/nevenincs/vaultspec-rag/actions/permissions/workflow \
    --jq .can_approve_pull_request_reviews
  ```

- **The CUDA host's accelerator is free.** The GPU tier starts its own service
  and refuses to while an installed `vaultspec-rag` service owns the device.
  Use a runner GPU available to the CI service. An unavailable device fails the
  hardware gate rather than silently skipping accelerator proof.

- **The Apple-silicon host is awake.** It carries the MPS tier, the macOS
  build and the Linux arm64 runner, and its runners go offline when it sleeps.

- **Every Linux runner has a browser.** The native monitor proof drives an
  installed Chrome or Chromium and never downloads one, so the browser belongs
  to the runner image.

- **The Windows host denies outbound traffic to the proof's two program
  paths, and names their directory in the runner's environment.** See
  [the Windows outbound-denied directory](#the-windows-outbound-denied-directory).

## Rehearsing the binaries lane

`RAG Binaries` runs from a release tag, so nothing on `main` exercises it and a
defect in it is otherwise found at a cut. A rehearsal builds and proves a
branch or `main` commit on all four targets and stops before the first write:
it reads no release, attaches nothing and dispatches no other lane.

```sh
SHA=$(git rev-parse origin/<branch>)
gh workflow run binaries.yml --repo "$REPO" --ref <branch> \
  --field tag=vaultspec-rag-v<version> --field target_sha="$SHA" \
  --field rehearse=true
```

The tag names the version the binaries are built as and must match the
version that commit declares; no such tag needs to exist. Rehearse after
changing `binaries.yml`, a release recipe, or a fleet runner.

## Reproducing the binary artifacts locally

Run each target on its native matrix host with an installed Chrome, Chromium or Edge
browser. Build the Vite handoff once and carry it unchanged to the other hosts.
Start with an empty `dist`, `dist-bin`, `dist-monitor-frontend`, and `dist-bundles` output set so
the exact-wheel and exact-target checks cannot select stale files.

```sh
TAG=vaultspec-rag-v<version>
TARGET=<native-target-triple>
PRODUCER_SHA=$(git rev-parse HEAD)

uv python install 3.13
npm ci
just release-monitor-frontend "$TAG" "$PRODUCER_SHA"
FRONTEND_SHA256=$(uv run --no-project --python 3.13 -- python -c \
  "import hashlib; from pathlib import Path; print(hashlib.sha256(Path('dist-monitor-frontend/frontend.json').read_bytes()).hexdigest())")
uv build --wheel --out-dir dist

uv run --no-project --python 3.13 -- python -m tools.monitor.release wheel --tag "$TAG" --directory dist
just release-binaries "$TAG" "$TARGET" dist-bin dist
just release-monitor "$TAG" "$PRODUCER_SHA" "$FRONTEND_SHA256"
uv run --no-project --python 3.13 -- python -m tools.monitor.release native-smoke \
  --tag "$TAG" --source-revision "$PRODUCER_SHA" --target "$TARGET" --directory dist-bin
just release-bundle "$TAG" "$TARGET" dist-bin dist-bundles

just release-checksums dist-bundles dist-bundles/SHA256SUMS
(cd dist-bundles && sha256sum -c SHA256SUMS)
```

`just release-binaries` requires exactly one wheel in `dist` and builds from
that wheel rather than resolving a published package. `just release-bundle`
requires all three finalized target-qualified files and `dist-bin/monitor-smoke.json`,
verifies the archive before
writing its `.sha256` sidecar, and gives the extracted commands their stable
names. `just release-checksums` creates an archive-only local view. The GitHub
workflow merges that view with the wheel and source-distribution entries
already attached to the Release before uploading `SHA256SUMS`.

Never use `dist-bin` as a release upload directory. It is a private staging
directory; `dist-bundles` is the public archive boundary.

The release build requires a clean producer checkout matching `PRODUCER_SHA`.
For a dirty local prototype, the compiler supports `--development`; its executable
reports that marker and release packaging refuses it.

## Complete-target and checksum gates

The release job reads the `target:` values from
[.github/workflows/binaries.yml](.github/workflows/binaries.yml), rather than
maintaining a second hand-written target list. For every declared target it
requires exactly one archive with the expected tag, target triple, and format:

- `*-windows-msvc` must be a ZIP archive.
- Other supported targets must be TAR.GZ archives.
- A missing archive, duplicate format, unexpected archive, or raw file fails
  the gate before `gh release upload` runs.

The final verifier repeats the check against the assets actually present on
the draft Release. This second check matters when a matrix leg fails before the
release job runs, or when an existing draft already contains an incomplete
asset set. It also requires that the binary release job itself succeeded. It is
the only thing that dispatches the publication, so a release it refuses is
never published and never reaches PyPI.

Both artifact workflows reconcile `SHA256SUMS` in the same way:

1. Generate the entries for the artifacts produced by the current workflow.
1. Download the existing `SHA256SUMS` from the same tag when it exists, and
   read any legacy `./name` entry as `name`.
1. Remove inherited entries for the filenames being replaced.
1. Append the current entries and sort by filename.
1. Upload the merged file with `--clobber`.

This makes reruns idempotent and preserves the other workflow's completed
entries. Do not replace the remote file with a binary-only checksum list, edit
it by hand, or attach raw staging files to repair a release.

## Verifying a monitor candidate

For an optional developer rehearsal, dispatch the private native verification lane
on the commit to be checked. Normal release builds already perform native proof:

```sh
gh workflow run acquisition.yml --repo "$REPO" --ref main \
  --field mode=candidate --field tag=vaultspec-rag-v0.6.0
```

The version input names the candidate; this command creates no tag or release.
One frontend build is bound to the dispatched commit and npm lock, then embedded
by the verified native compiler on all four targets. Each target renders the
finalized monitor in an installed browser and repeats the smoke under OS outbound
denial. The private Actions artifacts retain binaries, hashes and smoke reports.

Acquisition runs each target on the enrolled host that builds it for a release,
so a host that cannot prove a monitor is found here and not at a cut.

Linux uses a process-scoped kernel filter; macOS uses a process sandbox allowing
loopback; Windows uses firewall rules on two program paths, described below. The
browser driver stays outside each platform's OS policy. The external TCP control
must connect outside the policy and fail under it, while the compiled monitor
serves loopback HTTP. Failure leaves release admission closed. Candidate
verification is separate from acquisition of the final published archives.

### The Windows outbound-denied directory

A Windows Firewall rule can only be added by an Administrator, and a runner
account is deliberately not one. So the rules are added once per host, and each
proof only occupies them. The host carries a directory the runner may write,
with outbound traffic denied to two fixed program paths inside it. A proof
copies the pinned network control into both paths and requires each copy to
fail to connect, having first connected from an ordinary path. Only then does
the monitor take its path, so it runs under a denial that run watched work.

The host provides that directory and names it in `MONITOR_OUTBOUND_DENIED_DIR`.
On the fleet's Windows runner both come from the fleet: its repository declares
the directory and the two rules, converges them from an elevated session, and
writes the variable into the runner's environment. No workflow here sets it.

To run the Windows proof on another machine, create the two rules once from
an elevated PowerShell session and set the variable to the directory:

```powershell
$directory = 'C:\outbound-denied'
New-Item -ItemType Directory -Force -Path $directory | Out-Null
foreach ($name in 'monitor.exe', 'network-control.exe') {
  New-NetFirewallRule -DisplayName outbound-denied -Direction Outbound `
    -Action Block -Profile Any -Program (Join-Path $directory $name) | Out-Null
}
$env:MONITOR_OUTBOUND_DENIED_DIR = $directory
```

A proof that reports its blocked control still connects is on a host whose
rules are missing or whose firewall profiles are disabled.

## Automated monitor provenance

The four native release archives are attested after finalized-byte browser and
OS-offline proof. The signing job contains no checkout or project code and can
write attestations, but cannot write repository contents. Release attachment waits
for this job; the draft verifier and package-index admission both authenticate the
attached archives before publication.

Verification requires the `nevenincs/vaultspec-rag` repository,
`.github/workflows/binaries.yml` signer, the exact release tag ref and the exact
producer/signing commit. The signature authenticates archive digests; monitor hashes,
source, npm lock and common frontend evidence are then read from those authenticated
archives. GitHub's CLI verifies the Sigstore signature and certificate identity.
The former manually reviewed catalog and candidate-pin handoff are removed.

After publication, `RAG Acquisition` verifies this provenance before inspecting or
extracting the downloaded archive and rechecks executable digests before launch.
Live `SHA256SUMS` remains an additional consistency check. Git, GitHub CLI, Node and
an installed browser are verification-runner prerequisites; they are not runtime
requirements of the delivered monitor. Compiler/runtime provisioning still uses
reviewed committed SHA256 pins. Releases predating archive attestations are refused
by this verifier rather than admitted from live checksums alone.

## Package-manager publication

Scoop and Homebrew pointers live in the account repository
`nevenincs/homebrew-tap`, not in this product repository. Users add that
repository once:

```powershell
scoop bucket add nevenincs https://github.com/nevenincs/homebrew-tap
scoop install vaultspec-rag
```

```sh
brew tap nevenincs/tap https://github.com/nevenincs/homebrew-tap
brew install vaultspec-rag
```

The pointers are published by `RAG Channels`, a dispatch-only lane the
publication dispatches once the release is public. A Scoop manifest and a
Homebrew formula address assets by release download URL, so they advertise a
release rather than form part of it: pushed while the release was still a draft
they would send every package manager at a URL that serves nothing. The lane
refuses a draft, reads `SHA256SUMS` back from the published release rather than
from a build directory, and holds the channel deploy key and nothing else - the
job that uploads to PyPI carries `id-token: write`, and that grant has no
business beside a deploy key.

It runs the equivalent of:

```sh
just release-channels "$TAG" channels published/SHA256SUMS
```

Here `channels` is a checkout of `nevenincs/homebrew-tap` and
`published/SHA256SUMS` is downloaded from the release. The command generates
and validates both pointers from the same aggregate checksum file. The
generator refuses a backward version bump, refuses missing digests, and omits
unsupported or unavailable Homebrew targets rather than inventing a pointer. A
missing supported build is reported as a warning; the complete target gate must
still pass before a release is published at all.

Only these files belong in the channel commit:

```sh
git -C channels add -- bucket/vaultspec-rag.json Formula/vaultspec-rag.rb
git -C channels diff --cached -- bucket Formula
```

If the staged diff is non-empty, commit with the bot identity and push
`main`. Never use `git add .` in the account repository: it carries pointers
for multiple products and may contain another maintainer's work. The workflow
uses a bounded fetch/rebase/push retry and never force-pushes. The Homebrew
formula is a binary formula and contains one archive URL and digest per
available Linux or Apple silicon target; the Scoop manifest contains the single Windows bundle
URL and digest.

## Recovery

The release remains a draft until the chain finishes. Repair a failed lane for the
**same tag**. Attestation failures must be diagnosed before publication is retried.
Never publish a draft by hand to
unstick a lane - the publication is the statement that everything above it
passed.

Set the repository and exact tag before inspecting or rerunning anything. A
draft is not listed by `gh release list` without `--exclude-drafts=false`, and
`gh release view` reads it by tag:

```sh
REPO=nevenincs/vaultspec-rag
TAG=vaultspec-rag-v<version>

gh release view "$TAG" --repo "$REPO" --json isDraft,isPrerelease,assets \
  --jq '{isDraft, isPrerelease, assets: [.assets[].name]}'
gh run list --repo "$REPO" --workflow Binaries --limit 20
gh run list --repo "$REPO" --workflow Publish --limit 20
```

### A merged release that was never tagged

The release cut fails in `Create the release for the merged proposal` with
`Resource not accessible by integration`, and its
`Name a release this token cannot tag` step names the tag. The workflow token
never holds the `workflows` permission, and without it GitHub refuses any tag
or Release that targets a commit whose workflow files differ from `main`, even
once the tag exists. A workflow change that landed between the release commit's
merge and its tag, as when a proposal merged by hand waits for its cut,
therefore blocks the release for good: no rerun or later cut can finish it.

Finish it with your own credentials, as the cut would have. Relabel the release
pull request first, so the next cut does not pick it up again:

```sh
PR=<release pull request number>
VERSION=<version>
TAG="vaultspec-rag-v$VERSION"
SHA=$(gh pr view "$PR" --repo "$REPO" --json mergeCommit --jq .mergeCommit.oid)

gh pr edit "$PR" --repo "$REPO" \
  --remove-label "autorelease: pending" --add-label "autorelease: tagged"
git fetch origin "$SHA"
git push origin "$SHA:refs/tags/$TAG"
git show "$SHA:CHANGELOG.md" \
  | awk -v h="## [$VERSION]" 'index($0, "## [") == 1 { p = index($0, h) == 1 } p' \
  > release-notes.md
gh release create "$TAG" --repo "$REPO" --verify-tag --draft \
  --title "vaultspec-rag: v$VERSION" --notes-file release-notes.md
gh workflow run publish.yml --repo "$REPO" --ref main --field tag="$TAG"
```

`--draft`, because the chain publishes the release itself as its last act. A
release created full here would be advertised with no assets on it.

`RAG Publish` starts only by dispatch, so the last command starts the normal
chain from that draft: release stage, then Binaries, then the package-index
stage that publishes it.

### Missing or incomplete binary archives

Read the failed matrix leg first. Restore the runner or correct the build
input, then rerun `RAG Binaries` for the same tag and its release commit:

```sh
gh workflow run binaries.yml --repo "$REPO" --ref "$TAG" --field tag="$TAG" \
  --field target_sha="$(git rev-parse "$TAG^{commit}")"
```

The dispatch ref must be the release tag. Binaries verifies that its workflow
commit, the remote tag and `target_sha` agree before any build job runs.

Do not remove a target from the matrix just to make a release green. If the
supported target set intentionally changes, update the product model, channel
tests, installation guidance, and this contract in the same reviewed change.

If the Release contains legacy raw target-qualified executables, the verifier
will continue to reject it after the new archives are attached. List the assets
first, then remove only the named raw files; do not delete the archives or
`SHA256SUMS`:

```sh
gh release delete-asset "$TAG" <raw-asset-name> --repo "$REPO" --yes
```

Rerun `RAG Binaries` after cleanup. An incomplete release needs no demotion: it
is still a draft, so it has never answered as `latest`. The repaired run's
verifier hands it on to the publication, which publishes it.

An already-published release cannot be repaired this way. Publication is the
last act of the chain, so a published release with a broken asset set means a
lane pushed something after it - fix forward with a new release rather than
retracting a version users may already hold.

### Missing or invalid monitor provenance

The draft verifier and package-index admission reject archives without the expected
GitHub/Sigstore attestation. Inspect the `Build: Release provenance (Linux)` job and
its exact tag/source identity. A release produced before this attestation workflow
needs a new release; do not replace the trust check with a live checksum.

For transient API failures, rerun the failed verifier job against the existing
attested draft bytes. Changed artifacts must pass native proof and be attested again
before they can be admitted.

### Missing Python artifacts or PyPI publication

If the Release exists but the wheel or source distribution is missing, rerun
`RAG Publish` for the same tag:

```sh
gh workflow run publish.yml --repo "$REPO" --ref main --field tag="$TAG"
```

If PyPI does not list the version, retry the upload. Files PyPI already holds
are skipped, so this is safe whether the release is still a draft or was
published and the upload failed on a later attempt:

```sh
gh workflow run publish.yml --repo "$REPO" --ref main --field tag="$TAG" \
  --field stage=package-index
```

That stage requires the release to carry its wheel, source distribution, and
`SHA256SUMS`, all four binary archives, and their authenticated build provenance.
If it refuses for a missing Python asset, the release stage has not
finished for this tag: rerun it as above. The stage publishes the release when
it completes, so it also repairs a chain that stopped after the binaries were
proven.

If no GitHub Release exists yet, run `RAG Publish` first and wait for its
`github-release` job to attach the packages to the draft before rerunning
`RAG Binaries`. The manual `RAG Publish` path verifies the tag and creates the
draft when one is missing; `RAG Binaries` then attaches the validated target
archives.

### Checksum drift or a lost merge

Rerun the lane that owns the missing entries. If both Python and binary
entries are suspect, rerun both workflows for the same tag. Their shared
per-tag concurrency group serializes the updates, and each run removes its own
old entries before merging the other workflow's current entries. Check the
final file with the `gh release view` asset list and by downloading
`SHA256SUMS`; do not hand-edit the remote asset.

### Channel pointers did not advance

Re-dispatch `RAG Channels` for the published tag. It reads the checksums back
from the release, regenerates and validates both pointers, and commits only
this product's two files:

```sh
gh workflow run channels.yml --repo "$REPO" --ref main --field tag="$TAG"
```

It refuses a draft. If it does, the release was never published: repair the
chain above instead, and the publication will dispatch this lane itself.

For a local repair, use a fresh checkout of `nevenincs/homebrew-tap` and the
Release checksum file:

```sh
CHANNEL_ROOT=../homebrew-tap
gh release download "$TAG" --repo "$REPO" --pattern SHA256SUMS --dir published
just release-channels "$TAG" "$CHANNEL_ROOT" published/SHA256SUMS
git -C "$CHANNEL_ROOT" add -- bucket/vaultspec-rag.json Formula/vaultspec-rag.rb
git -C "$CHANNEL_ROOT" diff --cached -- bucket Formula
```

Commit only those two paths when the staged diff is correct, then push
`main`. If generation refuses because the channel already names a newer
version, do not force it backward; investigate the release tag or wait for the
newer release's artifacts instead. If a push races another channel update,
fetch and rebase, then retry without force-pushing.

### The acquisition check never ran for a release

The publication dispatches it, and a rejected dispatch fails the publication run.
A downstream check failure reports in its own workflow and does not retract the public release.
Ask for it again; it downloads the published archives the way a user does, so it
needs the release to be published:

```sh
gh workflow run acquisition.yml --repo "$REPO" --ref main --field tag="$TAG" \
  --field target_sha="$(git rev-parse "$TAG^{commit}")"
```

The weekly scheduled run covers the latest release regardless.

After recovery, verify all three surfaces: the GitHub Release is published with
the complete archive set and merged checksums, the account channel files name
the same version and digests, and the
[installation guide](docs/installation.md) commands still describe the current
target contract.

## One-time PyPI trusted-publisher setup

The PyPI project is configured for trusted publishing. Repeat this only for a
fork or after rotating the publisher configuration:

1. Open <https://pypi.org/manage/account/publishing/>.
1. Add or manage the pending publisher with project `vaultspec-rag`, owner
   `nevenincs`, repository `vaultspec-rag`, workflow `publish.yml`, and
   environment `pypi`.
1. Confirm that `publish-pypi` keeps `environment: pypi` and
   `id-token: write`; no repository secret is required.
