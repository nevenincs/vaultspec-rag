---
tags:
  - '#adr'
  - '#cli-json-output'
date: '2026-05-30'
modified: '2026-05-30'
related:
  - '[[2026-05-30-cli-json-output-research]]'
---

# `cli-json-output` adr: `envelope-wrapped --json mode across every command` | (**status:** `accepted`)

## Problem Statement

Every vaultspec-rag CLI command currently emits Rich tables and
multi-line prose only. Programmatic consumers — agent harnesses,
CI scripts, MCP clients that drive the CLI — have to parse Rich
output or regex against table cells. Issue #112 asks for a
structured `--json` output mode on every command so consumers
branch on a contract instead of scraping prose.

## Considerations

- The MCP layer already publishes Pydantic models for most
  responses (`SearchResultItem`, `SearchResponse`,
  `IndexResponse`, `IndexStatus`, `HealthResponse`,
  `BackendCapabilities`). The CLI tables strip those down to a
  handful of display columns. Reusing the MCP shapes for
  `--json` payloads means consumers learn one schema, not two.
- The MCP error path already uses `{"ok": False, "error": ..., "message": ...}` envelopes (`mcp_server.py:80-103`) that the
  CLI's `_try_mcp_search` / `_try_mcp_reindex` re-emit.
  Completing the symmetry on success (`{"ok": True, "data": ...}`) gives every CLI consumer one branch shape.
- `console` writes to stdout, and the CLI is liberal with
  warnings / status spinners / multi-line remediation prose.
  In `--json` mode any byte on stdout that is not part of the
  JSON document breaks the consumer. The existing
  `_suppress_hf_progress()` (Wave 1F) covers HuggingFace tqdm
  bars; the remaining sources (`console.status`,
  `console.print` warnings, `_display_port_unreachable_error`
  prose) need explicit guarding.
- Wave 1C established the flag-by-flag precedent (`--no-truncate`)
  for rendering options. No shared `RenderOptions` dataclass is
  needed yet; introducing one with three flags
  (`json`, `no_truncate`, `verbose`) would be premature.

## Constraints

- Backwards compatibility: every command's default behaviour
  stays Rich tables. `--json` is opt-in.
- Atomicity: exactly one JSON document per `--json` invocation.
  No interleaved progress fragments, no trailing newlines from
  Rich, no extra `console.print` calls leaking through.
- Exit codes preserved: 0 / 1 / 2 / 3 / 4 mean the same thing
  in `--json` mode as in table mode. The envelope's `ok` field
  is redundant with the exit code by design — both surfaces
  must agree.
- Error envelope is the same shape the MCP layer already uses:
  `{"ok": False, "error": "<code>", "message": "<prose>"}`.
  CLI-only errors (filter mismatch, port unreachable) get new
  `error` codes; MCP-originated errors pass through unchanged.

## Implementation

### Helpers (`src/vaultspec_rag/cli.py`)

- `_emit_json(ok: bool, command: str, *, data=None, error=None, message=None, **extra)`: serialises one JSON document via
  `sys.stdout.write(json.dumps(...) + "\n")`. Never touches the
  Rich console.
- `_emit_json_error_and_exit(command, error, message, code)`:
  wraps `_emit_json(ok=False, ...)` + `typer.Exit(code)`. Used
  by every error path that previously called `console.print(... red...)` + `typer.Exit(...)`.
- `_display_mcp_error` and `_display_port_unreachable_error`
  gain a `json_mode: bool` parameter. When `True`, they call
  `_emit_json_error_and_exit` instead of rendering prose.

### Per-command wiring

- `handle_search`: `--json` bool flag (right after
  `--no-truncate`). When set, emit
  `{"ok": True, "command": "search", "data": {"results": [<SearchResultItem dict>...]}}`. Replace `_display_search_ results` call with `_emit_json`. The MCP fast-path already
  returns dicts that match `SearchResultItem`; the in-process
  path serialises `SearchResult` dataclasses via dataclass
  `asdict`.
- `handle_index`: `--json` bool. Emit `{"ok": True, "command": "index", "data": {"sources": [{"source": "vault", "added": N, ...}, {"source": "codebase", ...}]}}` mirroring the
  existing per-source row layout.
- `handle_clean`: `--json` bool. Emit `{"ok": True, "command": "clean", "data": {"cleared": ["vault", "codebase"]}}`. The
  interactive confirm must be skipped when `--json` is set
  (require `--yes`).
- `handle_status`: `--json` bool. Emit `IndexStatus.model_dump`.
- `service_status`: `--json` bool. Serialise the four signal
  bools + heartbeat age + state + health sub-block + backend
  capabilities. Preserve exit codes 0/3/4 with envelope
  `ok=True` only when state == running.
- `service_projects_list`: `--json` bool. Mirror the
  `list_projects` MCP response shape.
- `service_projects_evict`: `--json` bool. Mirror the
  `evict_project` MCP response shape.
- `service_start` / `service_stop`: `--json` bool. Each panel
  becomes one envelope.

### Stdout silencing in `--json` mode

- Continue to call `_suppress_hf_progress()` (already
  unconditional in `handle_search` / `handle_index`).
- Wrap `console.status(...)` calls in `if not json_mode:` so the
  spinner never starts. The work still runs.
- Replace `console.print(...)` warning / error calls on the
  success and error paths with `_emit_json` / pre-exit `_emit_ json_error_and_exit`.
- `_display_port_unreachable_error(json_mode=True)` calls
  `_emit_json_error_and_exit("port_unreachable", message=..., code=1)` instead of printing remediation prose.

### Docs

- `README.md`: example showing `vaultspec-rag search foo --json | jq '.data.results[0]'`.
- `src/vaultspec_rag/README.md`: a `### --json output mode`
  section under each command group, plus the envelope shape
  spec.
- `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: mention
  `--json` as a global rendering flag.

### Tests

- `tests/test_cli.py` `TestJsonMode` class covers each command
  with `--json`: assert exit code, assert
  `json.loads(result.output)["ok"]`, assert the
  command-specific data shape, assert no Rich box-drawing
  characters present.
- One test per error-path envelope: filter mismatch on
  `search`, port unreachable on `search --port`, MCP-error
  passthrough, `service status` divergent.

## Rationale

The envelope shape was chosen over bare unwrapped output because
the error branch differs per command in the bare case; the
envelope normalises every consumer's first parse step to
`if not result["ok"]: handle_error(result)`. Two extra JSON
keys is a trivial cost.

Flag-by-flag was chosen over a shared `OutputOptions` dataclass
because only three rendering flags exist (`--json`, `--no- truncate`, `--verbose`) and only `handle_search` carries all
three; introducing the dataclass now is premature, and the
existing `--no-truncate` plumbing is the same shape.

MCP Pydantic models were chosen as the JSON schema source over
inventing a parallel CLI-side schema because the MCP shapes
already exist, already document every field, and are already
the contract for the same data crossing the wire to MCP
clients. CLI consumers benefit from learning one schema.

## Consequences

- Every CLI command grows one bool flag. Total surface growth:
  ~9 flags.
- Consumers gain a stable, MCP-mirroring contract. The CLI
  becomes a viable scripting target without sacrificing the
  Rich UX for humans.
- Some Rich progress feedback (status spinners) disappears
  when `--json` is set. Documented in the help string.
- The envelope means parsers can't naively pipe `vaultspec-rag status --json` into a tool that expects a bare `IndexStatus`
  object — they need `jq '.data'`. The README example
  demonstrates this.
