---
tags:
  - '#plan'
  - '#vault-true-incremental'
date: '2026-07-25'
modified: '2026-07-27'
tier: L2
related:
  - '[[2026-07-24-vault-true-incremental-adr]]'
  - '[[2026-07-24-index-throughput-adr]]'
  - '[[2026-07-24-index-throughput-research]]'
  - '[[2026-07-24-worktree-index-reuse-adr]]'
---

# `vault-true-incremental` plan

## Description

Executes `2026-07-24-vault-true-incremental-adr`, which decides that what
invalidates a vector is a storage and index contract rather than an ad hoc
patch. Vault change detection currently digests raw file bytes: the whole file,
frontmatter included, is blake2b-ed at
`src/vaultspec_rag/indexer/_vault_indexer.py:642-662` and again when the sidecar
is written at `src/vaultspec_rag/indexer/_vault_indexer.py:971-984`, and the
result drives classification at
`src/vaultspec_rag/indexer/_vault_indexer.py:537-550` and `833-845`. Because the
CLI refreshes a `modified:` stamp on every mutating vault verb, a byte-identical
body flips the digest and the document is re-embedded on the GPU for no semantic
change. `2026-07-24-index-throughput-research` measured the consequence:
incremental vault jobs spending 796 to 1,516 seconds to commit between zero and
six chunks.

`P01` establishes the indexed-frontmatter subset as a named contract beside the
payload builders that consume it (`src/vaultspec_rag/_store_models.py:322-359`),
which is the ADR's constraint that the fingerprint and the payload can never
drift apart silently. `P02` splits the fingerprint and routes each delta class to
its cheapest correct outcome. `P03` narrows the watcher's unscoped escalation -
still reached through `src/vaultspec_rag/watcher_retry.py:255` and
`src/vaultspec_rag/watcher.py:1648` - from a blanket re-embed to a convergence
pass over the same classifier. `P04` proves each classification branch can fail.

`2026-07-24-worktree-index-reuse-adr` supplies the donor-vector reuse that
covers the one-time migration in `P02.S09`; the ADR is explicit that reuse must
not be used to excuse a wrong classification, so it is a migration aid here and
nothing more. Sequenced after `2026-07-24-index-throughput-adr`'s plan lands,
which shares these files.

## Steps

### Phase `P01` - Define the indexed-frontmatter subset

The subset that enters point payloads becomes a named contract living beside the payload builders that consume it, so a field added to a payload cannot silently escape the fingerprint.

- [ ] `P01.S01` - Name the indexed-frontmatter subset beside the payload builders that consume it, so the fingerprint and the payload cannot drift apart silently; `src/vaultspec_rag/_store_models.py`.
- [ ] `P01.S02` - Canonicalise the subset before digesting it, excluding the volatile modified stamp by construction and absorbing pure whitespace and quoting churn; `src/vaultspec_rag/_store_models.py`.
- [ ] `P01.S03` - Cover the subset definition with a test that fails when a payload field is added without entering the subset digest; `src/vaultspec_rag/tests/`.

### Phase `P02` - Split the fingerprint and classify

Change detection stops digesting raw file bytes and computes a body digest plus a subset digest, routing each delta to the cheapest correct outcome: re-embed, payload-only upsert, or nothing.

- [ ] `P02.S04` - Replace the raw whole-file digest with a body digest plus a subset digest, normalising the body the way the chunker already normalises it; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `P02.S05` - Persist both digests in the sidecar under the existing meta-versioning convention so an old sidecar is recognised rather than misread; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `P02.S06` - Classify a body-digest delta as re-chunk and re-embed, preserving the current indexing path for that branch unchanged; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `P02.S07` - Route a subset-only delta to a payload-only upsert that rebuilds the document's payloads and leaves its vectors untouched; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `P02.S08` - Classify a volatile-stamp-only change as unchanged so it reaches neither the encoder nor the store; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [ ] `P02.S09` - Hold the first run under the new scheme to a re-classification rather than a re-embed, reusing donor vectors from the root's own collection wherever the body digest matches; `src/vaultspec_rag/indexer/_vault_indexer.py`.

### Phase `P03` - Make the unscoped escalation a convergence pass

The watcher's failure escalation keeps its convergence guarantee by re-classifying through the split fingerprint rather than re-embedding every unchanged body.

- [ ] `P03.S10` - Run the split classifier over the full corpus on the unscoped escalation so convergence is reached by digest comparison and payload updates rather than a blanket re-embed; `src/vaultspec_rag/watcher.py`.
- [ ] `P03.S11` - Leave the durable convergence-pending bit and the escalation trigger semantics unchanged, confirming only the work the escalated pass performs is narrowed; `src/vaultspec_rag/watcher_retry.py`.

### Phase `P04` - Prove the classification can fail

Each classification branch gets a guard test proven red-then-green by mutation, because a wrong fingerprint degrades silently and passes every assertion that does not count encodes.

- [ ] `P04.S12` - Prove the stamp-only guard bidirectionally: assert zero encodes on a modified-stamp bump, weaken the fingerprint back to a raw-file digest, watch the encode assertion fail, restore, watch it pass; `src/vaultspec_rag/tests/`.
- [ ] `P04.S13` - Prove the metadata-only guard bidirectionally: assert a tags-only edit updates payloads with zero encodes, route metadata changes into the re-embed branch, watch it fail, restore, watch it pass; `src/vaultspec_rag/tests/`.
- [ ] `P04.S14` - Prove the body guard bidirectionally: assert a body edit re-embeds, drop the body digest from the fingerprint, watch it fail, restore, watch it pass; `src/vaultspec_rag/tests/`.
- [ ] `P04.S15` - Measure an incremental vault run over a stamp-churned corpus against the recorded pre-change baseline and record both figures; `src/vaultspec_rag/tests/integration/`.

## Parallelization

`P01` blocks everything: the subset contract is the input to both digests, so no
classification step can be written before it exists. `P02` is sequential within
itself - `S04` and `S05` establish the digests and the sidecar shape that `S06`
through `S08` branch on, and `S09` depends on all three branches being decided.

`P03` may run alongside `P02.S06`-`S09` once `P02.S04` has landed, since it
consumes the classifier rather than the branch routing, and it touches a
different pair of modules.

`P04` is the one genuinely parallel phase: `S12`, `S13`, and `S14` each mutate a
different part of the fingerprint and can be proven independently, but each
requires its own branch from `P02` to exist first. `S15` runs last - it needs
every branch in place to be a meaningful measurement, and it needs the
pre-change baseline captured before `P02.S04` lands.

## Verification

- A `modified:`-stamp-only edit to a vault document classifies as unchanged and
  drives zero encodes and zero store writes.
- A tags-or-related-only edit updates the document's point payloads and drives
  zero encodes; the stored vectors are byte-identical before and after.
- A body edit re-chunks and re-embeds the document, unchanged from today.
- Each of the three guards above has been driven red by the mutation named in
  its Step, failing on its own encode-count or payload assertion rather than on
  an import or collection error, then restored and driven green in one
  uninterrupted sequence, with both directions recorded in the Step's execution
  record.
- Adding a field to a vault point payload without adding it to the subset digest
  fails `P01.S03`'s test.
- The first run under the new scheme re-classifies the corpus without a full
  re-embed: encode count is bounded by the documents whose body digest actually
  differs.
- A watcher failure escalation converges the corpus without re-embedding
  unchanged bodies, and the durable convergence-pending semantics are unchanged.
- An incremental vault run over a stamp-churned corpus is recorded against the
  pre-change baseline, both figures stated.
- `ruff`, `ty` over the changed files, and the vault and indexer test modules
  pass; no `torch` import is added to any module a chunk worker can reach.
