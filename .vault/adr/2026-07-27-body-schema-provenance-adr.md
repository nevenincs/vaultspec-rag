---
tags:
  - "#adr"
  - "#body-schema-provenance"
date: '2026-07-27'
related:
  - "[[2026-07-27-body-schema-provenance-policy-research]]"
supersedes:
  - '2026-07-27-active-corpus-conformance-adr'
modified: '2026-07-27'
---

# `body-schema-provenance` adr: `Validate documents against immutable schema contracts` | (**status:** `accepted`)

## Problem Statement

The live Vault corpus must retain its governing history. Current body-section warnings apply mutable present-day templates to documents authored under earlier contracts, so the warning count is not a valid measure of missing architectural evidence.

## Considerations

`2026-07-27-body-schema-provenance-policy-research` establishes the retroactive behavior and the provenance requirement. New documents must remain strictly validated, while historical documents need an auditable contract rather than an exemption.

## Considered options

Use a date cutoff: rejected because it cannot attest provenance. Bulk-fill current headings: rejected because it invents history. Archive or delete documents: rejected because it removes live governance. Use an immutable schema registry with a hash-attested baseline: accepted.

## Constraints

A future template change must not change an existing document's contract. A changed or newly created document must not self-classify as legacy. Ambiguous legacy records require explicit review rather than automatic acceptance.

## Implementation

Core will provide immutable named section contracts, stamp the current contract on new scaffolds, and validate historical records through a committed path-and-body-hash baseline. The migration will generate that baseline from reviewed repository provenance and fail closed for entries outside it.

## Rationale

The accepted approach follows `2026-07-27-body-schema-provenance-policy-research`: it preserves every record while keeping a verifiable, non-retroactive quality gate for both historical and new content.

## Consequences

The corpus gains a one-time reviewable baseline and future schema upgrades require an explicit immutable contract. In exchange, zero warnings means the corpus matches the contract that actually governed each document, not that evidence was removed or prose fabricated.
