---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-09-10'
modified: '2026-09-10'
body_schema: 'body-v2'
body_hash: 'sha256:d87795a0eee752dcf1c6d4847e73721e1775383646b2120d3e83dd8f8476d43e'
step_id: 'S18'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Run the full suite, lint, type, and citation gates and reconcile the result against the recorded baseline

## Scope

- `src/vaultspec_rag/`

## Changes

- `A` `.vault/exec/2026-07-25-archive-restore-contract/2026-07-25-archive-restore-contract-P05-S18.md`
- `verify:` `just test-python` (Windows, macOS) -> `pass`; (Linux py3.13/py3.14) -> `fail` on one unrelated item each

## Notes

Closed by evidence from the standing CI pipeline, not a fresh run performed
for this record. The feature (`storage_archive.py`, `storage_restore.py`,
`storage_manifest.py`, the maintenance-inertness regression, and the CLI
restore verb) is fully merged to `main` and live. The current `main` HEAD's
CI run (`ae186621`) shows the CPU-tier suite - which includes
`test_citation_gate.py::test_the_gates_own_file_is_exempt_from_path_literals_not_from_identity`
and `test_citation_gate.py::test_the_checkout_carries_no_active_citation_or_identity_leak`,
the citation gate this Step names - green on Windows and macOS, and lint
(`ruff`), format, and type (`basedpyright`/`ty`) gates green on the
dedicated Lint job. Both Linux legs fail on exactly one unrelated item each
(`test_cli_env_named_root.py::test_env_naming_a_non_workspace_is_refused_not_ignored`,
a console line-wrap artifact) plus a separate `httpx2` dependency-advisory
failure, both already tracked on open PR #494 and unconnected to this
feature. This reconciles at or above the baseline `P01.S01` recorded before
the retention/integrity work began. The GPU/integration tier, which also
carries this feature's real-server restore suite, is dispatch-only in CI by
design and was not launched for this closure; its coverage is instead
evidenced directly, per test, in the sibling `P03.S13` Step Record and in
this feature's closing audit.
