---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-25'
step_id: 'S15'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# switch the server-mode store client to gRPC transport and record the measured per-batch upsert delta

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Verify pin compatibility for gRPC transport: the installed qdrant-client ships grpcio 1.83.0 and protobuf 7.35.1 as core dependencies, so no dependency bump would be required.
- Trace the client construction seam in `src/vaultspec_rag/store.py`: server mode builds from `cfg.qdrant_url` (HTTP) only.
- Trace the managed server's listener wiring in `src/vaultspec_rag/qdrant_runtime/_supervise.py`: the gRPC port defaults to `http_port - 1`, a non-standard port the client configuration never learns.

## Outcome

REPORT-SKIP. `prefer_grpc=True` on the current client would target the qdrant default gRPC port 6334 while the managed supervisor listens on `http_port - 1`, so the switch is not a flag flip: it needs a new configuration surface (gRPC port discovery threaded from the supervisor through config to the store client) and its own failure-mode analysis. Dependency-wise the switch is free; topologically it is unsafe today. Local mode untouched by definition.

## Notes

The measured 20-25% per-upsert transport win recorded in the decision record remains unharvested; the follow-up must add the gRPC-port knob before flipping the client flag.

Re-examined during the plan closeout; the skip stands and gains a second reason. The store's error handling is written against the REST exception surface: the donor read in `src/vaultspec_rag/store.py` branches on `UnexpectedResponse.status_code == 404` to treat a vanished donor collection as a miss, and the write classifier in `src/vaultspec_rag/_store_writes.py` separates unrecoverable storage exhaustion from transient failure by walking the exception chain for a wrapped ENOSPC and for the HTTP 500 whose body names a WAL buffer overflow. Under gRPC those become status codes on a different exception type, so a transport flip silently reclassifies a full disk as transient and would retry writes that can never land - while burning GPU upstream. The switch therefore needs the port knob AND a mapped classification for the gRPC error surface, with its own tests. It is a decision record of its own, not a Step of this plan.
