---
tags:
  - '#research'
  - '#search-freshness-and-empty-results'
date: '2026-06-11'
modified: '2026-06-11'
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-vaultspec-rag-cli-service-ux-audit]]'
  - '[[2026-05-28-cli-backend-parity-adr]]'
  - '[[2026-05-28-cli-search-filters-adr]]'
  - '[[2026-04-04-test-and-paths-adr]]'
  - '[[2026-05-30-cli-index-default-adr]]'
---

# `search-freshness-and-empty-results` research: `actionable empty search responses`

This research grounds the decision to make search responses explain index freshness and
target identity when results are empty or suspicious.

## Findings

### R1. Empty results were ambiguous during the live audit

Initial exact-symbol code searches returned `results: []` even though the requested
implementation existed. The service was healthy, so the empty response looked like either
bad search quality or absence of code.

The actual recovery path required manual inference:

- run service status,
- try local status and hit a Qdrant lock,
- run index dry-run,
- refresh the code index through the service,
- poll jobs,
- retry search.

The CLI did not distinguish no-match from stale index, missing index, target mismatch, or
service contention.

### R2. Local status is not service-safe when Qdrant is owned by the resident service

`vaultspec-rag status --json` failed because the resident service held the local Qdrant
lock. The message was technically accurate, but it did not answer the user's intended
question: what is indexed and whether the current target is fresh.

Search and status need a service-safe path for index metadata while the resident service
owns local storage.

### R3. Search responses need index context

For agent and CLI use, a search response should include enough metadata to interpret
zero results:

- source type,
- indexed document/chunk count,
- index target root,
- requested target root,
- last indexed timestamp,
- index freshness/staleness state,
- active indexing jobs for that target if any.

This metadata is most important on empty responses but useful on all JSON search
responses.

### R4. Existing CLI backend parity is insufficient

Earlier CLI backend parity and search filter ADRs focused on wiring filters and making
CLI/MCP behavior consistent. They do not address the operational meaning of empty results
or target freshness.

The new ADR should supersede any implicit assumption that an empty results list is a
complete response.

### R5. Recommended direction

Search should become self-diagnosing:

- If the index is missing, say so and suggest the service-backed index command.
- If the index is stale or target-mismatched, report the mismatch.
- If no match is found on a fresh index, say the query returned no matches.
- If the service is busy or indexing, include that state or link to the active job.

JSON output should remain stable and scriptable, with diagnostics under a predictable
field rather than prose-only output.
