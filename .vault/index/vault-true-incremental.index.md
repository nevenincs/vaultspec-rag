---
generated: true
tags:
  - '#index'
  - '#vault-true-incremental'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - '[[2026-07-24-vault-true-incremental-adr]]'
  - '[[2026-07-25-vault-true-incremental-P01-S01]]'
  - '[[2026-07-25-vault-true-incremental-P01-S02]]'
  - '[[2026-07-25-vault-true-incremental-P01-S03]]'
  - '[[2026-07-25-vault-true-incremental-P02-S04]]'
  - '[[2026-07-25-vault-true-incremental-P02-S05]]'
  - '[[2026-07-25-vault-true-incremental-P02-S06]]'
  - '[[2026-07-25-vault-true-incremental-P02-S07]]'
  - '[[2026-07-25-vault-true-incremental-P02-S08]]'
  - '[[2026-07-25-vault-true-incremental-P02-S09]]'
  - '[[2026-07-25-vault-true-incremental-P03-S10]]'
  - '[[2026-07-25-vault-true-incremental-P03-S11]]'
  - '[[2026-07-25-vault-true-incremental-P04-S12]]'
  - '[[2026-07-25-vault-true-incremental-P04-S13]]'
  - '[[2026-07-25-vault-true-incremental-P04-S14]]'
  - '[[2026-07-25-vault-true-incremental-P04-S15]]'
  - '[[2026-07-25-vault-true-incremental-plan]]'
  - '[[2026-07-27-vault-true-incremental-grounding-research]]'
---

# `vault-true-incremental` feature index

Auto-generated index of all documents tagged with `#vault-true-incremental`.

## Documents

### adr

- `2026-07-24-vault-true-incremental-adr` - `vault-true-incremental` adr: `frontmatter-volatility-agnostic vault change detection` | (**status:** `accepted`)

### exec

- `2026-07-25-vault-true-incremental-P01-S01` - Name the indexed-frontmatter subset beside the payload builders that consume it, so the fingerprint and the payload cannot drift apart silently
- `2026-07-25-vault-true-incremental-P01-S02` - Canonicalise the subset before digesting it, excluding the volatile modified stamp by construction and absorbing pure whitespace and quoting churn
- `2026-07-25-vault-true-incremental-P01-S03` - Cover the subset definition with a test that fails when a payload field is added without entering the subset digest
- `2026-07-25-vault-true-incremental-P02-S04` - Replace the raw whole-file digest with a body digest plus a subset digest, normalising the body the way the chunker already normalises it
- `2026-07-25-vault-true-incremental-P02-S05` - Persist both digests in the sidecar under the existing meta-versioning convention so an old sidecar is recognised rather than misread
- `2026-07-25-vault-true-incremental-P02-S06` - Classify a body-digest delta as re-chunk and re-embed, preserving the current indexing path for that branch unchanged
- `2026-07-25-vault-true-incremental-P02-S07` - Route a subset-only delta to a payload-only upsert that rebuilds the document's payloads and leaves its vectors untouched
- `2026-07-25-vault-true-incremental-P02-S08` - Classify a volatile-stamp-only change as unchanged so it reaches neither the encoder nor the store
- `2026-07-25-vault-true-incremental-P02-S09` - Hold the first run under the new scheme to a re-classification rather than a re-embed, reusing donor vectors from the root's own collection wherever the body digest matches
- `2026-07-25-vault-true-incremental-P03-S10` - Run the split classifier over the full corpus on the unscoped escalation so convergence is reached by digest comparison and payload updates rather than a blanket re-embed
- `2026-07-25-vault-true-incremental-P03-S11` - Leave the durable convergence-pending bit and the escalation trigger semantics unchanged, confirming only the work the escalated pass performs is narrowed
- `2026-07-25-vault-true-incremental-P04-S12` - Prove the stamp-only guard bidirectionally: assert zero encodes on a modified-stamp bump, weaken the fingerprint back to a raw-file digest, watch the encode assertion fail, restore, watch it pass
- `2026-07-25-vault-true-incremental-P04-S13` - Prove the metadata-only guard bidirectionally: assert a tags-only edit updates payloads with zero encodes, route metadata changes into the re-embed branch, watch it fail, restore, watch it pass
- `2026-07-25-vault-true-incremental-P04-S14` - Prove the body guard bidirectionally: assert a body edit re-embeds, drop the body digest from the fingerprint, watch it fail, restore, watch it pass
- `2026-07-25-vault-true-incremental-P04-S15` - Measure an incremental vault run over a stamp-churned corpus against the recorded pre-change baseline and record both figures

### plan

- `2026-07-25-vault-true-incremental-plan` - `vault-true-incremental` plan

### research

- `2026-07-27-vault-true-incremental-grounding-research` - `vault-true-incremental` research: `Grounding`
