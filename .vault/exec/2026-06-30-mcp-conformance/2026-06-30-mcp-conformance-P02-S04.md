---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
body_hash: 'sha256:a6c9f11531a37ae7422c3a64aeede3e799c0ef789e6dc5e058a8661f90937652'
step_id: 'S04'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Report the resolution failure class and the discovery source and resolved port instead of an empty-bodied transport error

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

Made empty-body HTTP errors legible in the transport.

## Outcome

`_send_call` now returns a structured dict carrying `http_code` and a message that names the address, the empty or non-JSON body, the likely cause (a service that is not the vaultspec-rag daemon, e.g. the Qdrant port), and the `vaultspec-rag server status` remediation - replacing the opaque `404:` the research recorded.

## Notes

Covered by `test_empty_body_404_carries_a_legible_message` against a real local 404 server (no mocks).
