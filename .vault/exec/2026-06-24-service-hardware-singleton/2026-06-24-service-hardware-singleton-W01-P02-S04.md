---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S04'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Add a qdrant port-holder probe reporting whether a managed server is listening

## Scope

- `src/vaultspec_rag/qdrant_runtime/_resolve.py`

## Description

- Added `QdrantEndpointProbe` and `probe_qdrant_endpoint(http_port)` to `_resolve.py`: a pure,
  side-effect-free probe of the loopback Qdrant port reporting listening / ready / version,
  via a proxy-stripped loopback opener (a proxy must not spoof a ready/version answer used to
  decide attach).

## Outcome

The port-holder is now observable: a dead port reports not-listening, a live server reports
ready + version. `ruff` and `ty` pass; verified by the S07 test (dead port + a real stdlib
HTTP server reporting version 1.18.2).

## Notes

Defined the loopback opener locally in `_resolve.py` rather than importing the supervisor's
(the supervisor imports `_resolve`, so the reverse would be circular). No blockers.
