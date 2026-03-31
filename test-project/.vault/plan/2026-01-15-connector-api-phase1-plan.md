---
tags:
  - "#plan"
  - "#connector-api"
date: 2026-01-15
related:
  - "[[2026-01-12-connector-protocol-design]]"
  - "[[2026-01-12-connector-api-reference]]"
  - "[[2026-01-11-connector-patterns-research]]"
---

# Connector API Phase 1 Plan: Registry and gRPC Scaffold

Implement the connector registry and the gRPC service scaffold so that a simple file-based connector can ingest records into a pipeline.

## Phase 1 Scope

1. **`.proto` Definition** — define `connector.proto` with the `NexusConnector` service interface (Fetch, Push, Schema RPCs). Generate Rust stubs with `tonic-build`.

2. **`ConnectorRegistry`** — a thread-safe map from connector ID to `ConnectorHandle`. Connectors self-register at startup by calling `Registry::register(id, endpoint)`. The registry validates the schema returned by the connector's `Schema` RPC against the pipeline stage's expected input schema.

3. **`FileConnector` Reference Implementation** — reads newline-delimited JSON from a local file and streams records via the `Fetch` RPC. Implements backpressure by pausing reads when the downstream pipeline signals congestion.

## Proposed Changes

### `proto/connector.proto`

Define `Record`, `FetchRequest`, `FetchResponse`, `PushResult`, `SchemaRequest`, `SchemaResponse` message types. The `Record` message wraps a `bytes` payload with an optional string key and timestamp.

### `src/connector/registry.rs`

`ConnectorRegistry::register(id, addr)` connects to the gRPC endpoint, calls `Schema`, and stores the validated `ConnectorHandle`. `get(id)` returns a reference to the handle or a `ConnectorNotFound` error.

### `src/connector/file.rs`

`FileConnector::new(path)` opens the file and exposes a `tonic::Streaming<Record>` from the `Fetch` implementation. Lines that fail JSON parsing are emitted as `Record` with `error_payload: true`; the pipeline stage decides whether to skip or abort.

## Acceptance Criteria

- `FileConnector` streams all records from a 10k-line NDJSON file into a pipeline without data loss.
- Schema mismatch between connector output and stage input produces a descriptive error at registration time, not at runtime.
- Registering two connectors with the same ID returns a conflict error.
