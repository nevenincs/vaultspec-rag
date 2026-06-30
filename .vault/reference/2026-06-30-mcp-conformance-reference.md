---
tags:
  - '#reference'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-mcp-conformance-research]]"
---

# `mcp-conformance` reference: `MCP specification baseline and conformant search surface`

Grounding for the MCP conformance epic: the current Model Context Protocol
specification (revision `2025-11-25`) and the Python SDK in use, mapped against the
repo's existing MCP server, with the divergences enumerated and a recommended
spec-conformant tool surface under the decided narrow scope (MCP is code search, vault
search, and index-refresh only; lifecycle and administration stay in the CLI). Source
files are named in inline backticks; external spec URLs are listed under Sources.

## MCP specification baseline

The current GA revision of the Model Context Protocol is `2025-11-25`, the stable spec
published on MCP's one-year anniversary (it supersedes `2025-06-18`, which itself
replaced `2025-03-26`). The spec is date-versioned; clients and servers negotiate a
revision during the `initialize` handshake. Over HTTP the negotiated revision is pinned
on every later request via the `MCP-Protocol-Version: 2025-11-25` header; a server that
receives no such header falls back to assuming `2025-03-26`, and an unsupported value
must return `400 Bad Request`.

**Tools.** A tool definition (returned by `tools/list`, paginated via an opaque
`cursor`/`nextCursor`) carries: `name` (unique, 1-128 chars, `[A-Za-z0-9_.-]`, no
spaces); optional `title` (display name); `description`; `inputSchema` (a JSON Schema
object, draft 2020-12, never null - a no-arg tool uses
`{"type":"object","additionalProperties":false}`); optional `outputSchema` (JSON Schema
for the structured result); optional `annotations` (behavioral hints, below); and the
`icons` and `execution.taskSupport` fields new in `2025-11-25`.

**Tool results** carry unstructured `content` (an array) and/or a `structuredContent`
JSON object. Content item types are `text`, `image`, `audio`, `resource_link` (a URI
pointing at a resource), and embedded `resource` (inline `{uri, mimeType, text}`). When
a tool declares `outputSchema`, the server MUST return `structuredContent` conforming to
it, and SHOULD also serialize that JSON into a `text` block for backwards compatibility;
clients SHOULD validate it against the schema.

**Tool annotations** (`ToolAnnotations`) are untrusted-unless-trusted-server hints, not
enforced contracts: `title`; `readOnlyHint` (default `false`) - reads only, never
mutates; `destructiveHint` (default `true`) - may perform destructive updates, meaningful
only when not read-only; `idempotentHint` (default `false`) - repeated same-arg calls
have no additional effect; `openWorldHint` (default `true`) - interacts with an open
world of external entities. They drive client gating, UI risk coloring, and the model's
call decisions.

**Error semantics.** Two distinct mechanisms. Protocol errors are JSON-RPC `error`
objects (e.g. `-32602`) for unknown tools, malformed requests, or server faults - models
are unlikely to recover from these. Tool execution errors are a normal successful
JSON-RPC `result` carrying `isError: true` plus a `text` content block with an actionable,
self-correctable message. The spec is explicit that recoverable failures belong in an
`isError:true` result with actionable feedback so the model can retry, NOT raised as a
protocol error.

**Resources, prompts, completion, `_meta`.** Resources are server-exposed readable URIs;
resource templates use RFC 6570 URI templates (e.g. `vault://{doc_id}`) and support
`completion/complete` argument autocompletion. Prompts are templated message generators.
For a search-focused server the load-bearing surface is tools (the search and refresh
verbs) plus optionally resource templates for direct document fetch; prompts, completion,
and pagination are nice-to-have.

**Transports.** Two standard transports: stdio (subprocess, newline-delimited JSON-RPC)
and Streamable HTTP (a single MCP endpoint, e.g. `/mcp`, serving POST + GET, optionally
upgrading to SSE for streaming/resumability). Streamable HTTP replaces the old
`2024-11-05` HTTP+SSE transport, now deprecated. It supports optional stateful sessions
via an `MCP-Session-Id` header and resumability via SSE event IDs and `Last-Event-ID`.
Local HTTP servers MUST validate `Origin` (DNS-rebinding defense), SHOULD bind only to
`127.0.0.1`, and SHOULD authenticate. For a long-running local service that multiple
agents connect to, Streamable HTTP is the recommended transport; stdio is
one-subprocess-per-client and cannot multiplex.

## Current vaultspec-rag MCP implementation

**SDK version.** `pyproject.toml` pins `mcp>=1.26.0` (the `[mcp]` extra is a deprecated
no-op alias retained for install compatibility). MCP Python SDK `1.26.x` targets the
`2025-11-25` revision, and its FastMCP supports tool annotations, `outputSchema`/structured
output, and the Streamable HTTP transport.

**Transport.** `mcp/_mcp.py` constructs a single shared
`FastMCP("VaultSpec Search", stateless_http=True)`, but the daemon does not serve it over
HTTP. The daemon serves native REST routes only and mounts no `/mcp` endpoint; the MCP
server runs as a standalone stdio subprocess via `mcp.run(transport="stdio")` in
`server/_main.py`. That stdio forwarder loads no model - every tool delegates to the running
daemon over HTTP through `serviceclient`. The `stateless_http=True` flag is therefore
vestigial under stdio. Stdio is one-subprocess-per-client, the intended model for the
agent-facing MCP here.

**Tool shape.** All tools are registered with a bare `@mcp.tool()` (no `annotations=`, no
`outputSchema`, no explicit `title`). Each is a thin async delegation: resolve the port
via `_require_port()`, offload the blocking `serviceclient` call through
`anyio.to_thread.run_sync`, and unwrap. FastMCP derives `name`/`description`/`inputSchema`
from the function name, docstring, and typed parameters; the `dict | list[dict]` return
becomes JSON text content with no validated `structuredContent`. Search and index tools
live in `mcp/_tools.py` (`search_vault`, `search_codebase`, `get_index_status`,
`get_code_file`, `reindex_vault`, `reindex_codebase`); admin/observability tools in
`mcp/_admin_tools.py` (`list_projects`, `evict_project`, `get_watcher_state`,
`start_watcher`, `stop_watcher`, `get_service_state`, `survey_storage`, `get_logs`,
`get_jobs`, `reconfigure_watcher`); plus the `vault://{doc_id}` resource template and the
`analyze_feature` prompt in `mcp/_resources.py`.

**Error handling.** The no-local-fallback contract raises a single
`RuntimeError(_SERVICE_DOWN_MESSAGE)` from `_require_port()`/`_unwrap()` in `mcp/_tools.py`
when the service is absent, with a legible remediation ("...not running. Start it with
`vaultspec-rag server start`."). Because these are raised inside the tool body, FastMCP
converts them into a tool result with `isError: true` carrying the message - which is the
spec-correct mechanism for a recoverable error, though it is incidental rather than
deliberately modeled.

## Divergences from spec and best practice

- **No `outputSchema`/`structuredContent` on any tool.** The `2025-11-25` structured-output
  contract is unused, so clients get untyped JSON text and cannot validate results; the
  `dict | list` union on the search tools yields a loose schema.
- **No tool annotations anywhere.** Per spec defaults this advertises the read-only
  `search_vault`, `search_codebase`, `get_code_file`, `survey_storage`, and
  `get_index_status` as destructive, non-idempotent, open-world write tools - the inverse
  of their true nature - degrading client gating and the model's call decisions.
- **No explicit `title`** on tools; FastMCP falls back to the function name.
- **Error-as-exception is correct but undocumented and uneven.** The service-down
  `RuntimeError` becomes an `isError:true` result (spec-correct), but this is implicit SDK
  behavior, not a modeled contract; `get_code_file`/`get_vault_document` mix `ValueError`,
  `FileNotFoundError`, and `RuntimeError`, all collapsing to the same `isError` result with
  differing prose.
- **Duplicate status surface.** `get_index_status` (`mcp/_tools.py`) and `get_service_state`
  (`mcp/_admin_tools.py`) both delegate to the same daemon `get_service_state` route - two
  names for one behavior.
- **Admin/lifecycle tools violate a narrow-search scope.** `mcp/_admin_tools.py` exposes
  mutating service-control verbs (`evict_project`, `start_watcher`, `stop_watcher`,
  `reconfigure_watcher`) plus observability (`get_logs`, `get_jobs`, `list_projects`,
  `get_watcher_state`, `survey_storage`) - operability concerns the project's own
  `service-domain-owns-operability` direction and the new narrow scope place in the CLI.

## Recommended conformant surface under the narrow scope

Decided scope: MCP = code search + vault/ADR search + index-refresh only; lifecycle and
admin are CLI-only; one multi-tenant service; an absent service must fail fast with a
legible remediation error.

**Tools that stay.** `search_vault` and `search_codebase` - keep, annotate
`readOnlyHint=True, idempotentHint=True, openWorldHint=False`, give each an `outputSchema`
describing its hit list and return matching `structuredContent`, add a display `title`,
and narrow the return away from `dict | list` to one stable shape. `reindex_vault` and
`reindex_codebase` (the index-refresh verbs) - keep; annotate the incremental path
`readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False`. The
`clean=True` drop-and-recreate path is genuinely destructive: either keep
`destructiveHint=True` for it, or move the clean rebuild to CLI-only so MCP stays
incremental and the annotation is honestly non-destructive.

**Optional keepers (read-only retrieval, search-adjacent).** `get_code_file` and the
`vault://{doc_id}` resource template complement search; if retained, mark the tool
`readOnlyHint=True, openWorldHint=False` and keep the resource template (the spec-idiomatic
way to expose document fetch). The `analyze_feature` prompt may stay as a zero-cost
convenience.

**Removed from MCP (CLI-only).** All of `mcp/_admin_tools.py` (`list_projects`,
`evict_project`, `get_watcher_state`, `start_watcher`, `stop_watcher`, `get_service_state`,
`survey_storage`, `get_logs`, `get_jobs`, `reconfigure_watcher`), and `get_index_status`
in `mcp/_tools.py` (the duplicate of `get_service_state`; service-state inspection is a CLI
operability concern under the narrow scope).

**Error behavior to formalize.** Keep the single `_require_port()`/`_unwrap()` `RuntimeError`
with the existing remediation message, but make the `isError:true` mapping deliberate: the
absent-service condition yields a tool result with `isError:true` and the actionable
"service is not running; start it with `vaultspec-rag server start`" text, matching the
spec's tool-execution-error guidance for recoverable failures.

**Transport.** The shipped transport is stdio - the MCP server runs as a standalone stdio
subprocess (`mcp.run(transport="stdio")`) that forwards every call to the running daemon's
native REST through `serviceclient`, and the daemon mounts no `/mcp` endpoint. This is a
settled prior decision (the MCP-as-thin-service-client architecture) and is out of scope to
change here; the `stateless_http` flag on the FastMCP instance is vestigial under stdio. The
MCP specification also defines Streamable HTTP for multi-agent HTTP serving, which the
project deliberately does not use; if a future need for HTTP-served MCP arises, that is the
spec-correct transport to adopt.

## Sources

- MCP spec 2025-11-25, Tools: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- MCP spec 2025-11-25, Transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP spec revision index / releases: https://github.com/modelcontextprotocol/modelcontextprotocol/releases
- Tool annotations (readOnlyHint/destructiveHint/idempotentHint/openWorldHint): https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/
- MCP Python SDK (FastMCP) releases / version-to-revision mapping: https://github.com/modelcontextprotocol/python-sdk/releases
