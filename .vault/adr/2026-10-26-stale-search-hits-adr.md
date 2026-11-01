---
tags:
  - '#adr'
  - '#stale-search-hits'
date: '2026-10-26'
modified: '2026-10-26'
body_schema: 'body-v2'
body_hash: 'sha256:f778a923ba467fb4b034c5f8a05425bf772881c80796d15061e8230fc135a440'
related:
  - "[[2026-10-26-stale-search-hits-reference]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-09-08-search-readiness-contract-adr]]"
  - "[[2026-10-12-destructive-rebuild-lifecycle-adr]]"
  - '[[2026-09-08-incremental-publication-cost-adr]]'
---

# `stale-search-hits` adr: `verify delivered hits and reconcile confirmed stale content` | (**status:** `accepted`)

## Problem Statement

A published index can return a valid ranked hit whose source file has since changed or disappeared. Publication readiness and point breadth cannot establish that a delivered file still matches disk. Users need an explicit warning and bounded recovery without making a query authorize a full rebuild. The baseline implementation seams are in `2026-10-26-stale-search-hits-reference`.

## Considerations

- Returned indexed content remains useful while its source changes; freshness metadata must preserve ranking, snippets and result membership.
- Publication evidence is backend-, root- and source-specific. Unavailable or changing evidence cannot prove a stale file.
- Search latency and resource use must remain bounded independently of corpus size.
- `2026-09-07-explicit-reindex-authority-adr` reserves full rebuild authority to operators, while `2026-09-08-search-readiness-contract-adr` owns publication readiness and adapters.

## Considered options

- **Trust publication readiness alone.** Rejected: it cannot detect a changed file behind a delivered hit.
- **Scan and repair the whole corpus synchronously on every search.** Rejected: unbounded work changes the cost of reading and delays useful answers.
- **Verify final delivered hits and supervise bounded background reconciliation.** Chosen: precise warnings and limited repair preserve useful search and explicit rebuild authority.

## Constraints

Accepted 2026-10-26 under the user's explicit authorization to implement stale-hit detection and background reconciliation, including the clarification that a required rebuild must bubble to the operator. Acceptance authorizes implementation and the scoped prior-record amendments, not an operational rebuild.

- Verify only final reranked delivered hits, after filtering and truncation. Deduplicate reads per canonical file and bound file count, bytes and work. Resolve paths safely beneath the requested root, reject unsafe/nonregular targets and treat concurrent change as unverifiable.
- Compare stable current file bytes with canonical published file evidence for the selected source and backend. Code and documents use raw content identity. Vault uses its existing semantic fingerprint: raw identity is the fast path, while changed raw bytes with unchanged body and indexed metadata remain current, including a non-indexed modified-stamp refresh. Missing publication evidence stays unverifiable; do not infer currency from a speculative line-content fallback.
- Add per-hit `freshness` with values `current`, `stale`, or `unverifiable`, plus `stale_reason=content_changed`, `file_missing`, or null. A proven mismatch or safely confirmed absence can be stale. Unknown, unreadable, oversized, unsafe and transient observations remain unverifiable and never trigger repair.
- Preserve hits, scores, ordering and indexed snippets. Hit freshness neither replaces publication readiness nor proves authoritative absence.
- In managed service mode, confirmed stale final hits schedule bounded, coalesced audit after HTTP response delivery through one runtime-owned bounded worker queue. A consistent exact backend projection with continuing file drift permits an existing ordinary incremental job request for the affected root and concrete source. This is the existing unscoped incremental request, not a new persisted exact-path repair protocol; the incremental boundary must still refuse full cost. Search does not wait for audit or indexing. Embedded raw Python result models may remain unverifiable by default; local adapter verification, where present, never queues service work.
- Automatic work never executes or retries a full rebuild. Proven compatibility/schema/evidence incompatibility blocking audit, or a repair job returning `full_reindex_required`, becomes service-owned `rebuild_required` diagnostics with an executable existing `index --rebuild --type <source>` command scoped to the root and service port where applicable. Missing or transient evidence alone does not manufacture rebuild authority or confirmed incompatibility.
- Managed HTTP, CLI and MCP carry the same canonical verdict, repair state and remediation. The additive `drift_audit` list reports per-source status `pending`, `incremental_requested`, `deferred`, `rebuild_required`, or `resolved_or_unverifiable`, with bounded paths, reason and repair job identity where known. Unknown or conflicting observations are deferred, rather than called confirmed incompatibility. Existing incremental authority, reset epochs, publication fencing, GPU discipline and rebuild lifecycle remain binding.

## Implementation

We will extend canonical result models and their existing serializers, verify bounded final results in the shared managed search path, and add one runtime-owned drift auditor for confirmed-hit observations. This coordinator owns only bounded audit scheduling and observations; it reuses the canonical exact audit, publication authority and JobManager. Legacy breadth remediation remains separate evidence handling. No second JobManager, publication authority, indexer or adapter-owned classifier is introduced. Initial implementation limits are 2 MiB per file, 8 MiB per page and a soft 100 ms check budget, with one read per file and a 600-second root/source cooldown. These limits are implementation choices within the binding bounded-work and coalescing obligations. Capture the proof fence before retrieval and validate it after checking. Reuse exact projection audit before ordinary incremental admission through the same runtime registry that serves the request.

The scoped 2026-10-26 amendments in `2026-09-07-explicit-reindex-authority-adr`, `2026-09-08-search-readiness-contract-adr`, and `2026-09-08-incremental-publication-cost-adr` reconcile the bounded search exception, disk-read budget, and separately admitted background audit authority. Normal publication remains delta-proportional. `2026-10-12-destructive-rebuild-lifecycle-adr` is reused unchanged.

## Rationale

Checking the small delivered page gives the user evidence about what they will inspect while avoiding a corpus scan on the serving thread. Reusing the publication and remediation owners identified in `2026-10-26-stale-search-hits-reference` preserves proof fencing, attribution and incremental refusal. A visible operator action closes the recovery loop when bounded repair cannot safely proceed.

## Consequences

Search performs bounded filesystem I/O and can return mixed per-hit freshness states. Unverifiable hits remain useful but carry no assertion of currency. Background convergence may take later queries to become visible; a current response cannot promise the filesystem will remain unchanged after verification. Full rebuild remains an explicit operator action, including after confirmed drift. Implementation completion is established by the linked plan and review, not this acceptance.
