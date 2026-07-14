---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S01'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Create the CPU-only config-epoch module: canonical serialization plus blake2b hashing of membership inputs (vaultragignore patterns, nested-gitignore signal, preprocess rule patterns) and content inputs (preprocess invocation fields, html_strip, and vault_chunk_chars for the vault tier), stdlib-only so the spawn worker import chain stays torch-free

## Scope

- `src/vaultspec_rag/indexer/_config_epoch.py`

## Description

- Add the stdlib-only module `_config_epoch.py` (imports only `hashlib` and
  `json`) so it stays importable from the CPU-only spawn chunk-worker chain
  without loading torch.
- Provide a private `_digest` helper that canonicalizes any payload with
  `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)` and hashes it with blake2b, so a semantically-identical payload
  always yields the same digest and TOML option values JSON cannot represent
  degrade to their string form rather than raising.
- Expose `code_membership_epoch` over the resolved gitignore patterns
  (sorted so nested-gitignore traversal order never registers as spurious
  drift), the `.vaultragignore` file patterns, and the preprocess rule
  patterns.
- Expose `code_content_epoch` over the preprocess invocation surface
  (command/entry_point, on_error, resolved timeout, options, per-rule order)
  plus `html_strip`.
- Expose `vault_content_epoch` over `vault_chunk_chars` for the vault tier.

## Outcome

The two-tier epoch mechanism is a pure, side-effect-free hashing surface: it
accepts already-resolved pattern lists and rule objects and returns hex
digests, so the indexers can compute epochs from the inputs a run already
builds without the module performing any I/O or tree walk. A fresh-interpreter
import check confirms it leaves torch out of `sys.modules`, and the same holds
for the chunk-worker import chain. Ruff and basedpyright are clean.

## Notes

The membership hash deliberately sorts the gitignore patterns because
`rglob` traversal order is not guaranteed stable across runs; a genuine pattern
add or remove still changes the multiset and thus the digest. Preprocess rules
are consumed in their already-deterministic resolved-precedence order, so no
extra sort is applied there.
