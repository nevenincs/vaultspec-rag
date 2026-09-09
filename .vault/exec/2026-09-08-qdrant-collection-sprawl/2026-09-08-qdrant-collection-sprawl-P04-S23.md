---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:1517e9fc5d82635ee27740d98bc35a3e7685511cb81ae238f6e11357a0983b27'
step_id: 'S23'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Drop grace-ledger entries naming collections that no longer exist when the ledger is next written

## Scope

- `src/vaultspec_rag/generation_stamps.py`

## Changes

- `M` `src/vaultspec_rag/generation_survey.py`
- `M` `src/vaultspec_rag/storage_reclamation.py`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_generation_survey.py src/vaultspec_rag/tests/integration/test_generation_reclaim.py` -> `pass`

## Notes

The prune landed in `advance_generation_stamps` (`generation_survey.py`) rather than in
`generation_stamps.py`. `record_generation_stamps` only ever serialises a map its caller
already assembled; the map is assembled in `advance_generation_stamps`, which already
receives `held`/`unreferenced` classifications derived from the same live-collection
listing its caller (`reclaim_superseded_generations` in `storage_reclamation.py`) reads
once per cycle. Passing that listing into `advance_generation_stamps` as a plain
`Iterable[str]` keeps `generation_stamps.py` free of any qdrant dependency, matches the
existing parameter shape of `survey_generations`'s own `existing` argument, and avoids a
second `get_collections()` round trip. A stamp survives unless its collection is absent
from that listing; the listing is only ever the caller's own confirmed read, never a
guess, so an unlistable collection is never treated as gone.

The two adaptations this signature change required in `test_generation_survey.py`'s
pre-existing `TestGenerationStampAdvance` tests are recorded under `S24`, which owns
that file and lands in the same commit.
