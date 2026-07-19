---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S08'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Add --root to the storage delete verb: normalize the root exactly as registration does, resolve via root_collection_prefix, dispatch through delete_prefix, and make an absent namespace an idempotent exit-0 already_absent success in both human and json modes with resolved prefix and queried root in the envelope

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Make the `PREFIX` argument optional and add `--root` to `server storage delete` (`src/vaultspec_rag/cli/_service_storage.py`), enforcing exactly-one addressing with a structured `bad_request` (exit 2)
- Resolve the root against the operator's cwd and derive the prefix through `root_collection_prefix` - the same normalization indexing uses
- Map `skipped`/`no_such_namespace` to an `already_absent` success (exit 0, both modes) via `dataclasses.replace`; echo the resolved root and derived prefix as `queried_root` in the envelope and human output

## Outcome

Harnesses get a sanctioned, idempotent one-verb per-root teardown; `delete_prefix` safety gates (canonical-prefix regex, unknown refusal) are untouched. Commit 7ae79ca.

## Notes

The status mapping lives in the CLI adapter, not `delete_prefix`, so the maintenance cycle's failed/removed accounting is unaffected.
