---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:df98e8553fcbfeceac93881ac37b86179ea56a12f7a549797e652ae8d593370c'
step_id: 'S03'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# Add --root to server storage survey, pass it through both the service-first and CLI-direct paths, and render queried_root in human and --json output

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add `--root` to `server storage survey`; the service-first path forwards it
  as the route's `root` query parameter and parses the returned
  `queried_root`.
- On the CLI-direct fallback (no daemon answering), resolve the root through
  the same `root_collection_prefix` derivation in-process and narrow the
  gathered namespaces to its prefix - one derivation, two execution homes.
- Render `queried_root` as a leading line in human output and as a `data`
  field in `--json` output (`_emit_survey_json` gained the optional
  parameter).
- Rename the parse-loop local to `entry_root` to avoid shadowing the new
  function parameter (caught by basedpyright).

## Outcome

`server storage survey --root <path>` reports the authoritative prefix and
the root's namespaces in both output modes and both execution paths. Ruff,
ruff format, and basedpyright clean.

## Notes

None.
