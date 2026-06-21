---
tags:
  - '#research'
  - '#service-first-search-fallback'
date: '2026-06-21'
modified: '2026-06-21'
related: []
---

# `service-first-search-fallback` research: `degraded-service search hang and silent local fallback (#202)`

Issue #202 reports that `vaultspec-rag search` can hang far past its own
`--timeout`, leave Python processes alive after the caller times out, and keep
the local store locked for follow-up searches. The reporter ran, from a uv venv
with the CLI prebuilt as a binary:

```
uv run --no-sync vaultspec-rag search "<q>" --type code --timeout 45 --limit 12 --port 8801 --allow-fallback
```

with the service already degraded (the MCP path was returning `Transport closed`). The `--timeout 45` call did not return inside a 90s budget; two Python
processes (one from the project venv, one from the uv runtime) stayed alive; the
local store stayed busy until those were killed by hand.

This document grounds the root cause in the code on `main` (verified unchanged
from the reporter's `v0.2.21`; the only post-`0.2.21` change to the search
transport was the import-light `serviceclient` re-export refactor, no
timeout-semantics change).

## Findings

### F1 — `--timeout` never reaches the local fallback (primary)

`handle_search` in `src/vaultspec_rag/cli/_search.py` plumbs `timeout` only into
the HTTP path (`_try_http_search`). When the service at `--port` is unreachable,
`_try_http_search` returns `None` (connection refused, see
`src/vaultspec_rag/serviceclient/_transport.py` `_is_connection_refused`), and
with `--allow-fallback` the handler drops through to `_try_in_process_search`,
which loads the full GPU model stack (Qwen3 + SPLADE + CrossEncoder) and opens
the local Qdrant store **with no deadline at all**. Once fallback engages,
`--timeout` is meaningless and the command runs unbounded. This is the headline
cause of "hangs past `--timeout`".

### F2 — Silent auto-fallback on port discovery (design defect)

When no `--port` is given, `handle_search` calls `_default_service_port()` and,
if a service is discovered, **forces `allow_fallback = True`**. So a bare
`vaultspec-rag search` against a *discovered-but-down* service silently degrades
to the unbounded local path with no operator mandate. Separately, when no
service is running at all, `port` stays `None`, the HTTP block is skipped, and
the handler runs the in-process search directly — again, silent local execution
with no explicit local mandate. Both contradict the project's intended posture:
service-first by default, local always an explicit opt-in.

### F3 — "Locked store" and "orphaned processes" are one fact

`VaultStore.__init__` (`src/vaultspec_rag/store.py`) acquires an OS file lock on
`exclusive.lock` and only releases it in `VaultStore.close()`, reached via the
CLI's `finally: get_registry().close_project(target)`. The OS lock is held for
exactly as long as the process is alive; it is auto-released when the process
dies. So the store was not "leaked locked" — it was held by the **still-alive
hung process**. The reporter fired a *second* search while the first was still
alive loading models; the second collided on the lock (or also hung), so both
processes stayed alive and a manual `Stop-Process` was required. The "two
processes" signature is the `uv run` launcher plus the real `vaultspec-rag.exe`
child; the in-process search path spawns no `ProcessPoolExecutor` (that is the
indexing path only).

### F4 — HTTP `--timeout` is a per-socket budget, not a wall-clock deadline

Even on the live-but-slow HTTP path, `urllib`'s `timeout` applies per socket
operation, and `_do_http_call` can issue up to two requests for one logical call
(initial request, then on a 401 a `/health` token probe plus a retry), each
carrying the full `timeout`. So a single search can spend ~2x`--timeout` before
returning, consistent with "`--timeout 45` did not return within 90s" even
without fallback. Secondary to F1/F2 but worth noting.

### F5 — No bounded teardown on interrupt (Windows constraints)

There is no signal handler, `atexit` teardown, or wall-clock guard around the
in-process search. On Windows the usual `signal.alarm`/`SIGALRM` deadline is
unavailable, and a Python thread running the search cannot be force-killed, so a
true bounded local run requires either a watchdog that releases the store lock
and force-exits the process, or running the local search in a child process the
parent can kill. The common degraded case (service down, models legitimately
take 30-60s to load) is interruptible by a watchdog; a native CUDA-call hang
holding the GIL is only interruptible by killing the process.

## Implications for the fix

- Local execution must require an explicit mandate (`--allow-fallback`, a
  dedicated local opt-in, or the configured local-only mode). The silent
  `allow_fallback = True` auto-enable and the bare-search silent local path must
  go: an unreachable/missing service with no mandate exits fast with a clear
  "service down" envelope and remediation.
- When local IS mandated, it must be bounded by a wall-clock deadline derived
  from `--timeout`, and on expiry must release the store lock and exit non-zero
  rather than hang.
- A regression harness must simulate a dead and a wedged service to assert the
  command returns within a bound and leaves no held lock.
