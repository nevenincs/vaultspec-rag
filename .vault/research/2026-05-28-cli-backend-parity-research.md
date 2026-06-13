---
tags:
  - '#research'
  - '#cli-backend-parity'
date: '2026-05-28'
modified: '2026-05-28'
related:
  - '[[2026-05-28-cli-search-filters-plan]]'
  - '[[2026-05-28-cli-search-filters-adr]]'
  - '[[2026-05-28-cli-search-filters-research]]'
---

# `cli-backend-parity` research: `cli vs mcp vs backend parity audit`

## Trigger

Issue #107 surfaced a single missing wire (code-search filters dropped on
`--port` fast path) but the underlying pattern is broader: the backend
exposes filter and safety capabilities that neither MCP nor CLI surface
uniformly. Issues #108, #110, and #111 add evidence. This research
captures the grounded audit so the bundle plan is built on verified
state rather than the issue text alone.

## Method

Three independent code-reading passes against
`feature/107-cli-search-filters` worktree:

- Pass A: filter pipeline - `search.py:parse_query`, `_search_*_encoded`,
  `store.py:_build_filter` / `_build_code_filter`, Qdrant payload index
  definitions in `ensure_table` / `ensure_code_table`.
- Pass B: safety surface - fallback points in `cli.py:handle_search` /
  `handle_index`, exception discrimination in `_try_mcp_*`, tqdm origin
  in `embeddings.py` / `search.py:CrossEncoder`, `service status` and
  `service projects list` port discovery, daemon-side service.json
  lifecycle.
- Pass C: blast radius - every `vaultspec-rag clean` call site across
  tests, docs, CI, rules; `--type` flag-name collision check in
  `handle_search`.

## Findings

### Filter pipeline (Pass A)

`parse_query` (`search.py:39`) recognizes nine canonical filter keys via
query-string tokens: `doc_type` (`type:`), `feature`, `date`, `tag`,
`language` (`lang:`), `path`, `function_name` (`func:`), `class_name`
(`class:`), `node_type` (`nodetype:`).

Each search method whitelists which keys it honors:

- `_search_vault_encoded` (`search.py:433`): `doc_type`, `feature`,
  `date`, `tag`. Others silently dropped.
- `_search_codebase_encoded` (`search.py:502`): `language`, `path`,
  `node_type`, `function_name`, `class_name`. Others silently dropped.

Qdrant payload-index coverage (`store.py:289`):

- Vault: `doc_type`, `feature`, `date`, `tags` - all KEYWORD.
- Codebase: `path`, `language`, `function_name`, `class_name` - all
  KEYWORD; `line_start` INTEGER.
- `node_type` is stored but not indexed. Filtering still works
  (linear scan in local mode) but a remote Qdrant deployment would pay
  a perf cost.

Filter type: all `MatchValue` exact-equality (`store.py:871-957`). No
glob, no prefix, no `MatchText`. `tag` uses `MatchAny([value])` to
search inside the `tags` array, still exact.

MCP exposure (`mcp_server.py:586-711`):

- `search_vault`: only `query`, `top_k`, `project_root`. Query-string
  tokens flow through transparently.
- `search_codebase`: adds `language`, `node_type`, `function_name`,
  `class_name` as explicit params. `path` is missing as an explicit
  param.

CLI exposure (`cli.py:1098`):

- `search` exposes only the four code filters as flags; vault filters
  are reachable only through query-string tokens; `--path` is missing
  entirely.
- The four code-filter flags are silently dropped on `--port` until
  PR #109 lands (issue #107).

### Safety surface (Pass B)

- Fallback to in-process on `--port` unreachable happens in
  `handle_search:1211` (search) and `handle_index:634` (index). Both
  acquire the Qdrant lock and load GPU models - exactly the contention
  pattern the lock-error UX warns against. There is no
  `--allow-fallback` gate today.
- `_try_mcp_search` (`cli.py:959`) and `_try_mcp_reindex`
  (`cli.py:802`) swallow every exception and return `None`. Connection
  refused and live-but-broken-tool look identical from the caller. The
  more careful `_try_mcp_admin` (`cli.py:864`) already discriminates
  ECONNREFUSED from other errors - the pattern to mirror.
- tqdm progress bars originate from `SentenceTransformer` and
  `SparseEncoder` constructors (`embeddings.py:238-278`) and from
  `CrossEncoder` (`search.py:312`). No `show_progress_bar=False`, no
  env-var gate. They pollute stdout during fallback.
- `_display_search_results` (`cli.py:1080`) renders the same table
  title regardless of path. `handle_index` already uses the
  `"Indexing Summary (via MCP)"` vs `"Indexing Summary"` title pattern;
  search should mirror it.
- `service service projects list` already reads `service.json` for a
  default port via `_default_service_port` (`cli.py:2024-2043`). It
  exits with "Service is not running" when no port resolves; the
  message could be clearer about whether `service.json` is missing vs
  unparsable.
- Silent service death: the daemon never unlinks `service.json` on
  crash. `service status` cleans up stale PIDs but cannot distinguish
  "intentional stop" from "process disappeared".

### Blast radius (Pass C)

- `clean` default change: only one test exercises a real invocation
  (`tests/test_cli.py:146`) and it already passes `"all"` explicitly.
  Zero documentation or CI invocations rely on the default. Making
  `clean_type` required is safe.
- `--type` flag-name collision: `handle_search` already owns `--type`
  as the search-source switch (`vault` | `code`). The new vault
  doc-type filter must be named `--doc-type` to avoid the conflict,
  which is also consistent with the existing `--node-type` naming.
- No other commands have a positional argument with a destructive
  default. `index --type all` is the only sibling default, and it is
  safe by virtue of `index all` being idempotent.

## Implication

The fix for the four open issues converges on one structured bundle:

1. Parity wires - expose every filter the backend already honors as
   both an MCP param and a CLI flag, so the documented surface matches
   the implemented surface.
1. Fail-hard `--port` fallback - flip the default and add an explicit
   opt-in, with exception discrimination so live-but-broken services
   are not silently relaned to in-process.
1. UX clarity - path indicator on search, tqdm to stderr, clean
   requires explicit target, sensible `--max-results` default, optional
   no-truncate.
1. Schema fix - add `node_type` payload index for completeness.

Design-heavy items (`--json` mode, daemon-side silent death detection,
status divergence cross-check, service.log crash entries, glob path
filtering for #108) are deferred to Wave 2 and tracked as follow-up
issues rather than implemented in this PR.
