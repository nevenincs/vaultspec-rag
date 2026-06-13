---
tags:
  - '#adr'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-09'
related:
  - "[[2026-06-09-operability-hardening-research]]"
---

# `operability-hardening` adr: `targeted service, runtime, and UX hardening` | (**status:** `accepted`)

## Problem Statement

After the MCP/RAG-service deconflation landed on `main`, empirical service validation plus
three code-grounded research passes surfaced ten open issues that block reliable operation
of the resident RAG service — most acutely on Windows. They fall in three clusters: service
lifecycle/management (#181, #166), runtime/environment/compatibility (#176, #177, #178,
#180), and CLI UX + documentation (#169, #170, #171, #172). The pivotal finding: the
service-management cluster — previously deferred as an architectural redesign — decomposes
into targeted, localized fixes that do not touch the GPU pipeline, search path, embedding
stack, or indexer worker model. This ADR commits to hardening the service through bounded
fixes plus two documentation/test efforts, rather than a from-scratch redesign.

## Considerations

- **Windows-first runtime.** Job Objects, detached spawning, and exclusive file locks on
  the local Qdrant store dominate the failure modes.
- **Pinned Python 3.13 (uv-managed).** A system Python 3.14 breaks `qdrant-client` via the
  `protobuf` C-extension metaclass restriction; the daemon must run under the project venv.
- **GPU-only, no fallback model.** There is no CPU or sparse-only mode, so a required model
  being inaccessible (gated/missing) must fail fast with remediation, never degrade.
- **Existing project rules apply:** single dedicated GPU consumer thread; index workers stay
  CPU-only; no mocks/skips in tests; destructive verbs preview before applying.
- **#169 is a breaking CLI restructure** (flatten `server service <cmd>` to `server <cmd>`),
  touching the shipped builtin rule documentation and the CLI tests.
- **Library grounding (Context7):** `huggingface_hub` exposes gated-repo detection
  (`auth_check` / `model_info`, `GatedRepoError`) gated on a token (`HF_TOKEN`); Typer
  supports explicit `help=` on commands and `rich_help_panel` option grouping, overriding
  docstrings.

## Constraints

- Fixes must remain peripheral to the GPU/search/indexer core (research confirms each root
  cause lives in `cli/`, `server/`, `embeddings.py`, `jobs.py`, or `store.py` drop paths).
- `CREATE_BREAKAWAY_FROM_JOB` requires the launching Job Object to permit breakaway
  (default on interactive Windows shells); restricted CI job objects may deny it, requiring
  a graceful fallback to today's behaviour.
- Gated-model preflight adds a network round-trip; it must be cheap/optional and must not
  block startup when access is already granted.
- The CLI flatten (#169) must preserve the genuine `server mcp` protocol-adapter group and
  keep the deconflation invariants (no "MCP server" wording for the daemon) intact.

## Implementation

**Runtime correctness (foundational).** Spawn the daemon with the project's venv
interpreter resolved from the venv scripts directory (falling back to the current
interpreter only when no venv is detected), removing the system-Python-3.14 path that
triggers the `protobuf` metaclass crash; add a defensive interpreter-version guard in the
dependency check that raises an actionable error rather than an opaque metaclass traceback.
Wrap gated-model construction so an inaccessible model raises a clear fatal error carrying
the `HF_TOKEN` / login / model-URL remediation, with an optional cheap preflight
accessibility check. Make the in-process background reindex idempotently ensure the
embedding model is loaded before it leases a slot.

**Service hardening.** Make lifecycle verbs truthful and observable: non-zero exit when a
start is blocked by an occupied port; an orphan-detection path that, when `service.json` is
absent, probes the port and reports a distinct divergent state plus the port for manual
reclaim; persistence of the service token into `service.json` during the start health-poll
so auto-delegation no longer races into a 401; conversion of a missing required
`project_root` into a 400 with a clear message instead of an unhandled 500; detaching the
spawned daemon from the launching Windows Job Object so shell exit no longer orphans the
process and its Qdrant lock; and removal of the redundant O(N) pre-delete before dropping a
collection.

**CLI UX & documentation.** Flatten the command tree so daemon lifecycle verbs live directly
under `server` (preserving `server mcp`), updating the shipped builtin rule documentation
and CLI tests. Move user-facing text into explicit Typer `help=` strings with
`rich_help_panel` groupings and strip developer `Args:`/`Raises:`/`ctx` sections from
command docstrings. Author a grounded indexing/retrieval architecture guide and
cross-reference it from the relevant `--help`. Add no-mock operator-persona testimonial
integration tests exercising the cleaned CLI end-to-end.

**Verification.** Re-run the empirical service validation to confirm the #181 divergences
are resolved, run a formal code review, then reconcile and close the addressed issues.

## Rationale

Research ground each item to a `file:line` root cause and demonstrated the service cluster
is bounded, not architectural. The venv-interpreter spawn is the single root cause behind
both #177 and #178/#179, so fixing it foundationally collapses three issues. Fatal-with-
remediation for model access is the only honest behaviour given the GPU-only, no-fallback
stance. Truthful exit codes, orphan detection, the Job-Object breakaway, and token
persistence map one-to-one onto the divergences observed during the prior empirical
validation. Typer's explicit-help and HF Hub's gated-detection APIs (Context7-verified)
make the UX and model-access fixes idiomatic rather than bespoke.

## Consequences

- **Gains:** the resident service starts, serves, and is observable/vacatable reliably on
  Windows; the CLI is flatter and its help is clean; the indexing architecture is
  documented; regressions are guarded by re-validation and persona tests.
- **Difficulties:** #169 moves commands — a breaking change requiring builtin-doc and test
  updates plus a migration note. `CREATE_BREAKAWAY_FROM_JOB` may be denied in restricted CI,
  where the fallback retains current behaviour (no regression, no improvement there).
- **Pitfalls:** port-probe orphan detection surfaces the port for manual reclaim but does
  not itself kill the PID (full daemon-ownership/registry lifecycle remains a larger future
  effort, intentionally out of scope here).

## Codification candidates

- **Rule slug:** `daemon-spawns-with-venv-interpreter`.
  **Rule:** the resident daemon must be spawned with the project's venv interpreter, never
  the ambient `sys.executable`, so it cannot inherit an incompatible system Python.

- **Rule slug:** `gpu-model-access-fatal-with-remediation`.
  **Rule:** when a required GPU model is inaccessible (gated or missing), fail fast with a
  remediation message (token + URL); never crash silently and never silently degrade.

- **Rule slug:** `lifecycle-verbs-truthful-exit`.
  **Rule:** service lifecycle verbs must return accurate exit codes — non-zero on a blocked
  or failed start, and a distinct code for an orphaned/divergent daemon state.
