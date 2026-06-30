---
tags:
  - '#adr'
  - '#cli-backend-parity'
date: '2026-05-28'
modified: '2026-06-30'
related:
  - '[[2026-05-28-cli-backend-parity-research]]'
  - '[[2026-05-28-cli-search-filters-adr]]'
---

# `cli-backend-parity` adr: `cli-mcp parity wires and fail-hard fast path` | (**status:** `accepted`)

## Problem Statement

The vaultspec-rag backend already honors a coherent set of search filters
and safety contracts; MCP exposes a subset of them; the CLI exposes a
smaller subset still; the README documents only the CLI's view. Issues
#107, #108, #110, and #111 are four symptoms of the same root pattern:
divergent surfaces across the layers. Consumers who read the docs cannot
discover what the backend can do, and the CLI's `--port` fast path
silently relanes to the unsafe in-process path when the resident service
is dead.

## Considerations

- The backend is authoritative; every filter it whitelists in
  `_search_*_encoded` should be reachable from MCP as an explicit
  parameter, from the CLI as a flag, and from the docs as a documented
  contract.
- Query-string filter tokens already work end-to-end through MCP, but
  they are an undocumented power-user feature and they bypass the
  CLI's flag-shape ergonomics. Flags are the primary surface for
  consumers; query-string tokens stay supported but secondary.
- The fast path was designed to be the safe path. Silent fallback
  defeats that design and was directly implicated in an 18-process
  Qdrant-lock pile-up earlier in the session.
- A single `--type` token already names the search-source switch in
  the `search` command; the vault doc-type filter cannot reuse it.

## Constraints

- Backwards compatibility: existing `search` invocations must keep
  working. `_try_mcp_search` must remain callable without filter
  kwargs.
- No backend schema changes that require a reindex. `node_type`
  payload-index addition can be lazy: `ensure_code_table` adds it on
  the next index attempt; existing collections continue to function
  via linear scan until then.
- Wave 1 must be shippable in a single PR. Design-heavy items
  (`--json`, daemon-side death detection, log crash entries, glob path
  filtering) are explicitly out of scope and tracked as Wave 2 issues.

## Implementation

Wave 1 implements four coupled patches:

- Parity wires. MCP `search_codebase` gains `path` as an explicit
  parameter. MCP `search_vault` gains `doc_type`, `feature`, `date`,
  and `tag` parameters. CLI `search` gains `--path` (code) and
  `--doc-type` / `--feature` / `--date` / `--tag` (vault, named to
  avoid the existing `--type` switch). `_try_mcp_search` forwards
  every new field; the in-process path applies the same usage guard.
- Fail-hard fast path. When `--port` is supplied and the service is
  unreachable, the CLI exits with the same numbered remediation the
  lock-error UX already shows, instead of silently relaning. An
  `--allow-fallback` opt-in restores the legacy behaviour for users
  who want it. `_try_mcp_search` and `_try_mcp_reindex` adopt the
  ECONNREFUSED-vs-other discrimination already used by
  `_try_mcp_admin`, so live-but-broken services surface a structured
  error instead of silent fallback.
- UX clarity. `_display_search_results` mirrors the
  `(via MCP)` / `(via in-process)` title suffix already in
  `handle_index`. Default tqdm progress bars are suppressed
  (`HF_HUB_DISABLE_PROGRESS_BARS=1` + `show_progress_bar=False` on
  constructors) and re-enabled by `--verbose`. `search --max-results`
  default rises from 5 to 10 (issue #110 polish). `--no-truncate`
  flag added to the search results table. `clean_type` becomes a
  required argument (#111).
- Schema completeness. `store.ensure_code_table` adds a
  `create_payload_index('node_type', KEYWORD)` call. The 307
  `/mcp` to `/mcp/` redirect is removed by adding a no-redirect
  trailing-slash route on the FastMCP / Starlette mount.

Docs (`README.md`, `src/vaultspec_rag/README.md`,
`.vaultspec/rules/vaultspec-rag.builtin.md`) document every flag,
filter, and safety contract Wave 1 ships. The query-string token
syntax is also documented as an alternate surface.

## Rationale

A single bundle is preferable to four separate PRs because the changes
share a contract (the CLI/MCP filter shape) and reviewing them together
keeps the surface coherent. Splitting would risk landing the parity
wires without the safety changes, leaving consumers with more flags but
the same silent-fallback hazard. Splitting would also force four
release-please bumps for what is logically one consumer-facing release.

Fail-hard by default is chosen over a deprecation warning because the
silent fallback is not just confusing; it is dangerous (the lock-error
UX warns against the exact behaviour the fallback performs). A clean
break with `--allow-fallback` for legacy callers is safer than a phased
deprecation.

Naming `--doc-type` over `--type` is forced by the existing `--type`
collision and is consistent with the present `--node-type` naming.

## Consequences

- Consumers who passed `--port` and relied on silent fallback get an
  explicit error and the remediation text. The `--allow-fallback` opt-in
  is the escape hatch.
- The MCP and CLI surfaces grow by nine fields total (one code filter
  on `search_codebase`, four vault filters on `search_vault`, and the
  four corresponding CLI flags). The growth is bounded by what the
  backend already supports; no new backend capabilities are introduced
  by Wave 1.
- The `clean` default change is a small documented behaviour change.
  Audit found zero call sites that rely on the previous default.
- Wave 2 remains free to add `--json`, watchdog, divergence-check, and
  glob-path-filter capabilities without touching the surfaces Wave 1
  ships.
