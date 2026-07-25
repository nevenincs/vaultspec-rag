---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S02'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Sweep the indexer for duplicate behaviour with vaultspec-rag semantic search before any extraction, recording each duplicate pair so extraction collapses it rather than carrying both across the seam

## Scope

- `src/vaultspec_rag/indexer/`

## Description

- Rebuild the code index so semantic search is answering from current content.
- Search by behaviour across the duplication-prone clusters: digest
  computation, drift detection, point-id collection, and stored-identity
  construction.
- Read every candidate rather than judging on rank, and record the rejections.

## Outcome

The module carries substantial duplication. Eight duplicate pairs and three
bodies of unreachable code were identified, several already drifted apart.

**A first pass of this Step reached the opposite conclusion and was wrong.** It
searched three behaviour clusters, read a handful of top-ranked candidates,
found them to be distinct concerns, and concluded there was nothing to collapse.
That conclusion is retracted. The error was one of depth, not method: ranked
search results were treated as the candidate set rather than as an entry point,
and a negative was declared from a sample. The finding is recorded here because
a refactor briefed on "no duplicates to collapse" would have carried every one
of these across the seam.

True duplicates:

- Two byte-equivalent loops hash a set of files into a path-to-digest mapping,
  each with the same progress phases, the same blake2b call, the same
  skip-on-`OSError` warning, and the same run-control cadence. Even the
  caller-side prune of unhashable paths is repeated.
- The index-run lifecycle wrapper - accept preflight, take the writer lock,
  stamp the activity clock, emit started/failed/completed events, stamp again -
  exists in four copies across the codebase and vault indexers, differing only
  in a mode string and the delegate. **This duplication has already produced a
  live divergence**: the document indexer takes the writer lock but emits no
  index events and never stamps the activity clock at all. Verified directly -
  the stamping call appears four times in the codebase indexer and four times in
  the vault indexer, and zero times in the document indexer. It is the copy that
  never received the fix.
- The code and document run checkpoints repeat method for method. A prior
  decision recorded in the shared checkpoint module deliberately left one-line
  properties duplicated, on the stated reasoning that a duplicated one-line
  property reads wrong once whereas a duplicated decision is the copy that never
  gets the fix. By that same criterion the generation-publish phase machine and
  the run-signature assembly are duplicated decisions and fall outside the
  documented exemption.
- Ledger-state validation before publishing a manifest is repeated in the code
  and document metadata publishers, and has already drifted: the two raise
  different wordings for the same ordering violation.
- Stat-failure classification is decided twice within the same module, with the
  consequence that every admitted file is stat-ed twice per scan.

Near duplicates, where the difference is real:

- Two writers target the same code sidecar file under different durability
  regimes. The one living on the class under refactor omits the generation id
  and does not fsync; the other writes all reserved keys durably.
- The code and document chunk-byte estimators share a character-identical
  validation preamble and arithmetic. The tell that one is a copy of the other
  is that the document estimator sums into a constant named for code.
- Rollback of an attempt's introduced point ids exists twice, one honouring
  protected ids and one not.

Unreachable code that must not be carried across the seam: two future-submission
helpers with no callers at all, and a second whole collect-into-a-list chunking
pipeline kept alive only by its own tests. The parity test that proves
parallel and serial chunk identity exercises the path production no longer uses,
so that coverage is currently asserting nothing about the live pipeline.

One near-duplicate is deliberately retained. A helper deriving a chunk's stored
point id and expected content mirrors the store's upsert identity, and its
docstring owns that obligation. Its failure mode is safe by construction - drift
causes a missed reuse hit, never adoption of a wrong vector, since adoption
still requires byte-for-byte content equality - and collapsing it would couple
reuse verification to the write path for no gain.

Separately, the drift lifecycle is already split across two collaborators, but
the ordering between them - drop the published points, then remove the units
that claimed them - lives in the calling class rather than in either component.
That is the entanglement the governing decision named: an invariant with no
owner.

## Notes

This Step was executed twice. A direct sweep ran first, when the dispatched
executor appeared to have finished without reporting, and reached a false
negative. The executor's report then arrived, carrying the findings above with
per-site locators. The three highest-consequence claims were verified
independently before being accepted here - the unreachable helpers resolve to
their own definitions and nothing else, the activity-clock stamp is absent from
the document indexer while appearing four times in each sibling, and the
citation gate does return clean on a dated stem in a module docstring.

The false negative is instructive and is left recorded rather than quietly
overwritten. Ranked search results were treated as the candidate set instead of
as an entry point into reading, so three clusters were sampled and a negative
was declared across the module. Semantic search locates; it does not enumerate.
A duplication sweep is not finished when the top hits stop looking similar.

Two findings outside this plan's scope were filed rather than folded in: the
citation gate's blind spot, and the document indexer's missing activity-clock
stamps.

The code index proved unstable during the Step and the instability is worth
recording, because it silently degrades exactly the tool the sweep depends on.
Semantic search initially returned only one file for every query, including
queries whose subject plainly lives elsewhere - a probe for the reranker, which
is in the search package, returned ledger hits. A clean rebuild processing 422
files restored correct breadth, after which the same probe resolved to the
searcher and a broad query returned seven distinct files.

The cause was not established. No code index job ran between the earlier
successful rebuild and the observed collapse, so an incremental update is not an
obvious culprit; a vault index job was active during the collapsed probes, which
suggests but does not demonstrate interference. This is recorded as an
observation, not a diagnosis, and deliberately not filed as a defect until the
mechanism is reproduced. The practical consequence stands regardless: a search
against a degraded index answers rather than errors, so semantic grounding can
be wrong without announcing it.
