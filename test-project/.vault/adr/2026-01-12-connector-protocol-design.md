---
tags:
  - "#adr"
  - "#connector-api"
date: 2026-01-12
related:
  - "[[2026-01-12-connector-api-reference]]"
  - "[[2026-01-11-connector-patterns-research]]"
  - "[[2026-01-15-connector-api-phase1-plan]]"
---

# ADR: Connector Protocol Design — gRPC over REST | (**Status:** Accepted)

## Problem Statement

Nexus connectors must communicate with external data sources and downstream sinks. The protocol choice affects latency, schema enforcement, and the ease of adding new connector implementations. The connector API must support both push-based and pull-based data sources.

## Decision

Use gRPC with Protocol Buffers for the connector communication protocol instead of REST/JSON.

## Considered Alternatives

### REST with JSON

All connectors implement the `NexusConnector` service defined in `connector.proto`:

```


## Consequences

- **Pro:** Schema enforcement at compile time via `.proto` definitions prevents type mismatches between sources and pipeline stages.
- **Pro:** HTTP/2 multiplexing reduces connection overhead for connectors that serve multiple concurrent pipelines.
- **Con:** Requires a `.proto` compiler in the build toolchain; not as portable as plain HTTP.
- **Con:** Debugging gRPC streams requires specialized tooling (e.g., grpcurl, BloomRPC).
