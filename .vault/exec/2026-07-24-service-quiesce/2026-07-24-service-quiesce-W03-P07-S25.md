---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ff67f622049221c394a540037f576af48c581d57bad872c2f898eb9fd8a05a11'
step_id: 'S25'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Hard-refuse in-process GPU indexing whenever delegation does not succeed and render truthful human and JSON remediation, because neither --allow-fallback nor a quiesced service block authorizes local compute until verified borrower-lease evidence exists

## Scope

- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/cli/_render.py`
- `src/vaultspec_rag/tests/test_cli_index_fallback_refusal.py`

## Description

Remove delegated indexing's local-compute fallback after an unreachable or
service-owned refusal. Make `--allow-fallback` incapable of authorizing that
path and render service recovery guidance without claiming borrower safety.

## Outcome

Satisfied by `4e9ef7ef` against the clarified renderer scope in `f580b43c`.
Explicit and discovered delegation failures exit non-zero, while dead-port and
quiesced-refusal probes assert that no model, store, or Torch dependency is
initialized and that human and JSON remediation remain truthful.

## Notes

This Step does not create borrower authority and does not alter an intentionally
selected no-service in-process run; W04 owns lease-gated local GPU entry. The
checked-in subprocess guards were inspected but not executed during acceptance.
