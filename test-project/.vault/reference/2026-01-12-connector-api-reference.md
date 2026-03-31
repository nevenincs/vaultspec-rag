---
tags:
  - "#reference"
  - "#connector-api"
date: 2026-01-12
related:
  - "[[2026-01-12-connector-protocol-design]]"
  - "[[2026-01-15-connector-api-phase1-plan]]"
---

# Connector API Reference

## Overview

The Connector API defines how external data sources and sinks integrate with Nexus pipelines. All connectors implement the `NexusConnector` gRPC service interface.

## gRPC Service Definition

```protobuf
service NexusConnector {
  rpc Fetch(FetchRequest) returns (stream Record);
  rpc Push(stream Record) returns (PushResult);
  rpc Schema(SchemaRequest) returns (SchemaResponse);
}

message Record {
  bytes payload = 1;
  string key = 2;
  int64 timestamp_ms = 3;
  bool error_payload = 4;
}

message FetchRequest {
  string cursor = 1;
  int32 batch_size = 2;
}

message SchemaResponse {
  string schema_json = 1;
  string schema_hash = 2;
}
```

## `ConnectorRegistry`

The `ConnectorRegistry` is the central directory of available connectors. All connectors must register before a pipeline that references them can start.

```rust
pub struct ConnectorRegistry {
    connectors: DashMap<String, ConnectorHandle>,
}

impl ConnectorRegistry {
    pub async fn register(&self, id: &str, addr: &str) -> Result<(), RegistryError>;
    pub fn get(&self, id: &str) -> Option<Arc<ConnectorHandle>>;
    pub fn list(&self) -> Vec<String>;
}
```

`register` dials the gRPC endpoint with a 5-second timeout, calls `Schema`, validates schema compatibility, and stores the `ConnectorHandle`. Returns `RegistryError::AlreadyExists` if a connector with the same ID is already registered.

## `ConnectorHandle`

A `ConnectorHandle` wraps the established gRPC channel and the validated schema.

```rust
pub struct ConnectorHandle {
    pub id: String,
    pub schema: SchemaResponse,
    pub(crate) client: NexusConnectorClient<Channel>,
}
```

`ConnectorHandle::fetch(cursor, batch_size)` returns a `tonic::Streaming<Record>` for consuming data from the source.

## Built-In Connectors

### `FileConnector`

Reads newline-delimited JSON from a local file path.

```rust
let connector = FileConnector::new("/data/events.ndjson");
```

Throughput: ~380k records/sec on SSD. Batch size defaults to 64 lines per read call.

### `NullConnector`

Produces an infinite stream of empty records. Useful for pipeline load testing.

## Backpressure

The `ConnectorRegistry` subscribes to the scheduler's `BackpressureMonitor`. When the pipeline signals `Congested`, all active `Fetch` streams pause between batches. The pause is implemented by checking the backpressure watch channel before each batch read.

## Error Handling

- `RegistryError::AlreadyExists` — duplicate connector ID
- `RegistryError::ConnectionFailed` — could not reach gRPC endpoint within timeout
- `RegistryError::SchemaMismatch` — connector schema incompatible with pipeline stage
- `RegistryError::Timeout` — `Schema` RPC did not respond within 5 seconds
