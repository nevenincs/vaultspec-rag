---
tags:
  - '#adr'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-serviceclient-admin-errors-research]]"
---

# `serviceclient-admin-errors` adr: `surface admin failures through the transport's structured error envelope` | (**status:** `accepted`)

## Problem Statement

The resident RAG service is reached through one import-light HTTP transport shared by the
CLI and the MCP server. Its *admin* helper, `_try_http_admin`, swallows an unexpected
(non-refused, non-timeout) exception into a bare empty dict `{}` after a debug log. On the
MCP surface this `{}` flows through `_unwrap` unchanged (only `None` raises there), so an
agent receives an empty admin payload indistinguishable from a genuinely-empty result; on
the CLI it renders as an empty table rather than an error. This was recorded as finding
**L-2** in the `2026-06-18-mcp-service-client-audit` (PR #195) and deferred because it is
pre-existing and shared by both surfaces. The research `2026-06-24-serviceclient-admin-errors-research`
established that the transport already carries a deliberate two-axis error contract that the
admin path violates in exactly one branch. This ADR decides how that branch should behave.
It is a contract-alignment decision on a mature, in-tree module - no new feature.

## Considerations

- The transport's contract has two intentional axes (research F1): **unreachable** →
  `None` (mapped on MCP to a single service-down `RuntimeError`), and **live but broken** →
  a structured `{"ok": False, "error": <code>, "message": <text>}` envelope. The defect is
  that admin honours the first axis but drops the second for its catch-all branch.
- The structured `http_call_failed` envelope is already the house style: `_try_http_search`
  and `_try_http_reindex` both return it for the same exception class (research F2). Admin is
  the lone outlier, and it already envelopes its own *timeout* case - only the final
  catch-all returns `{}` (research F3).
- The envelope is MCP-compatible without any change to `_unwrap`: a non-`None` dict passes
  through verbatim, so the agent sees a legible error instead of a false empty (research F4).
  One change at the shared layer corrects both surfaces.
- The no-swallow discipline's intent is legibility to the code that must react; a debug log
  on a value the consumer never sees does not meet it (research F5).

## Constraints

- No frontier or library risk: the transport is stdlib-only (`urllib`) and mature; this is a
  single-branch behavioural correction, not new surface.
- The two existing axes are load-bearing and must be preserved exactly: connection-refused
  must keep returning `None` (the service-down signal the MCP `_unwrap` and the CLI
  unreachable handling depend on), and the timeout branch must keep its `admin_timeout`
  envelope. Only the catch-all `{}` changes.
- No parent-feature dependency: the MCP service-client rework (PR #195) that shares this
  transport is landed and stable; this ADR refines a finding it deferred.
- The project's no-mock test mandate applies: the regression must be proven against a real
  in-process route that raises a non-refused, non-timeout error, not by patching transport
  internals.

## Implementation

High-level; a plan sequences it.

**D1 - Replace the catch-all swallow with the structured envelope (Option A).** In
`_try_http_admin`, the final `except` branch that currently returns `{}` after a debug log
returns instead `{"ok": False, "error": "http_call_failed", "message": "...<class>: <exc>"}`,
matching `_try_http_search` and `_try_http_reindex` verbatim in shape. The connection-refused
branch (`→ None`) and the timeout branch (`→ admin_timeout` envelope) are unchanged. The
debug log is retained alongside the envelope (legible *and* logged).

**D2 - Reuse the `http_call_failed` error code, not a new `admin_call_failed`.** The code is
a contract token shared with search and reindex; reusing it keeps a single "the call to the
live service failed unexpectedly" code across the transport. The `message` already names the
exception class and text, which is sufficient to tell admin failures apart in logs without a
distinct code. (Resolves research open question 1.)

**D3 - Leave a successful-but-null body as `{}`.** The `res if res is not None else {}`
normalisation for a successful call with a null body is a *legitimately* empty result, not a
swallowed error, and is correct today; it stays. Once D1 lands, `{}` unambiguously means
"the call succeeded with nothing to report" because the failure path no longer produces it.
No new empty-`ok=True` shape is introduced - it would add contract surface for no consumer
benefit. (Resolves research open question 2.)

**D4 - Prove it with a real-route regression.** A test drives an admin call against a real
in-process route that raises a non-refused, non-timeout error (e.g. a malformed/non-JSON
response that fails decoding) and asserts the returned value is the `ok=False`
`http_call_failed` envelope - distinguishable from both a real empty result (`{}`) and the
unreachable sentinel (`None`) - with no patching of transport internals.

## Rationale

Option A is the smallest change that restores the contract the rest of the transport already
honours, and it is the only option that keeps the two clean axes intact (research options
B/C rejected). Re-raising (B) would break the return-an-envelope contract and surface a raw
traceback to the MCP agent; returning `None` (C) would mislabel a live-but-broken admin call
as a down service and route operators to the wrong remediation. Reusing `http_call_failed`
(D2) and leaving the null-body `{}` (D3) both follow the same principle: minimise contract
tokens, and let D1 alone make `{}` unambiguous. The decision is grounded in research findings
F1-F6 and the originating audit finding L-2.

## Consequences

- Gains: an unexpected admin failure becomes legible on both CLI (renders as an error) and
  MCP (the agent sees `ok=False` instead of a false empty), with no change to `_unwrap` or
  the unreachable/timeout axes; the transport's three point-of-failure helpers (search,
  reindex, admin) now share one error contract.
- Costs and risks: any consumer that today treats an empty admin `{}` as "no error" must
  tolerate an `ok=False` envelope - but per research F4 the CLI and MCP admin paths already
  handle `ok=False` from search/reindex, so the envelope is not a new shape to them. Low risk.
- Pathways: with all three helpers enveloping uniformly, a later consolidation of the
  duplicated `http_call_failed` construction into one transport helper becomes a clean,
  separable refactor (out of scope here).

## Codification candidates

- **Rule slug:** `serviceclient-helpers-envelope-not-swallow`.
  **Rule:** Every shared service-client transport helper must surface a live-but-broken call
  as the structured `{"ok": False, "error": ..., "message": ...}` envelope (never a bare
  `{}` or a swallowed exception), reserving `None` exclusively for a refused/unreachable
  service, so both the CLI and MCP can distinguish a real empty result from a failure.

  *(Candidate only - per the codify discipline this is promoted to a rule after the
  constraint has held across at least one full execution cycle, not on first encounter.)*
