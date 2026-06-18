---
tags:
  - '#audit'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
  - "[[2026-06-18-mcp-service-client-adr]]"
---

# `mcp-service-client` audit: `MCP service-client rework code review`

## Scope

The mandated terminal review (plan step P06.S21) of the MCP service-client rework on
branch `feature/mcp-service-client-rework` (PR #195, issue #194), auditing the full
feature diff against `main` across the five implementation commits (P01 lazy package
init + import-light `serviceclient` package; P02 MCP tools rewritten as thin
delegations; P03 daemon mount and stdio model-load removed; P04 dead/phantom artifacts
removed; P05 mock-free regression guards). The audit verified the seven ADR decisions
and their invariants: thin client (no Torch/models, no `cli`/`api`/`store` import), no
local fallback, no locks/local resource, stdio as the sole MCP transport, no bespoke MCP
logic, a lazy package init preserving the public API, and delegation correctness.

## Findings

Mechanical gates at review time: `ruff` clean; `basedpyright` 0 errors on
`mcp`/`serviceclient`/`server`; the runtime import-isolation probe returned an empty set
(no `torch`/`sentence_transformers`/`qdrant_client`/`cli`/`api`/`store`/`embeddings`/
`indexer` after importing the MCP package); the new mock-free guards and the server,
conflation, and ADR-regression suites green.

Verdict: **PASS-WITH-FOLLOWUPS**. No CRITICAL or HIGH findings. The rework delivers the
ADR's intent: a genuine thin stdio client with verified import isolation, a single
no-local-fallback chokepoint, and the daemon's REST plus eager-model path preserved.

- **MEDIUM (M-1) - resolved.** The `server/_routes.py` module docstring still described
  the pre-split reality (routes registered "alongside `Mount("/mcp")`", "all control
  stays on MCP"), the exact stale-documentation class that decision D6 set out to remove;
  P04 corrected the sibling server docstrings but missed this one. Fixed in this review:
  the docstring now describes REST-only registration reached by the stdio client through
  the service-client.

- **MEDIUM (M-2) - resolved.** The admin route table in `serviceclient/_transport.py`
  retained a dead `get_index_status` to `/status` entry; the daemon has no `/status`
  route and no live caller used the key (the `get_index_status` tool correctly delegates
  to the service-state route), so it was a phantom-route artifact of the class D6
  targeted. Fixed in this review: the dead entry was deleted. Confirmed no test bound the
  route-map entry.

- **LOW (L-1) - accepted.** The stdio branch wires a registry close callback and a
  watcher-stop in its `finally`; because the stdio client populates no registry these are
  defensive no-ops rather than a contract violation, and a live test asserts the wiring.
  Left in place as harmless defensive cleanup.

- **LOW (L-2) - deferred to a follow-up.** The shared admin client returns an empty dict
  on an unexpected (non-refused, non-timeout) exception, which the MCP unwrap path does
  not surface as an error. This is pre-existing behavior factored verbatim from the prior
  CLI client (not introduced by this rework) and is debug-logged, so it does not breach
  the no-swallow discipline outright, but the MCP now inherits the silent-empty path.
  Tracked as a follow-up rather than fixed on this branch.

- **LOW (L-3) - accepted.** The FastMCP instance keeps `stateless_http=True`, inert on
  stdio. The ADR reserves a Streamable-HTTP endpoint as a deliberate future opt-in and a
  live test asserts the setting, so it is retained as reserved configuration rather than
  removed.

- **NIT.** The runtime no-load assertions forbid only the five heavy ML libraries while
  the static AST guard additionally forbids `cli`/`api`/`store`; the ML-lib proof is the
  load-bearing one, so the asymmetry is acceptable. Ecosystem-test documented-surface
  assertions were narrowed to match the actual shipped rule text.

## Recommendations

- M-1 and M-2 are resolved in this review and ship on the branch. L-1 and L-3 are
  accepted as-is with rationale above. L-2 should be filed as a follow-up issue against
  the shared service-client's admin error handling (surface unexpected admin errors
  rather than returning an empty dict) and addressed outside this feature, since it is
  pre-existing and shared with the CLI.
- No CRITICAL or HIGH findings block the merge. With the two MEDIUM fixes applied, the
  feature meets the ADR's invariants and is ready to leave draft pending the full GPU
  integration run (plan step P06.S20).

## Codification candidates

The ADR already names two codification candidates for the eventual codify phase
(`mcp-is-a-thin-service-client` and `interface-layers-share-one-client`); this review
surfaces no additional durable cross-session constraint beyond those. The two MEDIUM
findings were instances of pre-existing debt cleaned up under decision D6, not new
recurring patterns, so they do not themselves warrant a rule.
