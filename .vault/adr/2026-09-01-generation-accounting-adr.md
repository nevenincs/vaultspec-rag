---
tags:
  - '#adr'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:17ce81025a02ca07765ab780d9c5081f5a3faa8b4a4a6fef6e98c015e3f36167'
related:
  - "[[2026-09-01-generation-accounting-repair-research]]"
  - "[[2026-09-01-generation-accounting-repair-reference]]"
---

# `generation-accounting` adr: `repair generation ownership and convergence` | (**status:** `accepted`)

## Problem Statement

Generation cleanup, resumed-path retirement, and reindex request configuration must each
honor the ownership and durability boundary already chosen for indexing. The current branch
leaves those boundaries inconsistent, so an accepted repair is required before it can merge.
`2026-09-01-generation-accounting-repair-research` and
`2026-09-01-generation-accounting-repair-reference` ground the scope.

## Considerations

- `2026-07-25-non-destructive-index-publication-adr` remains the stable parent
  decision: the served identity changes only at publication, after a replacement is ready.
- `2026-07-25-index-resume-drift-race-adr` remains the stable parent decision: the
  drift owner performs storage mutation before advancing ledger state.
- `2026-09-01-generation-accounting-repair-research` requires the repair to make the
  lifecycle-derived target, storage-confirmed convergence, and supported runtime
  configuration agree.
- `2026-09-01-generation-accounting-repair-reference` identifies existing lifecycle,
  drift, ledger, and service-client seams; the repair must extend those canonical owners
  rather than introduce parallel paths.

## Considered options

- **Make the lifecycle-derived build target and the existing retirement ordering
  authoritative, and resolve the reindex timeout at request time.** Chosen. It repairs
  all three boundaries through their existing owners.
- **Allow cleanup to use an implicit collection or rebind the served store during a
  build.** Rejected: it violates the publication boundary.
- **Converge a retained upsert by changing only ledger state or relaxing finalization.**
  Rejected: it abandons the storage-and-ledger agreement required by the resume decision.
- **Add a separate reindex-only configuration transport or retain the import-time
  timeout.** Rejected: it duplicates configuration behavior or leaves the declared
  setting ineffective.

## Constraints

- This ADR refines neither parent ADR and does not supersede them; both are accepted,
  stable, and binding.
- Every clean-generation mutation must name the lifecycle-derived build target until
  publication; the served identity must remain untouched during that work.
- A retained upsert may leave the manifest only after its points are removed from the
  active target and that storage outcome is durably recorded.
- Reindex must honor the supported timeout at call time while retaining its documented
  default when no override is present.
- The change must preserve canonical ownership: no compatibility shims, re-exports,
  duplicate cleanup or configuration paths, or test-only production behavior.
- Strict type checking, formatting, and the full relevant test suite are required; guard
  tests must demonstrate the protected failure before restoration and exercise production
  storage and service paths.

## Implementation

Keep `CodeGenerationLifecycle` as the source of the active build collection and pass that
target explicitly into clean-generation drift and stale cleanup. Do not rebind the store's
served collection before publication.

Extend the existing drift and retirement owner so a resumed retained upsert that becomes
skipped or vanished first removes its points from the active build target, records the
confirmed deletion through the ledger's existing durability path, and only then removes the
manifest claim.

Resolve the reindex timeout through the service client's canonical request-time settings
path, using the declared default as fallback. Add focused, typed production-path tests for
target ownership, storage-before-ledger convergence, and runtime timeout resolution,
alongside the repository's formatting and strict-type gates.

## Rationale

The chosen repair makes the generation lifecycle the single authority for collection
ownership, preserves the parent publication contract, and gives the resume path the same
storage-before-ledger convergence already required for drift. Resolving the timeout at the
request boundary gives the declared setting one observable implementation rather than a
disconnected declaration. The repair follows the seams identified by
`2026-09-01-generation-accounting-repair-reference` and satisfies the decision drivers in
`2026-09-01-generation-accounting-repair-research` without altering either governing ADR.

## Consequences

Clean rebuilds retain the currently served generation until the existing publication
transition. Resumed paths converge storage and ledger instead of reaching finalization with
an unresolved retained claim. Operators' supported reindex-timeout configuration affects
subsequent requests.

The repair adds explicit target propagation and deletion accounting at the relevant seams,
so future collection mutations must carry target ownership deliberately. Its acceptance
burden includes real-path regression coverage plus green formatting and strict type
checking; any later shortcut around those owners is a correctness regression.
