---
tags:
  - '#exec'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:36214099bb75938002423d80d51669252302a7ef28007650b6cd498b5bfbb059'
step_id: 'S01'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
---

# Create the shared stat-evidence gate module with advisory sidecar persistence, racy-window trust rule, and fail-toward-rehash semantics

## Scope

- `src/vaultspec_rag/indexer/_stat_gate.py`

## Description

- Add `src/vaultspec_rag/indexer/_stat_gate.py`: `StatEvidenceGate` with load, `hash_file`, `prune`, `persist`; advisory sidecar `key -> [size, mtime_ns, content_hash, hashed_at_ns]` behind a versioned reserved key.
- Trust a recorded hash only on exact `(size, mtime_ns)` match with the recorded mtime at least 2s older than the recorded hashing instant.
- Discard the whole sidecar on any parse or shape defect, including bool-typed ints; swallow persist `OSError` with a warning.

## Outcome

Gate module in place; every degraded state falls through to `hashlib.file_digest` exactly as the ungated loops did.

## Notes

None.
