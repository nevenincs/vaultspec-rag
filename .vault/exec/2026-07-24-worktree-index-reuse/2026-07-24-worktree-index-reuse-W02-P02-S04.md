---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# implement read-only donor-candidate discovery from the storage manifest with sibling-first ranking and a hard candidate cap

## Scope

- `src/vaultspec_rag/indexer/_donor_candidates.py` (new)`

## Description

- Create `src/vaultspec_rag/indexer/_donor_candidates.py` with `discover_donor_candidates(root, kind, *, backend, manifest, cap)`.
- Read candidates from the storage manifest only (`load_manifest` / injected mapping); exclude the indexing root's own `root_collection_prefix`.
- Filter to matching backend and to entries whose recorded `collections` include the kind's collection name (`prefix + suffix` in server mode).
- Rank sibling-first: rank 0 same git common dir (resolved by filesystem inspection of `.git` file -> `gitdir:` pointer -> `commondir`, no git subprocess), rank 1 shared parent directory (fallback heuristic), rank 2 otherwise; newest `last_indexed` first within a rank, prefix as deterministic tie-break.
- Cap the result at the named module constant `DONOR_CANDIDATE_CAP = 3` (tunable in one place by later measurement).

## Outcome

- New module `src/vaultspec_rag/indexer/_donor_candidates.py` (read-only, pure CPU, no torch anywhere on its import chain; heavy neighbours imported function-locally).
- Discovery API: `discover_donor_candidates` returning ranked `DonorCandidate` dataclasses (prefix, root, backend, kind, collection, last_indexed, storage_schema_version, family_rank).
- Ranking is explicitly hit-rate-only; correctness is carried by the eligibility gates and per-point content verification, stated in the module docstring.
- `uv run --no-sync ruff check` clean; `ruff format` applied; basedpyright and ty both clean on the new files.

## Notes

- Ranking's git-family detection reads `.git`/`gitdir:`/`commondir` files directly rather than spawning git; an unreadable or unrecognised layout degrades to the path-family heuristic, never to an error.
- No export hook added anywhere; the module is addressed by its full dotted path.
