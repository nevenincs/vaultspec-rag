---
tags:
  - '#adr'
  - '#mcp-search-scope'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-mcp-conformance-research]]"
  - "[[2026-06-30-mcp-conformance-reference]]"
  - "[[2026-06-30-mcp-conformance-adr]]"
  - "[[2026-06-18-mcp-service-client-adr]]"
  - "[[2026-06-07-mcp-server-deconflation-adr]]"
---

# `mcp-search-scope` adr: `MCP search-surface scope boundary` | (**status:** `accepted`)

## Problem Statement

The `vaultspec-rag` MCP server has accreted a broad, untested surface that mirrors much
of the CLI: alongside the two search verbs it exposes index control, a duplicate
service-state tool, and a cluster of mutating administration and observability tools
(project eviction, watcher start/stop/reconfigure, jobs, logs, storage survey). Agents
prefer MCP when available, so this sprawl is what an agent reaches for first - and the
grounding research showed it leading an agent into a dead end rather than to an answer.
The companion research and reference establish that the surface also diverges from the
current Model Context Protocol specification (revision `2025-11-25`): no tool
annotations, no structured output, a duplicated tool, and read-only tools advertised as
destructive. This ADR draws the responsibility boundary: what the MCP server is *for*,
which tools it keeps, and which responsibilities belong solely to the CLI. The companion
discovery ADR decides *how* the surviving tools reach the one running service; this ADR
decides *what* the surface is. It is the scope half of the MCP conformance epic, derived
from the research and reference rather than from an audit of shipped code in production.

## Considerations

The decisive principle, set by the epic mandate: the CLI and the MCP server must **not**
duplicate functionality. They converge on a shared *architecture* - the single
multi-tenant service and its discovery, project, and seat model - but they diverge in
*responsibility*. The MCP server is the agent-facing semantic-search interface; the CLI
is the operator-facing control and administration surface. This supersedes the earlier
framing of the epic as a CLI-to-MCP parity exercise: parity is the wrong goal, because a
search tool that also starts daemons, evicts projects, and tails logs is neither a good
search tool nor a defensible security surface.

Factors weighed: the project's existing `service-domain-owns-operability` direction
already holds that operability is service-domain behaviour the CLI adapts - putting
mutating admin verbs on the agent-facing MCP surface contradicts it. The MCP spec frames
tools as model-controlled with human-in-the-loop gating, and favours small, accurately
annotated tool sets; a sprawling surface degrades the model's call decisions and the
client's risk gating. The two search verbs and the index-refresh verbs are the only
tools whose purpose is to answer or freshen an agent's view of the corpus; everything
else is operator control.

## Constraints

This ADR's surviving tools depend on the companion discovery ADR (the sibling
`mcp-conformance` ADR) for how they resolve the one machine service; the scope decision
is coherent only if discovery is fixed in the same epic. The spec-conformance work
depends on the pinned `mcp` SDK (`>=1.26.0`), which targets the `2025-11-25` revision and
supports tool annotations, structured output, and the Streamable HTTP transport already
in use - so no new dependency or frontier risk. Removing tools from the MCP surface is a
**breaking change** for any agent configuration or workflow that invoked the admin tools
through MCP; that breakage is intended (those callers must move to the CLI) but must be
called out. The infrastructure confounds named in the research - server-mode Qdrant
instability and the CPU-only torch build - are out of scope here; this ADR governs the
shape of the surface, not backend stability.

## Implementation

The MCP server is narrowed to a semantic-search surface and brought into line with the
`2025-11-25` specification, expressed as the following decisions.

- **SB1 - The in-scope surface is search plus index-refresh.** The MCP server keeps the
  two search verbs (`search_vault`, `search_codebase`) and the two index-refresh verbs
  (`reindex_vault`, `reindex_codebase`). Read-only document retrieval that directly
  serves search - the `get_code_file` tool and the `vault://{doc_id}` resource template -
  is retained as search-adjacent, along with the zero-cost `analyze_feature` prompt.
  Nothing else is an MCP tool.

- **SB2 - Lifecycle and administration are CLI-only and are removed from MCP.** The
  mutating and observability admin tools - project listing and eviction, watcher
  start/stop/reconfigure and state, service-state inspection, storage survey, jobs, and
  logs - are removed from the MCP surface. Service lifecycle (start, stop, warmup,
  doctor) was never on MCP and never will be: an agent-facing search tool does not manage
  the daemon it depends on. These responsibilities live solely on the CLI, consistent
  with `service-domain-owns-operability`.

- **SB3 - The duplicate status tool is removed.** The `get_index_status` tool, which is a
  second name for the same service-state route as the admin `get_service_state`, is
  removed; service-state inspection is operator-facing CLI behaviour under SB2.

- **SB4 - Convergence is architectural, not functional.** The CLI and MCP deliberately do
  not mirror each other's verbs. They share one service and one discovery/project/seat
  contract (decided in the companion discovery ADR), so that an MCP search resolves the
  same live service a flag-less CLI search resolves; they do not share a feature matrix.
  This decision retires the parity-matrix framing.

- **SB5 - Surviving tools are made spec-conformant.** Each retained tool gains the
  `2025-11-25` affordances it currently lacks: behavioural annotations
  (`readOnlyHint`/`idempotentHint`/`openWorldHint`) that tell the truth about the tool, a
  declared `outputSchema` with matching `structuredContent`, and an explicit display
  `title`. The two search tools are annotated read-only and idempotent over a closed
  world, and their return shape is narrowed from a loose `dict | list` union to one stable
  schema. The transport stays Streamable HTTP at the `/mcp` endpoint.

- **SB6 - Index-refresh keeps an honest annotation; the destructive rebuild is CLI-only.**
  The incremental refresh path stays on MCP and is annotated non-destructive and
  idempotent. The destructive drop-and-recreate rebuild (the `clean` path) is removed from
  the MCP refresh tools and remains a CLI responsibility, so the MCP refresh annotation is
  honestly non-destructive rather than carrying a hidden destructive mode.

## Rationale

The narrowing is grounded in the research (the transcript dead-end and the admin-tool
inventory) and the reference (the `2025-11-25` divergences and the recommended conformant
surface). A search interface that also performs destructive administration is a poor fit
for the spec's model-controlled, human-gated tool model, and it contradicts the project's
own operability ownership rule. Keeping index-refresh on MCP - while pushing the
destructive clean rebuild to the CLI - reflects the one legitimate write an agent needs
(freshen the corpus it is about to search) without handing the agent a destructive verb.
Making the survivors spec-conformant is what lets a client gate them correctly and a
model choose them well; the annotations are not cosmetic, they change call behaviour.

## Consequences

The surface becomes small, honest, and spec-conformant: read-only search tools that
advertise themselves as such, an index-refresh that cannot silently drop a collection, and
no agent-facing path to mutate service state. This is a breaking change for any consumer
that drove administration through MCP - those callers move to the CLI, and the epic must
communicate that. The earlier parity goal is explicitly dropped in favour of a
responsibility boundary, which means the deferred "conformance test matrix" is rescoped
from CLI-to-MCP parity to *boundary enforcement plus spec conformance*: tests that assert
the in-scope tools exist and are correctly annotated, that the out-of-scope tools are
absent, and that search results validate against their declared schema. A pitfall to
watch: the boundary must be enforced mechanically (a test over the registered tool set),
or admin tools will re-accrete the next time someone wants a quick agent-side shortcut.
This ADR depends on the companion discovery ADR to make the surviving tools actually
reach the service; neither is complete alone.

## Codification candidates

- **Rule slug:** `mcp-is-search-not-admin`.
  **Rule:** The `vaultspec-rag` MCP server exposes only semantic search and index-refresh
  tools; service lifecycle, administration, and observability are CLI-only and must never
  be added to the MCP surface.
