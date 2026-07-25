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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-resume-drift-race with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-25-index-resume-drift-race-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Sweep the indexer for duplicate behaviour with vaultspec-rag semantic search before any extraction, recording each duplicate pair so extraction collapses it rather than carrying both across the seam and ## Scope

- `src/vaultspec_rag/indexer/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

The sweep found no true duplicate to collapse in the clusters searched, and that
is the finding rather than a null result. It changes what the extractions are
for: the module is large because one class holds many responsibilities, not
because behaviour was copy-pasted, so the seams should separate concerns and must
not go looking for redundancy to remove.

Candidates read and rejected:

- Digest computation is three distinct concerns wearing similar words. One site
  hashes the paths a run must re-examine, another asserts mid-stream that a
  document's content did not change under the reader, and a third decides whether
  embedding metadata needs rebuilding. Same vocabulary, different jobs.
- Drift detection and drift remedy are already separate and correctly layered.
  The predicate that reports which resumed paths moved lives on the checkpoint
  and delegates its evidence lookup to the ledger; the supersede that re-opens
  such a path lives on the ledger. Neither reimplements the other.

One genuine near-duplicate, deliberately retained: a helper that derives a
chunk's stored point id and expected content mirrors the store's upsert identity
and payload construction. Its own docstring states the obligation to track the
store exactly. It should NOT be collapsed during extraction. The mirror exists so
reuse verification can predict what the store would have written without going
through the store, and its failure mode is deliberately safe - drift between the
two causes a missed reuse hit and a hit-rate regression, never adoption of a
wrong vector, because adoption still requires the stored content to match
byte-for-byte. Collapsing it would couple reuse verification to the write path
for no gain.

The most useful discovery for the seam is not a duplicate at all. The drift
lifecycle is already split across two collaborators, but the ORDERING between
them - drop the published points, then remove the units that claimed them - lives
in the calling class rather than in either component. That is precisely the
entanglement the governing decision named: not redundant code, but an invariant
with no owner. It confirms the extraction target rather than adding to it.

## Notes

The dispatched agent completed without delivering a report, so this sweep was
re-run directly. The searches and the reading behind every verdict above are
first-hand.

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
