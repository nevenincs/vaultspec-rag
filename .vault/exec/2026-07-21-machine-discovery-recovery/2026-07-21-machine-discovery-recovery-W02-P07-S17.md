---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8516aab6623484c2b6d6a6ccdd21275099db3522f1d9df5b59934220dd921772'
step_id: 'S17'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Propagate typed degraded discovery through service-dependent transport errors without compatibility fallback

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Define a service-unavailable error that carries the typed resolution, exposing the
  refusal reason, the live holder, and the rendered evidence.
- Resolve the service address through the typed resolution, raising that error instead of
  returning an absent port, with no compatibility fallback on any degraded outcome.

## Outcome

A service-dependent call now fails with the discovery evidence behind it, so a caller can
distinguish a machine with nothing running from a live holder whose published address
cannot be trusted.

## Notes

The transport deliberately refuses to guess. When a holder owns the singleton but its
pointer is untrustworthy, resolving any address - including one from the status file -
would send the caller to a service the owner never advertised, which fails later and less
legibly than refusing here.

The typed resolution is imported inside the function and only for type checking at module
scope, so the transport keeps its import-light boundary: resolving still loads neither
torch, nor the store, nor the command-line package.
