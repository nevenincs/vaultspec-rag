---
tags:
  - '#plan'
  - '#cli-json-output'
date: '2026-05-30'
modified: '2026-06-30'
related:
  - '[[2026-05-30-cli-json-output-adr]]'
  - '[[2026-05-30-cli-json-output-research]]'
---

# `cli-json-output` `--json output mode for the vaultspec-rag cli` plan

Implements gh issue #112. Adds `--json` to every CLI command,
wrapping output in a `{"ok": bool, "command": str, "data" | "error" + "message"}` envelope so programmatic consumers
(agents, CI, MCP clients) branch on a structured contract
instead of scraping Rich tables.

### Phase `P01` - Envelope helpers

Provide one success and one failure envelope helper writing a single JSON document to standard output, and teach the shared error renderers to honour JSON mode.

- [x] `P01.S01` - Add the success and failure envelope helpers that serialise exactly one JSON document to standard output with a single trailing newline, the failure helper carrying the exit code; `src/vaultspec_rag/cli/_render.py`.
- [x] `P01.S02` - Teach the shared error renderers to honour JSON mode so an unreachable service and a rejected call emit the envelope rather than human text; `src/vaultspec_rag/cli/_render.py`.

### Phase `P02` - High-traffic commands

Wire the flag onto search, index and status, suppressing spinners and conditional warnings so a JSON run emits nothing but its envelope.

- [x] `P02.S03` - Wire the flag onto the search command, suppressing the spinner and routing results and both error paths through the envelope; `src/vaultspec_rag/cli/_search.py`.
- [x] `P02.S04` - Wire the flag onto the index and status commands, serialising the per-source summary and the index-status shape through the envelope; `src/vaultspec_rag/cli/_index.py`.

### Phase `P03` - Service commands

Wire the flag across the service verbs, preserving their exit codes and turning each rendered panel into one envelope.

- [x] `P03.S05` - Wire the flag onto the service status verb, serialising the lifecycle signals, heartbeat age, derived state and backend capabilities while preserving its exit codes; `src/vaultspec_rag/cli/_service_status.py`.
- [x] `P03.S06` - Wire the flag onto the remaining service verbs so each rendered panel becomes exactly one envelope with its exit code preserved; `src/vaultspec_rag/cli/_service_start.py`.

### Phase `P04` - Tests, documentation and smoke

Prove every command emits exactly one envelope on success and failure, that no stray output reaches standard output in JSON mode, and document the contract.

- [x] `P04.S07` - Cover every command for exactly one envelope on both the success and the failure path, and assert no spinner, warning or progress output reaches standard output in JSON mode; `src/vaultspec_rag/tests/`.
- [x] `P04.S08` - Document the envelope contract and the flag across the project README, the package README, and the shipped discovery rule; `README.md`.

## Description

- `_emit_json` + `_emit_json_error_and_exit` helpers in
  `cli.py`.
- `--json` bool flag on each command (`search`, `index`,
  `clean`, `status`, `server service status`,
  `server service projects list`, `server service projects evict`, `server service start`, `server service stop`).
- `_display_mcp_error` and `_display_port_unreachable_error`
  gain `json_mode` parameter.
- Silence `console.status(...)` spinners and conditional
  `console.print(...)` warnings when `json_mode=True`.
  `_suppress_hf_progress()` already covers tqdm bars.
- Mirror MCP Pydantic models (`SearchResultItem`, `IndexResponse`,
  `IndexStatus`, `HealthResponse`, `BackendCapabilities`) for
  payload shapes where they exist.
- Tests, docs, smoke.

## Steps

### Phase 1 — helpers

1. `_emit_json(ok, command, *, data=None, error=None, message=None, **extra)`: serialises one JSON document to
   `sys.stdout.write` (not via Rich console). Single trailing
   newline.
1. `_emit_json_error_and_exit(command, error, message, code)`:
   composes `_emit_json(ok=False, ...)` + `typer.Exit(code)`.
1. Extend `_display_mcp_error(payload, *, json_mode=False, command=...)` and `_display_port_unreachable_error(port, *, command, json_mode=False)` so the existing call sites switch
   on the flag.

### Phase 2 — wire `--json` on the high-traffic commands

1. `handle_search`: add `--json` bool. When set: suppress
   `console.status` spinner; replace `_display_search_results`
   with `_emit_json(ok=True, command="search", data={"results": [...]})`; route filter-mismatch + port-unreachable + GPU
   errors through `_emit_json_error_and_exit`. The MCP fast-
   path returns dicts that already match `SearchResultItem`;
   the in-process path converts `SearchResult` dataclasses via
   `dataclasses.asdict`.
1. `handle_index`: add `--json` bool. Serialise per-source
   summary; route MCP and port-unreachable errors through the
   envelope helper.
1. `handle_status`: add `--json` bool. Serialise `IndexStatus`
   shape via `model_dump`.

### Phase 3 — wire `--json` on service commands

1. `service_status`: add `--json` bool. Serialise the four
   signal bools, heartbeat age, derived state, health sub-
   block, backend capabilities. Preserve exit codes 0/3/4.
1. `service_projects_list`: add `--json` bool. Mirror the
   `list_projects` MCP response dict.
1. `service_projects_evict`: add `--json` bool. Mirror the
   `evict_project` MCP response dict. Preserve exit codes
   0/1/2.
1. `service_start` / `service_stop`: add `--json` bool. Each
   `Panel` becomes one envelope.

### Phase 4 — clean + minor commands

1. `handle_clean`: add `--json` bool. Require `--yes` when
   `--json` is set (skip the interactive confirm). Emit
   `{"cleared": [...]}`.

### Phase 5 — docs

1. `README.md`: example `vaultspec-rag search "foo" --json | jq '.data.results[0]'`.
1. `src/vaultspec_rag/README.md`: a `### --json output mode`
   section explaining the envelope shape and giving one
   example per command group.
1. `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: list
   `--json` as a global rendering flag in the CLI command
   summary.

### Phase 6 — tests + smoke

1. `tests/test_cli.py` `TestJsonMode` class:
   - One test per command's success-envelope shape: parse
     `result.output` as JSON, assert `ok=True`, assert
     `command=<name>`, assert payload keys exist.
   - Filter-mismatch error envelope on `search`.
   - Port-unreachable envelope on `search --port`.
   - MCP-error passthrough envelope on `search --port` against
     a broken tool (existing fixture pattern).
   - `service_status` divergent state envelope (exit 4).
   - Stdout-purity check: result.output starts with `{` and
     ends with a single newline; no Rich box-drawing
     characters present.
1. Smoke: live service on port 18877, `vaultspec-rag status --json | jq` returns parseable JSON; `vaultspec-rag search "x" --type code --port 18877 --json | jq '.data.results | length'` returns an integer.

### Phase 7 — commit + push + PR + merge

Conventional-commit; PR links #112. Ignore Gemini per standing
instruction. Merge after CI green.

## Parallelization

Phase 1 (helpers) must land first. Phases 2-4 are independent —
they touch disjoint commands and can land in one commit. Phase 5
docs depend on the final flag shapes; do last. Phase 6 tests
need Phases 2-4 wired.

## Verification

- 209+ unit tests pass (baseline from #113 merge) plus new
  Phase 6 tests.
- 180+ integration tests pass (no integration changes
  expected; quick re-run as a sanity check).
- ruff + mdformat + vault check schema clean.
- Smoke walkthrough: every `--json` invocation pipes cleanly
  into `jq`; no Rich bytes leak; exit codes match table-mode.
