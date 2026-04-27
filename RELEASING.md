# Releasing vaultspec-rag

This document describes how vaultspec-rag is versioned, tagged, and published
to PyPI. Publishing is deliberately a two-step, human-in-the-loop process so
that no release ships without an explicit decision.

## Overview

- **Versioning** is managed by [release-please]. It watches conventional
  commits on `main` and opens a release PR (title `chore(main): release vaultspec-rag <version>`) that bumps `pyproject.toml`,
  `.release-please-manifest.json`, and `CHANGELOG.md`.
- **Tagging and GitHub release creation** happen automatically when the
  release PR is merged.
- **Building and publishing to PyPI** happens via the `Publish` workflow,
  which is `workflow_dispatch`-only. A human runs it after confirming the
  release looks correct.

The `Publish` workflow is **not** wired to `on: release`. GitHub's documented
limitation is that events produced by the default `GITHUB_TOKEN` (including
releases opened by release-please) do not trigger downstream workflows. Manual
dispatch avoids that trap and keeps publish authority explicit.

## One-time setup: PyPI trusted publisher

Before the very first publish, the PyPI project must have a trusted publisher
configured. Until then, `uv publish` will fail with an OIDC error.

Because the project does not yet exist on PyPI, use PyPI's *pending publisher*
flow:

1. Log in to <https://pypi.org/manage/account/publishing/>.
1. Under **Add a new pending publisher**, fill in:
   - PyPI Project Name: `vaultspec-rag`
   - Owner: `wgergely`
   - Repository name: `vaultspec-rag`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
1. Save. The first successful upload from this workflow will claim the
   project.

The `publish-pypi` job already declares `environment: pypi` and
`permissions: id-token: write`, so no repo-side changes are needed and no
secrets are stored anywhere.

## Cutting a release

1. **Merge feature work** to `main` using conventional commit messages
   (`feat:`, `fix:`, `perf:`, etc.). release-please reads these to compute
   the next version.
1. **Review the release PR** that release-please opens. Check the proposed
   version bump and the generated changelog. Merge when happy.
1. Merging the release PR creates the git tag (`vaultspec-rag-v<version>`)
   and a matching GitHub Release.

## Publishing to PyPI

1. Open <https://github.com/wgergely/vaultspec-rag/actions/workflows/publish.yml>.

1. Click **Run workflow**. Provide the tag (for example
   `vaultspec-rag-v0.2.0a0`) and dispatch.

1. The workflow builds the wheel and sdist, runs the smoke test against both
   artifacts, and then uploads to PyPI via trusted publishing.

1. Verify the upload:

   ```sh
   curl -s https://pypi.org/pypi/vaultspec-rag/json | jq .info.version
   uvx --prerelease=allow vaultspec-rag --version
   ```

## Troubleshooting

- **`uv publish` fails with an OIDC error** — the PyPI trusted publisher is
  missing or misconfigured. Recheck the workflow name (`publish.yml`) and
  environment (`pypi`).
- **The workflow cannot be dispatched** — it must live on the default branch
  for GitHub to list it under **Run workflow**. If you added it on a feature
  branch, it will only be dispatchable from that branch.
- **Version in `pyproject.toml` does not match the tag** — release-please
  overwrites `pyproject.toml`, `.release-please-manifest.json`, and
  `CHANGELOG.md` in its release PR. If these drift (for example from a manual
  version bump), sync them by updating `.release-please-manifest.json` to
  match `pyproject.toml` and letting release-please reconcile on the next
  merge.

[release-please]: https://github.com/googleapis/release-please
