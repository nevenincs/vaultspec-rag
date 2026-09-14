---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-26'
body_hash: 'sha256:67e9c65d6fa192ca23f39ca8f1b80b6cf753055634e442e7b0b5304bae8dc399'
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

REPORT-DEFERRED. Superseding the earlier REPORT-SKIP with the same verdict and an explicit disposition: the transport switch is not attempted, this Step stays open, and the work is handed to a decision record of its own. `prefer_grpc=True` on the current client would target the qdrant default gRPC port 6334 while the managed supervisor listens on `http_port - 1`, so the switch is not a flag flip: it needs a new configuration surface (gRPC port discovery threaded from the supervisor through config to the store client) and its own failure-mode analysis. Dependency-wise the switch is free; topologically it is unsafe today. Local mode untouched by definition.

Scope the successor decision record must cover, so it is not re-derived:

- The gRPC port surface. The supervisor already accepts an explicit `grpc_port` and derives `http_port - 1` when none is given, and it exports that value to the child as its listener setting. The store learns only `qdrant_url`. Either the derivation becomes a single accessor both sides read, or the port becomes configuration the supervisor and the store are handed - one home for the fact, never a second copy of the arithmetic. Unmanaged remote servers supply a URL whose gRPC port cannot be assumed at all, so the surface must express absent.
- The exception-surface migration. The store's write-failure classifier and its donor-read miss detection both read REST shapes; under gRPC they must read gRPC status codes with equivalent tests. This is the part that makes the change a decision rather than a flag: getting it wrong turns a full disk into an infinitely retried transient fault.
- The upside, so the successor knows it is worth doing: 383 ms against 482 ms per-batch p50, a 20-25% per-call transport saving, measured on the pinned server during research with same-session control. That is real money on a rebuild-class run of a hundred-plus batches.
- The verification the switch owes: pin compatibility is already established (the installed client ships grpcio and protobuf as core dependencies, no bump), so what remains is a measured per-batch delta through the production upsert on both transports plus the reclassification tests.

## Notes

The measured 20-25% per-upsert transport win recorded in the decision record remains unharvested; the follow-up must add the gRPC-port knob before flipping the client flag.

Re-examined during the plan closeout; the skip stands and gains a second reason. The store's error handling is written against the REST exception surface: the donor read in `src/vaultspec_rag/store.py` branches on `UnexpectedResponse.status_code == 404` to treat a vanished donor collection as a miss, and the write classifier in `src/vaultspec_rag/_store_writes.py` separates unrecoverable storage exhaustion from transient failure by walking the exception chain for a wrapped ENOSPC and for the HTTP 500 whose body names a WAL buffer overflow. Under gRPC those become status codes on a different exception type, so a transport flip silently reclassifies a full disk as transient and would retry writes that can never land - while burning GPU upstream. The switch therefore needs the port knob AND a mapped classification for the gRPC error surface, with its own tests. It is a decision record of its own, not a Step of this plan.

Re-verified empirically in a later session, which converts two of the claims
above from code reading into observation. The port claim holds: the managed
server was listening on 127.0.0.1:8764 and 127.0.0.1:8765 and on nothing else,
so the derived `http_port - 1` gRPC listener is real and the qdrant-client
default 6334 is closed. The local-mode claim also holds, and more strongly than
"local mode ignores it": in the pinned qdrant-client 1.18.0 the constructor
dispatches `path=` to `QdrantLocal(location=path)` and never forwards
`prefer_grpc` or `grpc_port` to it at all, so local mode has no transport
argument to ignore and the switch is inert there by construction rather than by
policy. One correction to the reasoning, which makes the classifier hazard
narrower but no safer: `classify_write_error` in
`src/vaultspec_rag/_store_writes.py:99-117` does not read `status_code`. It walks
the chain for an `OSError` carrying `ENOSPC` and then matches the lowercased
exception text against the markers "no space left on device" and "wal buffer
size exceeds", falling through to `transient`. Text matching is transport-blind,
so disk-full detection *may* survive gRPC if the server's message text reaches
the exception string. That is the whole risk: it is unverified either way, and
the failure mode when it does not survive is an unbounded retry against a full
disk. The donor-read branch has no such ambiguity - it tests
`isinstance(exc, UnexpectedResponse)`, an HTTP-layer type gRPC never raises, so
that branch stops matching outright. A successor decision record must measure
the gRPC exception text rather than assume it, and must cover the donor branch
regardless.
