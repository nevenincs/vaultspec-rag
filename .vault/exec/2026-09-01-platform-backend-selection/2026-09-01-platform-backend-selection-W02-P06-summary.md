---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:1a68feb43e62ae2fbcaadafd37999d2811a004127ee01570bbb79bffd0f7bb2b'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# `platform-backend-selection` `W02.P06` summary

Updated operator surfaces for CUDA and MPS without weakening refusal behavior.

## Description

CLI install, start, lifecycle, diagnostics, status, and process surfaces use the canonical backend resolver. MPS CPU fallback is diagnosed as an explicit configuration refusal, and unavailable systems report that neither CUDA nor MPS is present while CPU remains unsupported. Existing CUDA diagnostics and service behavior are preserved.

## Verification

Operator-focused tests passed, including fallback, status wording, service preflight, and centralized-load guards with mutation proofs.
