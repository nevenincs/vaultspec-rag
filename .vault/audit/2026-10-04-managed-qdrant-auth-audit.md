---
tags:
  - '#audit'
  - '#managed-qdrant-auth'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:84b4c82b7cf8714575c772f5614307bc99c616510c41f714fbbec5bb6b6b4bcd'
related:
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
---

# `managed-qdrant-auth` audit: `Managed Qdrant data plane is unauthenticated`

## Scope

An external repository security scan at revision `d126f08` reported the supervised Qdrant child as an unauthenticated local data plane (CWE-306, medium). This audit records that finding, confirms it against the source, and records what the pinned server binary actually does when a key is configured, so a decision can rest on observed behaviour.

## Findings

### unauthenticated-data-plane | medium | Any local account can read, alter or delete indexed content through the managed Qdrant ports

The supervised child is configured entirely through its environment, and that environment names a loopback host, an HTTP port, a gRPC port and storage paths but no credential: `src/vaultspec_rag/qdrant_runtime/_supervise.py:439`. The ports are predictable: the HTTP port defaults to 8765 and the gRPC port to one below it, `src/vaultspec_rag/config/_settings.py:90`, `src/vaultspec_rag/qdrant_runtime/_supervise.py:376`. The shipped client key defaults to unset, `src/vaultspec_rag/config/_settings.py:65`, and the store passes that through, `src/vaultspec_rag/store_runtime.py:411`. Loopback binding keeps remote hosts out but does not separate operating-system users, while the application service in front of the same data requires a private bearer token. A different local account therefore bypasses the token-gated service and operates on collections directly.

### internal-clients-drop-the-key | low | Six of seven server clients never pass a configured key

Only the store passes `qdrant_api_key`. The maintenance cycle and survey warmer, `src/vaultspec_rag/server/_lifecycle.py:711`, `src/vaultspec_rag/server/_lifecycle.py:793`, the manifest reconcile, `src/vaultspec_rag/server/_lifespan.py:199`, the survey route, `src/vaultspec_rag/server/_routes_storage.py:91`, and the storage command group, `src/vaultspec_rag/cli/_service_storage.py:119`, `src/vaultspec_rag/cli/_service_storage.py:1029`, construct a client from the URL alone. Against an operator's key-protected remote server these already fail; under a managed credential they would all fail.

### pinned-binary-key-behaviour | low | The pinned server enforces one key on both protocols and leaves liveness routes open

Observed against the pinned 1.19.0 binary started with the service API-key setting in its environment. Anonymous `/readyz`, `/healthz`, `/livez` and the root version route answer 200, so the supervisor's readiness and version probes at `src/vaultspec_rag/qdrant_runtime/_supervise.py:632` and `src/vaultspec_rag/qdrant_runtime/_resolve.py:124` need no credential. Anonymous `/collections`, `/telemetry` and `/metrics` answer 401, a wrong key answers 401, and the right key answers 200. An anonymous gRPC collection listing fails `UNAUTHENTICATED` and succeeds with the key in metadata. The key does not appear in the child's output. The Python client warns once per construction that a key is being sent over a non-TLS connection.

## Recommendations

For unauthenticated-data-plane: decide how the managed child is credentialed and how every internal client obtains that credential, including a second process such as the storage commands; a follow-on ADR must choose between a per-instance key over loopback TCP and owner-isolated transport, and state the startup verification.

For internal-clients-drop-the-key: construct every server client through one path that resolves the credential, so a client cannot be added without it.

For pinned-binary-key-behaviour: keep readiness and version probes anonymous, and treat an anonymous data request that succeeds as a startup failure.
