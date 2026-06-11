---
tags:
  - '#adr'
  - '#search-freshness-and-empty-results'
date: '2026-06-11'
related:
  - '[[2026-06-11-search-freshness-and-empty-results-research]]'
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-05-28-cli-backend-parity-adr]]'
  - '[[2026-05-28-cli-search-filters-adr]]'
  - '[[2026-04-04-test-and-paths-adr]]'
  - '[[2026-05-30-cli-index-default-adr]]'
---

# `search-freshness-and-empty-results` adr: `actionable empty search responses` | (**status:** `accepted`)

## Problem Statement

Empty search results are currently ambiguous. During the live audit, service-backed code
search returned no results for implementation that existed. The user had to infer that the
index might be stale or missing and manually refresh it.

Search responses must distinguish no match from missing index, stale index, target
mismatch, and service contention.

## Considerations

- Agent users rely on JSON and need machine-readable diagnostics.
- Human users need exact next actions.
- Local status can fail when the resident service owns local Qdrant storage.
- Existing backend parity decisions focused on filters and behavior parity, not
  operational interpretation of empty responses.

## Constraints

- Diagnostics must be based on real metadata.
- Search should not perform an implicit expensive index unless explicitly designed later.
- Service-owned local storage must remain single-owner.
- JSON shape must remain stable for agents and scripts.

## Implementation

Attach index and target metadata to search responses, especially empty responses:

- requested source type,
- indexed count for the source,
- target root recorded in index metadata,
- requested target root,
- last indexed timestamp when available,
- freshness or missing-index state,
- active indexing job reference when known.

When results are empty, include a machine-readable reason and suggested command if safe.

When local status hits a service-owned Qdrant lock, direct the user to the service-safe
status or diagnostics path.

## Rationale

An empty result list is not enough information for a production CLI. Users need to know
whether search genuinely found nothing or whether the retrieval substrate is stale or
wrong.

## Consequences

Search responses and status metadata need closer integration. Tests must cover missing,
stale, fresh-but-empty, and target-mismatch cases.

## Codification candidates

- **Rule slug:** `empty-agent-responses-include-state`.
  **Rule:** Agent-facing CLI commands that return empty data must include state metadata
  and recovery guidance when operational state affects interpretation.
