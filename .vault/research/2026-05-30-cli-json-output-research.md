---
tags:
  - '#research'
  - '#cli-json-output'
date: '2026-05-30'
related: []
---

# `cli-json-output` research: `cli rich-table inventory + mcp model reuse audit`

## Trigger

Issue #112 — every vaultspec-rag CLI command currently emits Rich
tables only. Programmatic consumers (CI scripts, agent harnesses,
LSP-style tooling) have to scrape table output. The Wave 2 sequence
allocates the third slot to adding `--json` mode across the whole
CLI surface so consumers branch on a structured contract instead
of regex.

## Method

One grounding pass (Sonnet agent) covering six audit areas: per-
command rendering inventory, MCP Pydantic model reuse, error paths,
stdout pollution sources, the existing `--no-truncate` precedent,
and envelope-shape design choice.

## Findings

### Per-command rendering inventory

| Command                                  | Today's Table columns                                                                            | Candidate JSON payload                                             |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `handle_search` (`cli.py:1269`)          | `Score \| Location \| Snippet`                                                                   | `{results: [SearchResultItem]}`                                    |
| `handle_index` (`cli.py:478`)            | `Source \| Added \| Updated \| Removed \| Total \| Time`                                         | `{sources: [IndexResponse]}`                                       |
| `handle_clean` (`cli.py:774`)            | `Source \| Status`                                                                               | `{cleared: [str]}`                                                 |
| `handle_status` (`cli.py:1612`)          | key/value (Device, Storage Path, Vault Documents, Codebase Chunks, Target, Backend Capabilities) | `IndexStatus`                                                      |
| `service_status` (`cli.py:2260`)         | seven divergence rows + `State` + health/capabilities                                            | structured dict with the four signals + state + exit_code + health |
| `service_projects_list` (`cli.py:2496`)  | `Root \| Idle \| Refs \| Last access`                                                            | `{projects: [...], max_projects, idle_ttl_seconds}`                |
| `service_projects_evict` (`cli.py:2550`) | three `console.print` outcomes                                                                   | `{evicted: bool, reason: str}`                                     |
| `service_start` / `service_stop`         | Rich `Panel(...)`                                                                                | `{pid, port, startup_s, log}` / `{pid}`                            |

### MCP Pydantic model reuse

`mcp_server.py:491-664` already defines `SearchResultItem`,
`SearchResponse`, `IndexStatus`, `IndexResponse`, `HealthResponse`,
and `BackendCapabilities`. Every CLI command maps cleanly onto one
of these models. The CLI currently strips them down for table
display; `--json` mode emits the full model so consumers get
every field the backend already produces (e.g. AST metadata on
code search hits, backend capabilities on status). The bare-dict
`list_projects` and `evict_project` MCP responses are documented
in docstrings (`mcp_server.py:1156-1218`) and serve as the JSON
shape for those CLI commands too.

### Error paths per command

Every command has at least one `console.print(...red...)` +
`typer.Exit(...)` path. Categories:

- Filter / argument validation (`handle_search` filter-type
  mismatch).
- MCP `{"ok": False, ...}` envelope rendered by
  `_display_mcp_error`.
- Port unreachable rendered by `_display_port_unreachable_error`
  (multi-line remediation prose).
- GPU / torch init failures via `_handle_gpu_error`.
- Lock contention / file lock errors.
- Service-state errors (`service_status` exit 3/4, projects
  list/evict exit 3, `service_start/stop` various).

The `{"ok": false, "error": ..., "message": ...}` shape already
exists in the MCP layer (`mcp_server.py:80-103`) and is re-emitted
by `_try_mcp_reindex` / `_try_mcp_search`. Adding `{"ok": true}`
for the success case completes a contract that is already
half-implemented.

### Stdout pollution sources

- HuggingFace + sentence-transformers tqdm bars: already silenced
  by `_suppress_hf_progress()` (`cli.py:1235-1245`, Wave 1F).
- Rich `console.status(...)` spinners: `handle_search` in-process
  path, `service_start` poll loop, `service_warmup` download
  loop, `handle_benchmark`. All write to `console` which is
  stdout-bound (`cli.py:56`). Need explicit suppression in
  `--json` mode.
- `console.print(...)` warnings / errors: every non-table line
  hits stdout today. In `--json` mode either the console
  redirects to stderr or each call becomes conditional.
- `_display_port_unreachable_error`: multi-line remediation
  prose. The biggest pollution source for agent consumers and
  the specific complaint behind issue #110.
- Logger output: goes through `configure_logging`, lands on
  stderr or the rotating log file. Not a stdout concern.
- Zero raw `print()` calls anywhere in `cli.py`.

### `--no-truncate` precedent

Wave 1C added `--no-truncate` as a `bool` typer.Option on
`handle_search` (`cli.py:1378-1388`) forwarded as a keyword
argument to `_display_search_results` (`cli.py:1543`) and used
inline in the in-process table build (`cli.py:1603`). No shared
`RenderOptions` dataclass — flag-by-flag. `--json` follows the
same shape: one bool on each command, forwarded into a
rendering branch.

### Envelope shape recommendation

Always wrap in `{"ok": bool, "command": str, "data" or "error"/"message"}`. Rationale:

- Mirrors the existing MCP error envelope so consumers learn one
  contract.
- `service_status` has three exit codes (0/3/4) and three
  shapes; consumers can branch on `ok` first, exit code second.
- `service_projects_evict` returns different bare shapes
  depending on `reason`; the envelope normalises.
- Cost is two extra keys — trivial.

## Recommendation

- Add `_emit_json(ok, command, *, data=None, error=None, message=None)` module-level helper in `cli.py` that
  serialises one JSON document to stdout via `sys.stdout.write`
  (not `console.print`, so Rich formatting never sneaks in).
- Add `--json` bool flag on every command. When set, the
  command suppresses Rich rendering and routes status / error
  output via the envelope helper. tqdm + spinner pollution gets
  the same `_suppress_hf_progress()` treatment plus explicit
  guarding of `console.status(...)` calls behind `not json_mode`.
- JSON payloads mirror the MCP Pydantic models where they
  exist (`SearchResultItem` for search, `IndexResponse` for
  index, `IndexStatus` for status, `HealthResponse` for service
  status). Where no MCP model exists (clean, projects list,
  evict), use the docstring-documented dict shape.
- `_display_mcp_error` and `_display_port_unreachable_error`
  gain `json_mode` paths that emit the envelope instead of
  prose.
