---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S04'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Replace the raw whole-file digest with a body digest plus a subset digest, normalising the body the way the chunker already normalises it

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Add `src/vaultspec_rag/indexer/_vault_fingerprint.py` with `VaultFingerprint`,
  `fingerprint_text`, `fingerprint_path`, `encode`, `parse`, and `classify`.
- Split `prepare_document` in `src/vaultspec_rag/indexer/_vault_prep.py` into a
  read plus `vault_document_from_text`, so the fingerprint and indexing derive
  from one parse rather than two readings of the same frontmatter.
- Digest the normalised body - `VaultDocument.content`, the exact string the
  chunker splits and the encoder embeds - with line endings normalised first.
- Digest the indexed subset through the contract established in P01.
- Give the stat-evidence gate a per-domain digest function in
  `src/vaultspec_rag/indexer/_stat_gate.py`, defaulting to the raw-bytes
  `file_digest`, and bind the vault indexer's gate to the fingerprint.

## Outcome

The vault no longer digests raw file bytes for change detection. A body delta and
a stale-vector condition are now the same event by construction, because the body
digest covers exactly the text that gets embedded.

Binding the digest to the gate rather than passing it per call is what keeps the
gate's recorded evidence and the fingerprint it is evidence for from ever meaning
different things - each indexer owns one gate over one sidecar, so the digest
function is a property of that pairing.

Line-ending normalisation means a checkout that reflows a file costs nothing.

## Notes

Parsing markdown for every candidate document is new work the raw-byte digest did
not do. The stat gate absorbs it: a file whose size and mtime have not moved is
never read at all. The case that does pay is stamp churn, where the parse is
milliseconds against the GPU seconds it replaces.

The gate's `hash_file` was left in place. It has no production caller - the
indexers all reach `hash_paths` - and collapsing it is a separate concern from
this plan.

Two defects in this Step were found by review after it first landed, both from
the same root cause: the fingerprint decoded the file to text and digested the
re-encoded result, rather than digesting the bytes as stored.

The first was a crash class. Decoding raised `UnicodeDecodeError` on a file that
is not valid UTF-8, and the hashing phase's per-file failure capture catches
`OSError` alone - so one bad byte anywhere in the vault aborted the entire run,
on the full scan, on the scoped path, and at publication after the GPU work was
already done. Every retry aborted identically while the file remained, so vault
indexing stayed wedged until an operator located the byte. The raw-bytes digest
this replaced could not fail that way: such a file hashed, and was skipped with
a warning at the parse phase. The fingerprint now falls back to the bare raw
digest on a decode failure, which `classify` already handles as
raw-comparison-only, and the document skips at parse exactly as before.

The second was a cost defect in the migration bridge. The old scheme digested
bytes; digesting a decoded-and-re-encoded copy disagrees for any file whose line
endings the checkout translated. This repository pins the vault to LF and was
shielded, but a consumer with `core.autocrlf` set checks out CRLF, and there
every document would have classified as a body delta and re-embedded - the exact
full-corpus GPU pass the bridge exists to avoid.

Both are now guarded, each proven red-then-green, including one integration
guard that indexes a real corpus containing a cp1252 byte and requires the run
to complete with the good documents landed.
