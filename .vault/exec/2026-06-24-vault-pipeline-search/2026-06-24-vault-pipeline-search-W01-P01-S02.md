---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S02'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Author the intent-tagged labeled query set with hand-graded gold judgments

## Scope

- `src/vaultspec_rag/tests/quality/intent_queries.toml`

## Description

- Authored `intent_queries.toml`: 11 queries spanning orientation (6), debugging (2), and
  implementation (3), each with a declared intent and rubric-derived gold judgments.
- Anchored every gold judgment on a real, verified vault doc_id (path without extension);
  21 total judgments across ADR, research, plan, and exec documents.
- Included the canonical regression (orientation "decision on gpu lock scope" grades the
  accepted ADR 3, the implementing exec record 1) and a status-derank trap (a superseded
  mcp-route ADR graded 1 so it must not lead its most-topical query).
- Documented the schema and the mechanical-from-rubric authoring rule in file comments.

## Outcome

The query set is committed data the S05 harness will consume. Validated: TOML parses, all
21 gold doc_ids resolve to existing `.vault/` files, and every grade is in [0, 3].

## Notes

Targets the real project vault rather than the synthetic corpus, so the gating harness
exercises the actual corpus the live failure occurs in; the S03 synthetic enrichment is a
deterministic supplement. No blockers.
