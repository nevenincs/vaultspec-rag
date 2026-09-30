---
tags:
  - '#reference'
  - '#release-standard'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:d5e133018e8714ca6d0daf69e1531052ed0566a9accafd90ee3a35dc5f438830'
related: []
---

# `release-standard` reference: `Draft-first release order as vaultspec-core implements it`

How vaultspec-core creates a release unpublished and publishes it last, and
what RAG's chain did instead. Read from the two repositories' workflow files
and guard suites; core locators are prefixed with the product name, RAG
locators are plain.

## Summary

**Core creates the release as a draft and forces its tag.** The package config
carries both flags together: `vaultspec-core release-please-config.json:8`
(`draft`) and `:9` (`force-tag-creation`). The second is required by the first -
GitHub creates no git tag for a draft release, and every lane checks out the
tag for its source. The cut then proves the forced tag points at the commit the
gate proved and dispatches the binary lane, editing no release flag:
`vaultspec-core .github/workflows/release-please.yml:288` and `:320`.

**The completeness gate judges the draft and edits nothing.** Core's
`verify-release-assets` derives its expected targets from the build matrix and
fails an incomplete set without demoting anything, because the release is
unpublished:
`vaultspec-core .github/workflows/binaries.yml:1273` and `:1321`. On success -
and only there - it dispatches the publication lane, so the irreversible index
upload never races a build that could still fail:
`vaultspec-core .github/workflows/binaries.yml:1379`.

**The publication lane publishes the release last.** It creates the draft
idempotently for a repair dispatch with
`gh release create ... --draft --verify-tag --generate-notes || true`
(`vaultspec-core .github/workflows/publish.yml:252`), uploads to the index,
verifies what it attached, and flips the draft as its final act:
`vaultspec-core .github/workflows/publish.yml:361`. The channel pointers and
the acquisition check are dispatched after that flip, at `:382` and `:414`, the
first because a package-manager pointer addresses release download URLs and the
second because it downloads unauthenticated and cannot see a draft.

**The channel lane holds the deploy key and nothing else.** It is dispatch-only,
checks out the account distribution repository with the deploy key
(`vaultspec-core .github/workflows/channels.yml:75`), and refuses a draft
rather than trusting its caller (`:108`). The separation exists because the
upload job carries `id-token: write`, which is not scoped to one audience.

**Four guards hold that order.** In
`vaultspec-core dev/guards/test_automation_contracts.py`: the draft and forced
tag at `:1528`, the publication dispatched only from the proven gate at `:1552`,
the flip last and only once at `:1581`, and no lane editing a release into
shape at `:1685`.

**What RAG did instead, before this feature.** release-please created a full
release and the cut immediately marked it a prerelease; the binary lane demoted
an incomplete release, an `acquisition` job gated a `promote` job that removed
the flag, and that job dispatched the package index. The Scoop and Homebrew
pointers were generated and pushed from the binary lane's release job, while
the hold was still on, with the deploy key in the same job. RAG's chain also
has a shape core's does not: the publication workflow takes a `stage` input
(`release` or `package-index`) and its release stage attaches the distribution
before the binaries lane runs, so the binaries carry the release's own wheel
rather than a second build of it.

**Where RAG now implements each of core's steps.** The forced tag proof at
`.github/workflows/release-please.yml:314` and the dispatch at `:334`; the
idempotent draft creation at `.github/workflows/publish.yml:97`; the
completeness gate at `.github/workflows/binaries.yml:445` and `:480`, with the
handoff to the package-index stage at `:612`; the distribution precondition at
`.github/workflows/publish.yml:352` and the index upload at `:405`; the
publication job at `:423`, its flip at `:442`, and the channel and acquisition
dispatches at `:468` and `:492`; the channel lane's deploy key at
`.github/workflows/channels.yml:79` and its draft refusal at `:98`.

**One deliberate difference.** Core's gate hands the draft on with
`--ref "${TAG}"` so the publication workflow is read from the released tree for
trusted publishing. RAG dispatches with `--ref main`, matching every other hop
in its chain, which resolves the workflow from current policy while each job
checks out the release commit for its source. RAG's trusted publisher is
configured for `publish.yml` in the `pypi` environment either way.
