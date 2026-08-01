---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:62b28a2f9a4c22ad842777edaae92bc87c9a7a0e7784ee760b52e167ac9f0546'
related:
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` audit: `w05 public surfaces`

## Scope

Reviewed the `W05.P09` and `W05.P10` implementation on `main` against D6 and
steps S61-S74, S108-S120, and S125-S128. The review covered the closed source
parser, document result shaping and filters, combined candidate selection,
per-domain partial outcomes, indexing and cleanup lifecycle routes, resident
transport, CLI and MCP adapters, status/readiness, and real-behavior test
integrity.

## Findings

### w05-public-surfaces | high | Combined search silently discards accepted filters

Search validation explicitly permits code, vault, and document filters for the
combined source. The HTTP payload builder serializes domain filters only when
the selected source is exactly code, vault, or document, while both the
in-process CLI branch and the combined public facade accept only query and
top-k. The server combined dispatch likewise forwards no filters. A caller can
therefore request path, source, extractor, or metadata restrictions and receive
unfiltered results without an error. This violates D6 and S65/S108.

### w05-public-surfaces | high | Complete combined-search failure masquerades as empty success

`CombinedSearchOutcome.partial` is false when every domain fails. The server
still emits the normal search success envelope with an empty result list and a
"Found 0" summary, and CLI domain-failure rendering runs only when `partial` is
true. An all-domain operational failure is consequently indistinguishable from
three empty successful indexes on normal CLI and MCP paths, despite the nested
domain records. The combined outcome needs an explicit overall success state.

### w05-public-surfaces | high | Combined reindex collapses admission failure before domain creation

The reindex route validates every domain into one list before creating any job.
If one domain's policy or support-profile admission raises, the shared outer
handler returns one request error and no domain jobs are created. For example,
a refused document corpus prevents otherwise valid vault and code jobs. This
contradicts the independent partial outcome required by D6 and S66/S109.

### w05-public-surfaces | medium | Combined count preflight sits outside per-domain outcomes

The combined search facade obtains all three collection counts before entering
the per-domain exception boundary. A collection-specific count/schema failure
therefore aborts the complete request instead of becoming one failed domain
alongside successful results from the others. Move count and empty-index
handling into each domain operation.

### w05-public-surfaces | medium | MCP advertises feedback parameters that are ignored

The document and combined MCP tools accept `like_ids` and `unlike_ids`, and the
transport sends them, but document and combined server dispatch does not pass
them to the public facades or searcher. The tools therefore advertise controls
that have no effect. Either implement domain-aware feedback semantics or reject
and remove these arguments until supported.

### w05-public-surfaces | medium | Planned public-surface verification is absent

The planned real HTTP/API verification module does not exist. The real MCP
session exercises document and combined search only against empty indexes, and
the real-store test invokes `VaultSearcher.search_combined` rather than the
public combined facade used by HTTP, CLI, and MCP. No real test proves unknown
HTTP source rejection, public combined filtering, partial or complete failure
rendering, or non-empty MCP document result shaping. This allowed the findings
above to pass the focused suites.

## Recommendations

1. Add a typed combined-filter input shared by the public facade, service route,
   transport, in-process CLI, and MCP; apply each filter only to its owning
   domain before the common final ranking boundary.
1. Give combined outcomes explicit `ok` and `partial` truth for all-success,
   mixed, and all-failed states. Return and render complete failure as failure.
1. Validate and create combined reindex domains independently, preserving a
   structured admission or creation failure for each domain.
1. Move collection count probes inside the same per-domain search boundary as
   query execution.
1. Remove unsupported feedback parameters or implement them end-to-end with a
   defined cross-collection identity contract.
1. Add non-empty real HTTP and MCP tests plus public-facade tests for combined
   filters, unknown sources, mixed failure, and complete failure.
