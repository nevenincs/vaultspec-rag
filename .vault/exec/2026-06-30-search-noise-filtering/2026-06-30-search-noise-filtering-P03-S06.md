---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S06'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Thread the domain filter and profile contract identically through the facade, service search route, CLI flags, and the MCP tool, rejecting domain filters for vault search, with parity tests

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Extend `validate_search_filters` with `exclude_domains`/`only_domains`/
  `include_domains` (code-only) and `InvalidDomainValueError` (subclasses the
  existing filter error so exit-2 handlers need no new wiring); flip
  `dedup_locales` to tri-state.
- Thread explicit domain params + tri-state dedup + a `notes` out-mapping
  through the `api` facade (`search_codebase` / `search_codebase_timed`).
- Server route reads the domain payload keys, collects `notes`, and adds a
  `filtered` field (per-domain drop counts) to the response envelope.
- Resolve the max-args ratchet the project already settled by routing CLI/HTTP
  domain filters as inline query tokens (`exclude:` / `only:` / `include:`,
  comma/repeat accumulating) parsed in `_parsing.py`; the searcher merges tokens
  with explicit kwargs. MCP keeps typed params and encodes them to tokens
  (`_with_domain_tokens`) so the transport signature is unchanged.
- Tests: token parsing, domain validation (+code-only), policy merge.

## Outcome

270 unit tests passed across search/cli/server/mcp/store/indexer; ruff and
basedpyright clean. One contract reaches every adapter: hide/only/include and
the dedup default behave identically in-process, over HTTP, via CLI, and via MCP.

## Notes

The `filtered` envelope field is surfaced on the service path; the inline-token
wire shape means domain filtering needed no new transport/CLI-flag surface,
matching the intent:/status: precedent that the max-args ratchet established.
