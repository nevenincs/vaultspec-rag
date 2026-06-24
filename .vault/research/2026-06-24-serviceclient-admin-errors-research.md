---
tags:
  - '#research'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
related: []
---



# `serviceclient-admin-errors` research: `swallowed admin errors in the shared service client`

The resident RAG service is reached through one import-light HTTP transport shared by both
the CLI and the MCP server. This research characterises a defect in that transport's
*admin* path: on an unexpected (non-refused, non-timeout) exception, `_try_http_admin`
returns a bare empty dict `{}`, collapsing a real failure into something the consumer
cannot distinguish from a legitimately-empty result. It was first recorded as finding
**L-2** in the `2026-06-18-mcp-service-client-audit` (PR #195) and deferred there because it
is pre-existing - factored verbatim from the prior CLI client during the MCP service-client
rework - and shared by both surfaces. This is the research phase for GitHub issue **#199**;
it weighs the contract options and feeds an ADR. No implementation is proposed here.

## Findings

### F1 - The transport already has a deliberate two-axis error contract

Every call funnels through `_do_http_call`, and the `_try_http_*` helpers discriminate two
distinct failure axes, by design:

- **Unreachable** (the service refused the connection between the port read and the call):
  the helper returns `None`. `_is_connection_refused` walks the exception chain to identify
  this case. On the MCP side, `None` is mapped by `_unwrap` to a single
  `RuntimeError` (the service-down message); a missing `service.json` maps to the same
  error. This is the "service is down" signal.
- **Live but broken** (the service answered, or failed in a way that is not a refusal): the
  helper returns a structured `{"ok": False, "error": <code>, "message": <text>}` envelope.
  This is the "service is up but this call failed" signal.

The contract is sound and intentional. The defect is that the admin path does not honour the
second axis for one branch.

### F2 - The admin path is the lone surface that swallows; search and reindex do not

The same unexpected-exception class is handled three different-looking ways across the
transport, and only admin loses the error:

- `_try_http_search`: on a non-refused, non-timeout exception returns
  `{"ok": False, "error": "http_call_failed", "message": "...<class>: <exc>"}`.
- `_try_http_reindex`: on a non-refused exception returns the same
  `{"ok": False, "error": "http_call_failed", "message": ...}` envelope.
- `_try_http_admin`: on a non-refused, non-timeout exception logs at debug with
  `exc_info=True` and **returns `{}`**.

So the structured `http_call_failed` envelope is already the established house style for
"live but broken"; admin is the outlier. The fix is to bring admin into line, not to invent
a new contract.

### F3 - The admin path already envelopes its *timeout* case - only the catch-all swallows

`_try_http_admin` is not uniformly lossy. It returns `None` on a refused connection (correct,
per F1) and returns a structured `{"ok": False, "error": "admin_timeout", "message": ...}`
envelope on a timeout. The bare `{}` is reached only by the final catch-all branch - every
*other* unexpected exception (a malformed response, a JSON decode error, an `OSError` that is
neither refusal nor timeout, an unexpected `urllib` error). The remediation surface is
therefore a single branch, and an envelope already exists one line above it to mirror.

### F4 - How the swallow manifests differently on each consumer

- **MCP:** tools delegate through `_unwrap`, which raises only when the result is `None`.
  A `{}` is not `None`, so `_unwrap({})` returns `{}` verbatim to the agent. The agent
  receives an empty admin payload that is indistinguishable from a real empty result (e.g.
  "no projects", "no watcher configured"). A genuine backend failure is silently presented
  as "nothing here". The structured envelope, by contrast, also passes through `_unwrap`
  unchanged (it is not `None`), so returning `{"ok": False, ...}` is fully compatible with
  the existing MCP path - the agent then sees a legible error instead of a false empty.
- **CLI:** the admin commands render the returned dict. An `ok=False` envelope is the
  CLI's established error-rendering contract (the search and reindex paths already produce
  it), so an enveloped admin error renders as an error rather than an empty table.

A single change at the transport layer therefore corrects both surfaces, because the layer
is now shared (the motivation for fixing it once, noted in the originating audit).

### F5 - No-swallow discipline: a debug-logged loss is still a loss

The project's no-swallow discipline requires that no `except` clause silently suppress an
error. The current branch *does* log (`logger.debug(..., exc_info=True)`), so it is not an
outright breach of the letter of the rule. But the loss is real at the contract boundary:
the caller - and on MCP, the agent - cannot tell a swallowed exception from an empty payload,
and a debug log is not visible in the returned value the consumer acts on. The discipline's
intent (a failure must be legible to the code that has to react to it) is not met.

### F6 - Adjacent, in-scope-to-note: the successful-but-null-body `{}`

Distinct from the swallow, `_try_http_admin` also maps a successful call whose body is `None`
to `{}` (the `res if res is not None else {}` normalisation). This is a *legitimately* empty
result, not a swallowed error, so it is correct today - but it shares the same `{}` value as
the bug, which is part of why the swallow is invisible. The ADR should decide whether a
null-body success deserves its own explicit shape (e.g. an empty-but-`ok=True` envelope) or
whether `{}` is an acceptable "nothing to report"; this is a smaller, separable question and
should not block the primary fix.

## Options weighed (for the ADR)

- **Option A - Structured `http_call_failed` envelope (recommended).** Replace the catch-all
  `{}` with `{"ok": False, "error": "http_call_failed", "message": "...<class>: <exc>"}`,
  exactly mirroring `_try_http_search` and `_try_http_reindex`. Pros: consistent with the
  existing house contract; legible on both CLI and MCP through the unchanged `_unwrap`;
  distinguishable from a real empty result; minimal surface (one branch). Cons: none of
  substance; it is the path the rest of the transport already takes.
- **Option B - Re-raise / propagate the exception.** Let the unexpected exception escape the
  helper. Rejected: it breaks the established return-an-envelope contract (search and reindex
  return envelopes, they do not raise), would surface a raw traceback to the MCP agent, and
  would conflate the helper's two clean axes (None vs envelope) with a third (raise).
- **Option C - Return `None` (treat as unreachable).** Rejected: `None` means "service is
  down" per F1, and on MCP it maps to the service-down `RuntimeError`. A live-but-broken
  admin call is not a down service; this would mislabel the failure and send operators to the
  wrong remediation.

## Open questions for the ADR

- Confirm the error code: reuse `http_call_failed` (consistency with search/reindex) versus a
  more specific `admin_call_failed`. Consistency argues for the shared code; specificity
  argues for telling admin failures apart in logs/telemetry.
- Decide F6: leave a null-body success as `{}` or give it an explicit empty-`ok=True` shape.
- Confirm the test shape that satisfies the no-mock mandate: a real in-process route that
  raises a non-refused, non-timeout error (e.g. a malformed-response/JSON-decode path)
  asserting the envelope is returned and is distinguishable from a real empty result - no
  patching of the transport internals.
