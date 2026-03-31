---
tags:
  - "#research"
  - "#connector-api"
date: 2026-01-11
related:
  - "[[2026-01-12-connector-protocol-design]]"
  - "[[2026-01-12-connector-api-reference]]"
---

# Research: Connector Integration Patterns in Data Systems

## Summary

Reviewed connector architectures in Apache Kafka Connect, Airbyte, Fivetran, and the CNCF Landscape to inform the Nexus connector API design.

## Kafka Connect

Kafka Connect uses a `Connector` interface with `TaskConfig` for partitioned ingestion. The `SourceConnector` produces records; the `SinkConnector` consumes them. Workers are managed by a Connect cluster that distributes `Task` instances across available workers.

**Relevant to Nexus:** The separation of `Connector` (configuration and task splitting) from `Task` (actual I/O) maps to the `ConnectorRegistry` + `ConnectorHandle` split in Nexus. Nexus simplifies this by not supporting partitioned task distribution in Phase 1.

## Airbyte

Airbyte defines connectors as Docker images that implement the Airbyte Protocol — a JSON-over-stdout interface with `SPEC`, `CHECK`, `DISCOVER`, and `READ` commands. The protocol is language-agnostic: connectors can be written in Python, Java, or any language that produces stdout.

**Relevant to Nexus:** Language-agnostic connector protocols are attractive for adoption but add operational complexity (container lifecycle, startup latency). The gRPC approach trades universality for performance and type safety. For Nexus's current target (intra-cluster deployments with high throughput requirements), gRPC is the better fit.

## Fivetran

Fivetran manages connector lifecycle entirely as a SaaS offering. No self-hosted connector runtime. Not directly applicable to Nexus but demonstrates demand for a managed connector registry with schema evolution support.

## gRPC Streaming vs. REST Polling

For high-throughput connectors (>100k records/sec), gRPC streaming reduces per-record overhead by eliminating HTTP header serialization and maintaining persistent connections. Benchmark data from the `grpc-benchmarks` repository shows gRPC achieving 8-12× higher throughput than REST for payload sizes between 100B and 10KB. This benchmark result directly supported the connector protocol design decision.

## Conclusion

gRPC with Protocol Buffers is the correct protocol choice for Nexus connectors at the target ingestion rates. Language-agnostic alternatives (Airbyte protocol, REST) should be offered as an adapter layer in a future version for broader ecosystem compatibility.
