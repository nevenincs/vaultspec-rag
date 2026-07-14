---
tags:
  - '#adr'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-research]]"
---

# `tool-env-gpu-continuity` adr: `GPU-torch continuity across uv tool upgrades and env-aware start diagnostics` | (**status:** `accepted`)

## Problem Statement

A field report from a GPU (cu130) Windows box running v0.2.28 as a uv tool showed the
GPU contract is unmanaged across the tool lifecycle: every `uv tool upgrade` (or
`install --force`) re-resolves torch to the CPU PyPI wheel because the cu130 pin is
project-scoped and absent from published wheel metadata; the CPU-wheel refusal's
remediation (`vaultspec-rag install`) cannot repair a tool env and only re-prints the
escape hatch; and after a partially-failed forced reinstall (the running service exe
locks `Scripts\`), `uvx` silently runs a cached ephemeral CPU env (`archive-v0`) with
nothing indicating the interpreter is not the installed tool. Two adjacent UX gaps:
`server status` reports "stopped" during model warmup while `server start` reports
"a service already owns this machine" (no warming state), and `server jobs`' human
summary always contains the word "active", trapping scripted greps (its `--json`
already exists but is underdiscoverable). Grounded in
`2026-07-14-tool-env-gpu-continuity-research` (R1/R2/UX-a/UX-b, U1-U6, F1-F6).

## Considerations

- uv facts (research U1-U5): tool receipts record `--index`/`--with` options and
  `uv tool upgrade` re-applies them - the only durable pin vector; `--torch-backend`
  is `uv pip`-only; uv has no post-install hooks; the uvx ephemeral env is silently
  chosen when the installed env is broken and is positively identifiable by
  `archive-v0` in `sys.prefix`.
- In-repo facts (research F1-F5): the start pre-flight already resolves and prints
  the daemon interpreter; `_running_in_uv_tool_env()` exists but no uvx-ephemeral
  classifier; the warming gap is the lifespan ordering (machine lock acquired before
  warmup, uvicorn serves after); `server jobs --json` exists and the `/jobs` route
  owns the data.
- Binding decisions: `torch-loads-through-centralized-gpu-gate` (installer probes the
  real wheel; remediation must be loud and exact); the torch-dependency-group ADR
  (project-surface pins; explains why wheels cannot carry the pin);
  `service-domain-owns-operability` (status semantics live in the service domain);
  `broker-facing-cli-outcomes-are-structured-and-idempotent` (lifecycle envelopes);
  `operator-views-are-bounded` (jobs rendering).
- The service cannot intercept `uv tool install --force` while running (no uv hook);
  the achievable surface is detection, exact-command remediation, and documentation.

## Considered options

- **O-A1 (chosen) - canonical receipt-carrying install command via `--index`.**
  Document and emit `uv tool install "vaultspec-rag[mcp]" --index https://download.pytorch.org/whl/cu130` as the canonical tool install; the receipt
  re-applies it on every upgrade and the torch version floats with the release.
- **O-A2 - `--with` direct-URL wheel pin as canonical.** Rejected as primary: it
  hard-pins torch version, python ABI, and platform, going stale on every torch or
  python bump; kept as the documented fallback because it sidesteps the Windows
  pytorch `--index` breakage (uv issue 11532) if that surfaces on `uv tool`.
- **O-B1 (chosen) - exact-command remediation in the refusal itself.** The CPU-wheel
  refusal prints the immediate repair (`uv pip install --python "{interpreter}" --reinstall --torch-backend=cu130 torch`) plus the durable receipt fix (O-A1),
  env-classified; `vaultspec-rag install` stops being the advertised remediation on
  non-project envs.
- **O-B2 - an active `install --repair-env` that runs the escape hatch.** Deferred:
  mutating an arbitrary resolved interpreter is a new failure surface; exact-command
  emission removes the reported friction without it. Pathway left open.
- **O-C1 (chosen) - runtime env classifier + loud ephemeral warning.** Classify the
  daemon interpreter (installed-tool / uvx-ephemeral / project-venv / other) from
  `sys.prefix` path shape; `server start` and the refusal warn loudly on
  uvx-ephemeral, naming the installed-tool path and that a locked forced reinstall
  means the running service must be stopped first.
- **O-C2 - refuse to start from an ephemeral env.** Rejected: uvx-without-install is
  a legitimate flow; a healthy ephemeral env that passes the CUDA pre-flight may run.
  The warning plus the pre-flight refusal (when CPU-only) covers the harmful case.
- **O-D1 (chosen) - `warming` phase stamped in the status sidecar by the daemon.**
  The daemon lifespan stamps `warming` after machine-lock acquisition and before
  component warmup, and `running` when uvicorn begins serving; `server status`
  renders lock-held + sidecar-warming as a distinct `warming` state with its own
  exit code instead of "stopped".
- **O-D2 - serve HTTP before warmup and report warming via `/health`.** Rejected for
  now: reorders the lifespan around readiness semantics every consumer relies on
  (health-ready currently implies models loaded); far larger blast radius than the
  sidecar stamp.
- **O-E1 (chosen) - jobs discoverability, envelope kept.** `server jobs --json`
  already emits the `{ok, command, data}` envelope; add `--json` signposting to the
  human summary/help so script authors stop grepping "active". No new status field -
  jobs is a read verb, not a lifecycle verb.

## Constraints

- The cu130 index URL and the torch floor already live in the workspace pin; the
  emitted/ documented command strings must be derived from one constant surface so a
  CUDA bump updates them together (no scattered literals).
- Env classification must be pure path logic on `sys.prefix`/`UV_TOOL_DIR`/
  `UV_CACHE_DIR` shapes - no `uv` subprocess on the start path - and must live where
  service call paths can reach it without importing torch
  (`torch-loads-through-centralized-gpu-gate`).
- The sidecar `warming` stamp is written by the daemon process only; the CLI parent
  keeps writing the spawn record. Status rendering must treat an absent phase field
  as today's semantics (older daemons, back-compat).
- The warming state must not weaken the machine-singleton contract: "already owns
  this machine" remains correct during warmup; the fix is that status agrees.
- Storage-maintenance lifecycle-inertness and the stop/start envelope contracts are
  untouched; `uv tool` behaviour (receipt re-application) is external and pinned by
  research U1 - if a future uv changes receipt semantics the documented command
  degrades to today's behaviour, never worse.
- Verification of O-A1 on real Windows (uv issue 11532 risk) is an execution-phase
  gate: if `--index` misresolves on `uv tool`, the documented canonical form flips
  to the O-A2 fallback before release.

## Implementation

**A - durable pin.** README/install docs make the receipt-carrying command the
canonical tool install; `warn_if_active_torch_not_gpu()` and the start refusal emit
it as the "make upgrades safe" line. Command strings derive from one helper next to
the existing cu130 constants.

**B - single-step remediation.** `_preflight_daemon_cuda`'s failure text drops the
`vaultspec-rag install` indirection for non-project envs and prints, for the resolved
interpreter: the immediate escape hatch, then the durable receipt fix, selected by
the env classification.

**C - env classifier.** A small pure function (beside `_running_in_uv_tool_env()`)
returns installed-tool / uvx-ephemeral / project-venv / other for a given prefix or
interpreter path; `server start` logs/prints a prominent warning on uvx-ephemeral
(including the "stop the service before forced reinstall - the Scripts lock is the
running service" guidance) and the refusal includes the classification label beside
the interpreter path.

**D - warming state.** The daemon lifespan stamps phase transitions
(`warming` -> `running`) into the service status sidecar; `_explicit_port_state` and
the port-only renderer gain a `warming` branch (pid, since, distinct exit code);
`server start`'s already-owns message says "warming" when the sidecar says so.
`/health` semantics unchanged.

**E - jobs signposting.** The human jobs summary/help mentions `--json`; envelope
shape unchanged.

Tests extend the no-mock homes named in research F6 (env pre-flight, status states,
lifespan-lock ordering, jobs unit, install torch-config), plus a manual persona pass
on the real GPU box per `manual-cli-persona-required`.

## Rationale

The receipt (U1) is the only mechanism uv offers that survives re-resolution, so the
durable fix is necessarily a documented/emitted install spec, not code (U4). Given
that, the highest-leverage code change is making every failure surface print the
exact two commands - repair now, survive upgrades - for the actual interpreter, which
the pre-flight already resolves (F1). The ephemeral trap (R2) is fully covered by a
pure-path classifier (U5, F3) because the harmful case (CPU ephemeral env) already
fails the pre-flight - it just fails illegibly today. The warming stamp is the
bounded fix to a real structural gap (F4): the daemon owns the transition because
only it knows when warmup starts and when serving begins, and sidecar rendering is
already how status reads daemon state. Jobs needs no envelope change - the report's
premise was partially wrong (F5) - so the fix is discoverability only.

## Consequences

- **Gains.** `uv tool upgrade` stops silently breaking GPU boxes once installed via
  the canonical command; every refusal is self-remediating with copy-paste commands;
  the uvx-ephemeral trap becomes a labelled, explained state; the warmup window
  reports `warming` instead of the contradictory "stopped"; scripted job waits have
  a signposted structured path.
- **Honest difficulties.** Users on plain `uv tool install` keep the old behaviour
  until they reinstall with the receipt-carrying form - the fix cannot retrofit
  existing receipts; the cu130 index as a global highest-priority index is blunt
  (acceptable because the pytorch index only serves torch adjacents, PyPI remains
  fallback); a new status state (`warming`, new exit code) is a minor contract
  change consumers must learn.
- **Pathways.** An active `install --repair-env` (O-B2) over the same classifier;
  extending the classifier into `server doctor`; a `/health` warming phase if a
  later decision reorders the lifespan.
- **Pitfalls.** Scattering the cu130 URL across message literals (must stay
  derived); classifying by substring on forward slashes only (Windows paths);
  stamping `warming` from the CLI parent (races the daemon); treating absent phase
  as warming (breaks older daemons).

## Codification candidates

- **Rule slug:** `gpu-remediation-prints-exact-commands`.
  **Rule:** Any surface that refuses work because the active interpreter's torch is
  CPU-only or absent must print copy-paste remediation for the *resolved* interpreter
  and environment kind - the immediate repair and the durable re-install form - never
  a pointer at another command that cannot repair that environment.

  *(Candidate only - promoted after the constraint has held across at least one full
  execution cycle, per the codify discipline.)*
