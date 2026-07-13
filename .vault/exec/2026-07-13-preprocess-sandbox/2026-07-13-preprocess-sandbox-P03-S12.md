---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S12'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Thread preprocess_skipped and preprocess_failures into the job record and the /jobs response so extraction failures are client-visible

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Seed the two preprocess outcome fields onto the job record at start with safe defaults.
- Add `preprocess_skipped` and `preprocess_failures` parameters to the finish recorder and
  store them on the record, keeping the existing human-readable summary string intact.
- Defensively copy the failures list in the snapshot serializer so callers cannot mutate
  live registry state.
- Thread the two fields from the index result into the finish call at both the
  background reindex site and the watcher code-reindex site.
- Cover the new behavior with registry unit tests asserting the defaults, the surfaced
  failures, and the defensive copy.

## Outcome

A client polling the jobs surface now sees which files failed extraction and why, not
just a summary count. The job record carries `preprocess_skipped` (int) and
`preprocess_failures` (list of `"rel_path: reason"` strings); both are seeded to `0`/`[]`
at start so the serialized envelope always includes them, and populated at finish from
the index result. The `/jobs` route serializes the registry snapshot directly, so the
two fields flow into its JSON response with no route change. The finish recorder gained
two keyword parameters that default to the no-preprocess case, so existing callers are
unaffected. The snapshot serializer copies the failures list so a consumer mutating a
returned record cannot corrupt the live registry.

## Outcome verification

`ruff check`, `basedpyright`, and the jobs unit suite all pass; the three new registry
tests are green, including one that mutates the serialized failures list and asserts the
stored record is unchanged.

## Notes

The watcher's code-reindex finish call also carries the index result, so it was threaded
identically to keep watcher-triggered reindexes surfacing failures the same way as
tool-triggered ones; that one-line change lives in `watcher.py` but belongs to this
step's contract.
