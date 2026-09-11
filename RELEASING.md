# Releasing vaultspec-rag

This is the maintainer runbook for publishing the Python package, standalone
binary bundles, and package-manager pointers. The release pipeline is
automated after the release PR is merged; this document records the artifact
contract, the gates that protect `latest`, and the recovery paths when a lane
stalls.

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

RAG is CUDA-only. macOS is not a supported runtime, so no macOS binary or
Homebrew formula branch is published. Linux archives require the glibc floor
recorded in their `manifest.json`; the Homebrew formula repeats the applicable
caveat.

Each archive contains exactly these release members:

- `vaultspec-rag` (or `vaultspec-rag.exe` on Windows)
- `vaultspec-search-mcp` (or `vaultspec-search-mcp.exe` on Windows)
- `LICENSE`
- `README.txt`
- `manifest.json`

The target-qualified executable names used in the build directory are staging
names. They are not public download names and must never be uploaded to a
release. The archive-local manifest describes the product, version, target,
runtime, requirements, platform floor, and SHA-256 of each member. It does not
contain the enclosing archive's digest; that digest belongs in the release's
top-level `SHA256SUMS` file.

The user-facing installation and verification commands are in
[the installation guide](docs/installation.md#install-without-python).

## How the release runs

The three workflows have deliberately separate responsibilities:

1. `release-please.yml` opens and updates the release PR from conventional
   commits. When the PR is merged, release-please creates the
   `vaultspec-rag-v<version>` tag and GitHub Release.
1. The same workflow immediately marks the new Release as a prerelease and
   explicitly dispatches both `Publish` and `Binaries` with the exact tag. Do
   not remove the binary dispatch or rely on the tag-push trigger: a tag created
   with the default `GITHUB_TOKEN` does not recursively start workflows.
1. `Publish` builds the wheel and source distribution, smoke-tests both across
   the supported Python versions, publishes to PyPI through the trusted
   publisher, and attaches the Python artifacts to the GitHub Release.
1. `Binaries` builds the exact release wheel once, passes that wheel to every
   target leg, finalizes the target-qualified executables, and creates and
   verifies one archive per target. Its release job aggregates the archive
   checksums, passes the complete-target gate, attaches only the public
   archives and merged checksum file, then generates and validates the Scoop
   manifest and Homebrew formula in the account channel repository.
1. `Binaries` always runs `verify-release-assets` after its release job. The
   verifier derives the expected targets from the matrix, checks the remote
   Release for every correctly named archive, rejects raw executables, and
   requires the binary release job to have succeeded. A failed or incomplete
   set is demoted to a prerelease. A repaired normal release is promoted only
   after the complete set passes; release tags containing `rc`, `alpha`,
   `beta`, or `dev` remain prereleases by design.

`Publish` and `Binaries` share the concurrency group
`release-artifacts-<tag>` with `cancel-in-progress: false`. This serializes
updates to the one remote `SHA256SUMS` asset while allowing a failed lane to be
rerun for the same tag.

## Cutting a release

1. Merge feature work to `main` with conventional commit messages such as
   `feat:`, `fix:`, or `perf:`.
1. Review the release PR opened by release-please. Confirm the proposed
   version, changelog, `pyproject.toml`, `.release-please-manifest.json`, and
   `uv.lock` are coherent, and wait for the required checks.
1. Merge the release PR. Do not manually create a second tag or Release for
   the same version.
1. Watch both `Publish` and `Binaries`. The release should remain a prerelease
   until the binary verifier has accepted all three target archives.
1. Confirm the GitHub Release asset list and the PyPI version. A normal,
   complete release should expose three binary archives, one wheel, one source
   distribution, and `SHA256SUMS`.

The required release checks include workflow lint, static analysis, tests,
documentation checks, the Vault audit, and the dependency audit. The GPU
integration suite is informational; the binary workflow's target matrix and
runner preflight are the release gates for standalone artifacts.

## Reproducing the binary artifacts locally

Run each target on an environment that can serve the corresponding matrix
leg. Start with an empty `dist`, `dist-bin`, and `dist-bundles` output set so
the exact-wheel and exact-target checks cannot select stale files.

```sh
TAG=vaultspec-rag-v<version>

uv python install 3.13
uv build --wheel --out-dir dist

just release-binaries "$TAG" x86_64-pc-windows-msvc dist-bin dist
just release-bundle   "$TAG" x86_64-pc-windows-msvc dist-bin dist-bundles

just release-binaries "$TAG" x86_64-unknown-linux-gnu dist-bin dist
just release-bundle   "$TAG" x86_64-unknown-linux-gnu dist-bin dist-bundles

just release-binaries "$TAG" aarch64-unknown-linux-gnu dist-bin dist
just release-bundle   "$TAG" aarch64-unknown-linux-gnu dist-bin dist-bundles

just release-checksums dist-bundles dist-bundles/SHA256SUMS
(cd dist-bundles && sha256sum -c SHA256SUMS)
```

`just release-binaries` requires exactly one wheel in `dist` and builds from
that wheel rather than resolving a published package. `just release-bundle`
consumes the finalized target-qualified files, verifies the archive before
writing its `.sha256` sidecar, and gives the extracted commands their stable
names. `just release-checksums` creates an archive-only local view. The GitHub
workflow merges that view with the wheel and source-distribution entries
already attached to the Release before uploading `SHA256SUMS`.

Never use `dist-bin` as a release upload directory. It is a private staging
directory; `dist-bundles` is the public archive boundary.

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
GitHub. This second check matters when a matrix leg fails before the release
job runs, or when an old release already contains an incomplete asset set. It
also ensures that the binary release job itself succeeded before stable/latest
promotion.

Both artifact workflows reconcile `SHA256SUMS` in the same way:

1. Generate the entries for the artifacts produced by the current workflow.
1. Download the existing `SHA256SUMS` from the same tag when it exists.
1. Remove inherited entries for the filenames being replaced.
1. Append the current entries and sort by filename.
1. Upload the merged file with `--clobber`.

This makes reruns idempotent and preserves the other workflow's completed
entries. Do not replace the remote file with a binary-only checksum list, edit
it by hand, or attach raw staging files to repair a release.

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

The release job runs the equivalent of:

```sh
just release-channels "$TAG" channels dist-bundles/SHA256SUMS
```

Here `channels` is a checkout of `nevenincs/homebrew-tap`. The command
generates and validates both pointers from the same aggregate checksum file.
The generator refuses a backward version bump, refuses missing digests, and
omits unsupported or unavailable Homebrew targets rather than inventing a
pointer. A missing supported build is reported as a warning; the complete
target gate must still pass before a normal release can become stable.

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
available Linux target; the Scoop manifest contains the single Windows bundle
URL and digest.

## Recovery

Set the repository and exact tag before inspecting or rerunning anything:

```sh
REPO=nevenincs/vaultspec-rag
TAG=vaultspec-rag-v<version>

gh release view "$TAG" --repo "$REPO" --json isPrerelease,assets \
  --jq '{isPrerelease, assets: [.assets[].name]}'
gh run list --repo "$REPO" --workflow Binaries --limit 20
gh run list --repo "$REPO" --workflow Publish --limit 20
```

### Missing or incomplete binary archives

Read the failed matrix leg and runner-preflight result first. Restore the
runner or correct the build input, then rerun `Binaries` for the same tag:

```sh
gh workflow run Binaries --repo "$REPO" --ref main --field tag="$TAG"
```

Do not remove a target from the matrix just to make a release green. If the
supported target set intentionally changes, update the product model, channel
tests, installation guidance, and this contract in the same reviewed change.

If the remote Release contains legacy raw target-qualified executables, the
verifier will continue to reject it after the new archives are attached. List
the assets first, then remove only the named raw files; do not delete the
archives or `SHA256SUMS`:

```sh
gh release delete-asset "$TAG" <raw-asset-name> --repo "$REPO" --yes
```

Rerun `Binaries` after cleanup. If a normal release is currently stable while
it is incomplete, demote it immediately so it cannot answer as `latest`:

```sh
gh release edit "$TAG" --repo "$REPO" --prerelease
```

The successful binary verifier will promote a repaired normal release again.

### Missing Python artifacts or PyPI publication

If the Release exists but the wheel, source distribution, or PyPI publication
is missing, rerun `Publish` for the same tag:

```sh
gh workflow run Publish --repo "$REPO" --ref main --field tag="$TAG"
```

If no GitHub Release exists yet, run `Publish` first and wait for its
`github-release` job to create the Release before rerunning `Binaries`. The
manual `Publish` path verifies the tag and can create the missing Release;
`Binaries` then attaches the validated target archives.

### Checksum drift or a lost merge

Rerun the lane that owns the missing entries. If both Python and binary
entries are suspect, rerun both workflows for the same tag. Their shared
per-tag concurrency group serializes the updates, and each run removes its own
old entries before merging the other workflow's current entries. Check the
final file with the `gh release view` asset list and by downloading
`SHA256SUMS`; do not hand-edit the remote asset.

### Channel pointers did not advance

Rerun `Binaries` after the Release has a complete archive set. Its release job
regenerates and validates the account pointers before committing them. For a
local repair, use a fresh checkout of `nevenincs/homebrew-tap` and the Release
checksum file:

```sh
CHANNEL_ROOT=../homebrew-tap
just release-channels "$TAG" "$CHANNEL_ROOT" dist-bundles/SHA256SUMS
git -C "$CHANNEL_ROOT" add -- bucket/vaultspec-rag.json Formula/vaultspec-rag.rb
git -C "$CHANNEL_ROOT" diff --cached -- bucket Formula
```

Commit only those two paths when the staged diff is correct, then push
`main`. If generation refuses because the channel already names a newer
version, do not force it backward; investigate the release tag or wait for the
newer release's artifacts instead. If a push races another channel update,
fetch and rebase, then retry without force-pushing.

After recovery, verify all three surfaces: the GitHub Release has the complete
archive set and merged checksums, the account channel files name the same
version and digests, and the [installation guide](docs/installation.md)
commands still describe the current target contract.

## One-time PyPI trusted-publisher setup

The PyPI project is configured for trusted publishing. Repeat this only for a
fork or after rotating the publisher configuration:

1. Open <https://pypi.org/manage/account/publishing/>.
1. Add or manage the pending publisher with project `vaultspec-rag`, owner
   `nevenincs`, repository `vaultspec-rag`, workflow `publish.yml`, and
   environment `pypi`.
1. Confirm that `publish-pypi` keeps `environment: pypi` and
   `id-token: write`; no repository secret is required.
