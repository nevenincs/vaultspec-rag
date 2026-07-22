---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `large-index-resilience` audit: `p06 resumable pipeline`

## Scope

Reviewed phase P06 commits S22 through S25 against the accepted durable-ledger and bounded-pipeline contracts. The audit covered full, unscoped incremental, and scoped incremental storage mutation ordering; exact generation compatibility; segment replay; path and stale deletion evidence; metadata publication; clean-generation resume; cooperative control edges; and the phase boundary tests.

## Findings

### incremental-control-rollback | critical | Control delivery can delete storage-confirmed generation points

`CodebaseIndexer._commit_incremental_replacement` handles a control signal before finalization by deleting `published_ids - existing_ids`. Under the ledger-integrated pipeline, every newly published ID is already storage-confirmed and committed in the current generation, so deleting it makes the ledger lead storage and causes a compatible retry to skip missing points. The ID set also includes all carried manifest identities for incremental generations while `existing_ids` is scoped to attempted paths, so the same branch can delete unrelated retained paths. This violates the storage-before-ledger authority, one-unit replay, and control-safe-point contracts.

Resolution: resolved before phase closure. Checkpoint-backed incrementals now preserve storage-confirmed points when cooperative control arrives before finalization. `TestIncrementalPublicationRecovery.test_control_preserves_storage_confirmed_generation_points` verifies the edge with a production control token, SQLite generation ledger, and vector store. The final P06 boundary gate passed all 20 cases.

## Recommendations

- Carry this resolved invariant into P08 restart testing: cooperative unwind must preserve checkpointed storage and compatible replay must converge without missing points.
- Continue P07 finalization work without reintroducing rollback of storage-confirmed generation units.
