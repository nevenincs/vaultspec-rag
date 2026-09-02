---
tags:
  - '#adr'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-09-02'
body_hash: 'sha256:75b441bb4af67c597f9add10a47afd5ff9ac305a5ed7e4340c17e13bd5f00e6f'
related:
  - '[[2026-07-14-tool-env-gpu-continuity-research]]'
  - '[[2026-09-01-tool-mode-cuda-research]]'
  - '[[2026-09-01-tool-mode-cuda-reference]]'
---

# `tool-env-gpu-continuity` adr: `GPU-torch continuity across uv tool upgrades and env-aware start diagnostics` | (**status:** `accepted`)

## Problem Statement

A field report from a GPU (cu130) Windows box running v0.2.28 as a uv tool showed the
GPU contract is unmanaged across the tool lifecycle: every `uv tool upgrade` (or
`install --force`) re-resolves torch to the CPU PyPI wheel because the cu130 pin is
project-scoped and absent from published wheel metadata; the project-mode repair in
`vaultspec-rag install` cannot repair a tool env; and after a partially-failed forced
reinstall (the running service exe
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
  the installer must detect and refuse before it invokes the replacement.
- The repair scope and safety evidence are grounded in
  `2026-09-01-tool-mode-cuda-research` and
  `2026-09-01-tool-mode-cuda-reference`.

## Considered options

- **O-A1 (chosen) - canonical receipt-carrying direct CUDA wheel requirement.**
  Keep the existing ABI-aware `--with "torch @ <cu130 wheel>"` request as the
  durable tool input and verify the receipt semantically after installation.
- **O-A2 - index-only receipt configuration.** Rejected: uv receipt handling for
  index options has varied across releases, while a direct CUDA requirement does
  not depend on that serialization.
- **O-B1 (chosen) - exact-command remediation in the refusal itself.** The CPU-wheel
  refusal prints the immediate repair (`uv pip install --python "{interpreter}" --reinstall --torch-backend=cu130 torch`) plus the durable receipt fix (O-A1),
  env-classified; `vaultspec-rag install` stops being the advertised remediation on
  non-project envs.
- **O-B2 (chosen) - an active tool-mode repair in `install`.** Detect a defective
  persistent tool environment, obtain consent, refuse unsafe ownership evidence,
  run the receipt-carrying reinstall, and verify both wheel and receipt.
- **O-B3 - automatic service stop or a non-durable `uv pip` fallback.** Rejected:
  the installer must not terminate a service or report a temporary wheel change as a
  durable repair.
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
  gate: run the active self-reinstall with its service stopped and verify that the
  current CLI process does not itself prevent replacement. A failure remains explicit;
  it cannot fall back to `uv pip`.
- A live or unverifiable service holder blocks the repair before any `uv` child starts.
  Consent follows the existing default-no interactive and non-TTY installer contract.

## Implementation

**A - durable pin.** The CUDA tool request stays derived from the current canonical
command builder and tool-mode package declaration. Documentation and refusal surfaces
continue to render it, but the installer consumes a structured representation instead
of parsing rendered text.

**B - installer-owned repair.** Before workspace or project mutation, `install`
uses the existing torch-free probe and environment classifier. A broken persistent tool
environment asks for consent, obtains conservative service ownership evidence, invokes
the receipt-carrying uv reinstall only when safe, then verifies CUDA readiness and the
uv-owned receipt. It returns a structured, truthful action for every terminal branch.

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

Tests extend the existing classifier, probe, installer-report, and service-identity
homes with guards that prove unsafe and declined paths launch no uv process; success
proves both CUDA postcondition and a cu130 direct requirement in the receipt.

## Rationale

The receipt is the only mechanism that survives tool re-resolution. The earlier
emitted-command remedy was a useful intermediate surface but leaves a required
operator mutation and cannot prove receipt persistence.
`2026-09-01-tool-mode-cuda-research` shows that the installer can close that gap
without accepting the larger risks of automatic service control or a second
wheel-install path. The existing
classifier, isolated probe, and ownership detector keep the repair bounded and
testable. The ephemeral trap remains covered by a pure-path classifier because the
harmful case already fails the pre-flight - it is now eligible for repair only when it
is a persistent tool environment. The warming stamp is the
bounded fix to a real structural gap (F4): the daemon owns the transition because
only it knows when warmup starts and when serving begins, and sidecar rendering is
already how status reads daemon state. Jobs needs no envelope change - the report's
premise was partially wrong (F5) - so the fix is discoverability only.

## Consequences

- **Gains.** `uv tool upgrade` stops silently breaking GPU boxes once installed via
  the canonical command; installer repair can make an existing tool durable with
  affirmative consent; every refusal remains self-remediating with copy-paste commands;
  the uvx-ephemeral trap becomes a labelled, explained state; the warmup window
  reports `warming` instead of the contradictory "stopped"; scripted job waits have
  a signposted structured path.
- **Honest difficulties.** Users on plain `uv tool install` keep the old behaviour
  until they reinstall with the receipt-carrying form - the fix cannot retrofit
  existing receipts; the cu130 index as a global highest-priority index is blunt
  (acceptable because the pytorch index only serves torch adjacents, PyPI remains
  fallback); a new status state (`warming`, new exit code) is a minor contract
  change consumers must learn.
- **Pathways.** Extending repair evidence into `server doctor`; a `/health` warming
  phase if a later decision reorders the lifespan.
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
