---
tags:
  - '#audit'
  - '#storage-migration'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:fcdc9c585c2fd39878d423a3238e72b5470539a858d9b6d332763d464f57dc2c'
related: []
---

# `storage-migration` audit: result reporting

## Scope

Reviewed migration outcome handling in `src/vaultspec_rag/cli/_service_storage.py`, its CLI regression tests, and the result contracts in `docs/cli.md` and `docs/automation.md`. The change affects reporting only; copying, source preservation, destination skipping, and cleanup are unchanged. No implementation plan or ADR authorizes a storage-design change.

## Findings

### migration-outcome | high | Failed collections were reported as successful

- [x] Resolved: aggregate failed collection results into exit code 1 and a single JSON envelope with `ok: false`, error `migrate_failed`, and all collection results retained. The original implementation failed four regression cases at the exit-code assertion. Eight focused cases passed after correction. Temporarily restoring unconditional JSON success failed the JSON assertion; restoring the fix passed.

### result-payload | low | Mixed-result coverage needed complete payload assertions

- [x] Resolved: the regression test now checks every source, target, status, point count, and reason in the returned results, including the successful collection in a mixed outcome.

### failure-envelope | low | The generic JSON description excluded partial result data

- [x] Resolved: automation guidance now allows failure envelopes to retain partial results in `data`, consistent with migration reporting.

## Recommendations

No blocking implementation or test-review findings remain. The combined storage tests passed 37 cases with three existing client-version-probe warnings. Tests use mocked clients for the new migration cases; no shared service migration or index mutation was performed. Run the focused suite after final assertion edits. Publish a fixed release before presenting the corrected outcome contract as available in installed version 0.4.23.
