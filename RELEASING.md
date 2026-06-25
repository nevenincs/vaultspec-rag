# Releasing vaultspec-rag

How vaultspec-rag is versioned, tagged, and published to PyPI. The pipeline
is fully automated once you merge the release PR; this document explains
what happens at each step and how to recover when something stalls.

## Overview

Three GitHub Actions workflows cooperate to ship a release:

- **release-please.yml** reads conventional commits on `main`, opens a
  release PR (titled `chore(main): release vaultspec-rag <version>`), and
  keeps `pyproject.toml`, `.release-please-manifest.json`, `CHANGELOG.md`,
  and `uv.lock` in sync on that PR.
- When you merge the release PR, release-please creates the git tag
  (`vaultspec-rag-v<version>`) and a matching GitHub Release.
- **publish.yml** runs automatically when either trigger fires: the new
  tag pushed to `main`, or release-please dispatching the workflow after
  it creates the release. The workflow builds the wheel and sdist, smoke
  tests both artefacts, and uploads to PyPI via trusted publishing.

The only human step is merging the release PR. Manual dispatch of the
Publish workflow exists as a recovery option (see Troubleshooting).

## CI gates

The release PR cannot be merged until these required checks pass:

- **Workflow Lint** - actionlint over every workflow file.
- **Lint, Type, Config, Link, and Markdown Checks** - ruff, ty, taplo,
  lychee, mdformat.
- **Tests** - the unit suite.
- **Vault Audit** - `vaultspec-core vault check all`.
- **Dependency Audit** - `uv audit` for known CVEs.

The GPU integration suite (`gpu-integration.yml`) runs on a self-hosted
runner and is informational; it does not gate the merge.

## One-time setup: PyPI trusted publisher

Done once for `vaultspec-rag`. The PyPI project is already claimed; no
action needed for normal releases. Repeat the steps below only if you
fork the project or rotate the publisher configuration.

1. Sign in to <https://pypi.org/manage/account/publishing/>.
1. Under **Add a new pending publisher** (or **Manage** for an existing
   project), enter:
   - PyPI Project Name: `vaultspec-rag`
   - Owner: `nevenincs`
   - Repository name: `vaultspec-rag`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
1. Save. The next upload from this workflow will use the publisher.

The `publish-pypi` job already declares `environment: pypi` and
`permissions: id-token: write`. No repo secrets are stored.

## Cutting a release

1. **Merge feature work** to `main` using conventional commit messages
   (`feat:`, `fix:`, `perf:`). release-please uses these to compute the
   next version and the changelog.

1. **Wait for the release PR** that release-please opens. The PR body
   shows the proposed version and the generated changelog. release-please
   also pushes a fresh `uv lock` to the PR branch so the lockfile stays
   aligned with the bump.

1. **Review and merge** the release PR. Merging triggers three automatic
   actions: the git tag is created, a GitHub Release is published, and
   the Publish workflow starts.

1. **Verify the upload** once the Publish workflow completes:

   ```sh
   curl -s https://pypi.org/pypi/vaultspec-rag/json | jq .info.version
   uvx --prerelease=allow vaultspec-rag --version
   ```

## Troubleshooting

- **Publish workflow did not run.** Confirm the release-please job
  finished cleanly on `main` and that the tag exists on origin. If both
  are present, dispatch Publish manually:

  1. Open
     <https://github.com/nevenincs/vaultspec-rag/actions/workflows/publish.yml>.
  1. Click **Run workflow**, supply the tag (for example
     `vaultspec-rag-v0.2.9`), and run.

- **`uv publish` fails with an OIDC error.** The PyPI trusted publisher
  is missing or misconfigured. Recheck the workflow name (`publish.yml`)
  and environment (`pypi`) under the project's publishing settings.

- **The workflow cannot be dispatched from the Actions UI.** It must
  live on the default branch for GitHub to list it. If you added it on
  a feature branch, it is only dispatchable from that branch.

- **Version in `pyproject.toml` does not match the latest tag.**
  release-please rewrites `pyproject.toml`,
  `.release-please-manifest.json`, and `CHANGELOG.md` on every release
  PR. If they drift after a manual bump, update
  `.release-please-manifest.json` to match `pyproject.toml`, push the
  fix, and let release-please reconcile on the next merge.
