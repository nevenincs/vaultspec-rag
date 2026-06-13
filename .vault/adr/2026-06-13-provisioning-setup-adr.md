---
tags:
  - '#adr'
  - '#provisioning-setup'
date: '2026-06-13'
modified: '2026-06-13'
related:
  - "[[2026-06-13-server-first-default-adr]]"
  - "[[2026-06-12-qdrant-server-provisioning-research]]"
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
---

# `provisioning-setup` adr: `unified dependency provisioning with server-first defaults` | (**status:** `accepted`)

## Problem Statement

The project provisions three external dependencies through three unrelated mechanisms
with three separate front doors and no single readiness command: CUDA torch wheels via
a consumer-pyproject patch plus a manual sync, Hugging Face models via lazy first-use
download or a warmup verb, and the Qdrant server binary via its own provisioning verb.
A user standing up the intended configuration - a GPU host serving a large codebase -
runs a multi-step dance across three subsystems and only discovers the server-binary
requirement when starting the server fails. With the sibling decision making server
mode the default backend, that discoverability gap becomes a default-path problem: the
assumed configuration now depends on a binary the primary setup flow does not mention.
This ADR consolidates provisioning behind one setup front door whose default is
server-first, adds a readiness command that reports what is and is not provisioned, and
preserves a first-class local-only path.

## Considerations

- The three dependencies are not homogeneous. Models and the Qdrant binary are
  fetch-and-go artifacts that live outside the Python environment. Torch is different
  in kind: provisioning it patches the consumer's dependency resolution and requires a
  follow-up sync, so it cannot be fetched in one shot. A unified front door therefore
  orchestrates heterogeneous steps and must report them honestly - a configured torch
  step that says "sync pending" reads differently from a downloaded binary that says
  "installed".
- With server mode now the default, the natural polarity of the setup flags inverts:
  provisioning happens by default and the user opts out, rather than opting in. A flat
  list of per-dependency skip flags is the simplest expression of that; a profile knob
  is the alternative if the flag list grows.
- The mirror of "set it up" is "tell me what is ready". The setup verb fixes
  provisioning; a readiness verb fixes discoverability - a user should learn what is
  missing before hitting a runtime failure, not after. The two are complementary and
  scoped together.
- The existing per-dependency provisioners are sound backends. The work is a unifying
  front door and a readiness reporter over them, not a rewrite of how each dependency
  is fetched.

## Constraints

- Reuse the existing provisioning backends rather than reimplementing them: the torch
  configurator, the model download/warmup path, and the Qdrant runtime provisioner
  stay the engines; this feature adds the front door and the readiness reporter.
- The distribution wheel stays pure-Python; provisioning remains a runtime concern.
  This feature changes when and how provisioning is triggered, never what ships in the
  wheel.
- Every provisioning step reuses the project's sync vocabulary
  (`created` / `updated` / `unchanged` / `skipped` / `failed`), is idempotent
  (re-running a satisfied dependency is an `unchanged` no-op with no network), and
  supports a dry-run preview, per the dry-run discipline for state-writing verbs.
- The Qdrant provisioning step inherits the verify-before-execute security contract
  already established: committed digest verified before extraction and re-verified
  before execution, HTTPS host-pinned download, no silent provisioning without the
  setup invocation or an explicit consent flag.
- `--local-only` must be honoured at every layer it appears (setup skips the binary;
  runtime selects the local store) and must be trivially discoverable, since the
  server-first default makes it the escape hatch for CI, offline, and small-project
  users.
- Depends on the supervised-server and server-first-default decisions, both accepted
  and exercised. The torch and model provisioning paths are pre-existing and stable.

## Implementation

A single setup front door provisions all external dependencies with a server-first
default, and a readiness verb reports provisioning state, both layered over the
existing per-dependency backends.

- Setup front door: the install / setup flow gains a unified provisioning behaviour
  that, by default, configures torch, ensures models, and provisions the Qdrant
  server binary - with explicit opt-outs. `--local-only` skips the server binary
  (the headline opt-out that also flips the runtime default to local); finer
  per-dependency skips exist for the cases where a user wants some but not all. Each
  step delegates to its existing backend and reports through the shared sync
  vocabulary; the heterogeneity is surfaced honestly (torch reports "configured, sync
  pending"; the binary reports "downloaded" or "unchanged").
- Readiness verb: a status / doctor-style command reports, per dependency, whether it
  is provisioned and usable - torch CUDA availability, model presence, and the Qdrant
  binary's resolution source and the supervised server's liveness - so a user learns
  what is missing before a runtime failure. It is a bounded, read-only operator view.
- Default polarity: provisioning is opt-out, matching the server-first default. The
  Qdrant step's consent model collapses into the setup default - invoking setup is the
  consent - while the air-gapped operator-binary path and the standalone Qdrant
  provisioning verb remain for users who want them.
- Documentation: the getting-started path becomes "install, run setup, you have a
  server-backed RAG over your codebase", with local-only as the documented minimal
  alternative.

## Rationale

The provisioning research mapped the three mechanisms and their asymmetries and
recommended consolidating the front door over the existing backends rather than
bundling or rewriting. The server-first-default decision makes that consolidation
urgent: once the assumed backend depends on the binary, leaving the binary out of the
primary setup flow turns a discoverability nuisance into a broken default path. A
single opt-out setup verb plus a readiness reporter closes both gaps - fragmentation
and discoverability - while the constraints preserve the wheel purity, the security
contract, and the first-class local-only path that make a server-first default safe.

## Consequences

- The intended configuration becomes a one-command setup with a clear readiness check,
  replacing the undocumented multi-subsystem dance.
- The heterogeneous torch step is the main source of friction: a unified verb that
  configures torch but cannot complete it (the sync is the user's to run) must
  communicate that boundary clearly or it will read as a half-failure. The honest
  per-step reporting is a hard requirement, not polish.
- The readiness verb adds a small, durable surface that future external dependencies
  can plug into - the consolidation pays forward as the dependency set grows.
- Opt-out polarity means a user on a constrained host who forgets `--local-only` will
  trigger a binary download they may not want; the dry-run preview and the loud,
  actionable nature of each step are the mitigations.
- Risk of scope creep: a "doctor" command can accrete unbounded diagnostics. It stays
  a bounded readiness report over the known dependency set, not a general health
  console.

## Codification candidates

- **Rule slug:** `provisioning-reuses-shared-vocabulary`.
  **Rule:** Every dependency-provisioning step routes through the shared setup front
  door, reports with the sync vocabulary (`created`/`updated`/`unchanged`/`skipped`/
  `failed`), is idempotent, and supports `--dry-run`; new external dependencies extend
  the front door and the readiness verb rather than adding a separate provisioning
  command.
