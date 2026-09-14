---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:eeda4ee5cc37aec021848d86c6623a604abc9b58e3c8ecea7bdaff6448b9b743'
step_id: 'S56'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---


# Run repository lint format type full test vault and diff gates with individual exit codes

## Scope

- `repository-wide verification`

## Changes

- `verify:` `just check-python` -> `fail`
- `verify:` `just check-type` -> `fail`
- `verify:` `just check-vault` -> `fail`
- `verify:` `just test-all` -> `fail`
- `verify:` `git diff --check` -> `pass`

## Notes

Repository failures predate and fall outside this Step's readiness ownership: three release-tool
tests need formatting; strict typing reports embeddings/store/release-tool diagnostics; the
installed vault CLI rejects 1,572 legacy per-Step records; the Python lane has two release/pin
failures; and no compatible GPU service was available. The CPU suite completed 4,921 passes,
four skips, and two failures unrelated to readiness.
