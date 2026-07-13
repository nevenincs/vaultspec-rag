---
tags:
  - '#audit'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
related:
  - '[[2026-07-13-preprocess-sandbox-adr]]'
  - '[[2026-07-13-preprocess-sandbox-plan]]'
  - '[[2026-07-13-preprocess-sandbox-research]]'
---

# `preprocess-sandbox` audit: `adversarial security review of the hook-containment boundary`

## Scope

Adversarial, hostile-hook-author review of the whole change set that makes the
RAG server run any repo's preprocess hooks safely by OS containment rather than
consent: the `HookSandbox` abstraction and the Windows AppContainer, Linux
bubblewrap, and macOS seatbelt backends; the runner staging and launch seam; the
tri-state control and trust-store removal; the three server-path defect fixes;
and the qdrant local delete-resurrect store fix folded in for green main.
Reviewed against the ADR decisions D1-D9 and the torch-discipline, storage-lock,
and worker-CPU rules. Priority order: sandbox escape, fail-open holes, torch
discipline, the qdrant fix, resource leaks, quality.

## Findings

### sandbox-escape | none | containment holds on every path

No filesystem or network escape was found. Zero capability SIDs deny network
including loopback; the process-thread handle-list restricts child inheritance
to the two pipe write ends despite the broad `bInheritHandles`; the read grant is
read+execute, not write; sibling and parent roots are never granted; the
staged-to-original path remap is a display-only string replace with no injection
surface. The real end-to-end containment test genuinely proves denial of an
out-of-stage secret read, a network connect, and secret-env inheritance, from
inside the child, with no mocks.

### job-teardown-broken | high | FIXED - the Job Object never tore down the tree

The AppContainer launch created a kill-on-close Job Object and assigned the
child, but returned without holding the job handle, so the handle was never
closed and `KILL_ON_JOB_CLOSE` never fired: a detached grandchild survived the
timeout, and one job kernel handle leaked per file. Containment still held
(grandchildren inherit the AppContainer token), so it was a teardown/leak
defect, not an escape. Fixed: the job handle is returned from `_assign_job`,
held on the launch handle, and closed in `cleanup`, triggering the teardown. A
new regression test proves a detached grandchild is reaped on cleanup.

### per-launch-recursive-acl | high | FIXED - icacls re-walked the whole tree per file

Every hook launch ran `icacls /T` over the scratch dir, the entire interpreter
prefix, the venv, and the whole project root - O(files x tree) ACL work
(minutes-to-hours on a large corpus), plus a persistent unrevoked ACE on every
file. Fixed: the static read paths (interpreter prefixes, project root) are
granted once per worker via an in-process cache; only the fresh per-launch
scratch dir is granted each time.

### fail-open-local-only-daemon | high | FIXED - server_mode misclassified a --local-only daemon

The fail-closed policy keyed on `server_mode = bool(cfg.qdrant_url)`, which is
"am I using a remote Qdrant," not "am I the resident non-interactive daemon." A
`server start --local-only` daemon has `qdrant_url` unset, so it was classified
local and - on a host with no sandbox backend - would run hooks unconfined:
exactly the C1 re-exposure the ADR exists to close. Fixed: a dedicated
`VAULTSPEC_RAG_SERVICE_DAEMON` marker is set in the daemon's environment at
spawn and read to derive `server_mode`, independent of the storage backend, so a
local-only daemon fail-closes correctly.

### breakaway-race | medium | FIXED - child ran before job assignment

The child was created running, not suspended, leaving a window in which a fast
child could spawn a breakaway grandchild before `AssignProcessToJobObject`.
Fixed: the child is created `CREATE_SUSPENDED`, assigned to the job, then
resumed.

### partial-failure-leaks | medium | FIXED - handles leaked on launch error paths

An exception during attribute-list construction or `CreateProcessW` leaked the
pipe handles and the attribute list; the stdout/stderr file objects were never
explicitly closed. Fixed: construction is wrapped in try/finally, the read ends
are closed on the failure path, and the pipes are closed in `cleanup`.

### dead-code | medium | FIXED

Removed unreferenced and partially-broken helpers (`cached_backend` and its
probe cache, a `staged_source` context manager that was a broken generator,
unused env deny-list constants, and an unused scratch-remove helper); the live
runner memoizes its own backend keyed on the real `(server_mode, unsandboxed)`
pair, which also moots the theoretical cache-poisoning concern.

### seatbelt-profile-injection | medium | FIXED - unescaped path in the macOS profile

The macOS seatbelt profile interpolated paths into `(subpath "...")` literals
without escaping, so a path containing a quote or paren could break out and
inject clauses. Fixed: a quote helper escapes backslashes and double quotes.
macOS-only, operator-controlled paths, so low real exposure.

### launch-post-create-leak | low | FIXED - handles leaked if pipe wrap failed after CreateProcessW

The re-review flagged that if wrapping the read pipes as file objects raised
after the child was created, the process, thread, job, and read-pipe handles
would leak because no handle object existed for ``cleanup`` to release. Fixed:
the post-create steps are guarded so a failure terminates the child and closes
every handle before re-raising. The attribute-list build was also extracted to a
helper that deletes its partial list on failure.

### pythonpath-docstring | low | FIXED

Corrected an inaccurate docstring claiming the `PYTHONPATH=project_root` grant
never shadows stdlib/site modules; it can, but the child is contained, so the
worst case is the project's own code running against its own tree.

### torch-discipline | none | clean

The sandbox modules, runner, config loader, and the `/reindex` pre-flight are
stdlib-only and torch-free; no torch reaches the service, MCP, or service-client
paths.

### qdrant-fix | none | correct

The local delete-resurrect workaround closes the collection's sqlite handle
before delete and asserts the on-disk directory is gone, both guarded by
`not self._server_mode`; server mode (a remote HTTP delete) is untouched, the
lifecycle-before-collection lock order is preserved, and a real regression test
proves a drop-then-recreate yields zero points.

## Recommendations

- Ship after the fixes: the initial review returned FAIL on three HIGH findings,
  all now fixed with tests; the re-review verdict is PASS with no CRITICAL/HIGH
  remaining and one further LOW residual fixed on top. No CRITICAL was ever
  present and no sandbox escape existed at any point.
- Promote the reframed `preprocess-config-is-code-execution` candidate once this
  holds a cycle: server-mode hooks now run only under a working OS sandbox or are
  refused (fail-closed), which the rule should assert.
- Windows remains the only host with a first-class backend proven end-to-end;
  Linux bubblewrap has a real backend and test, macOS seatbelt is implemented but
  unproven on a real host, and Linux Landlock is a documented fail-closed gap -
  worth a follow-up for hosts without bubblewrap.
