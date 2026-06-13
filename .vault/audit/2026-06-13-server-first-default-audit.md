---
tags:
  - '#audit'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
related:
  - '[[2026-06-13-server-first-default-plan]]'
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-06-13-provisioning-setup-adr]]'
---

# `server-first-default` audit: `server-first operator persona validation`

## Scope

Manual operator-persona validation of the server-first reframe against the real
command surface, run as the named operator on the live development host (RTX 4080
SUPER, a resident service already serving the large corpus in server mode). The
validation exercises the readiness verb, the install provisioning surface, and the
`server start` backend selection in both human and JSON modes, per the
`cli-operability-needs-persona-tests` rule that requires CLI operability changes to
end with a real persona pass.

## Findings

### PASS - readiness verb renders coherently in both modes

`vaultspec-rag server doctor` reports `Backend: server`, `Readiness: ready for requests`, and one bounded line per dependency: torch ready (CUDA on the RTX 4080
SUPER), models ready (all three repos cached), qdrant ready (binary resolves from
`provisioned`). `server doctor --json` emits a single well-formed envelope
(`{"ok": true, "command": "server doctor", "data": {...}}`) whose `data` is the same
bounded three-dimension snapshot with per-dimension `info`. The operator gets an
immediate, truthful answer to "is this host ready to serve?" without reading logs.

### PASS - server-first defaults are legible at the help surface

`server start --help` leads with "Defaults to the managed Qdrant server backend
(server mode); pass --local-only for the on-disk store", and the `--qdrant` option is
honestly reframed as redundant. `install --help` states that install "also provisions
the external dependencies the server-first default" needs, and exposes `--local-only`,
the finer `--skip-torch/--skip-models/--skip-qdrant`, and `--no-provision`. An operator
reading help alone learns the default is server mode and the opt-out is one flag.

### PASS - provisioning preview is honest and heterogeneous

`install --local-only --dry-run` previews without writing: "Provisioning: mixed",
PyTorch `skipped (torch configuration opted out)`, Models `already present`, Qdrant
binary `skipped (--local-only selected; using the on-disk store, no binary)`. The
sync vocabulary is used per step and the local-only opt-out correctly skips only the
binary while reporting the rest, matching the provisioning-setup decision.

### LOW - readiness qdrant runtime liveness is null when read from a CLI process

In `server doctor --json` the qdrant `info.runtime` shows `mode: local`, `alive: null`, `pid: null` even while `server_mode: true` and the binary source is
`provisioned`. This is expected: the readiness reporter runs in the short-lived CLI
process, which is not the daemon and therefore cannot observe the supervised server's
live pid/liveness; it truthfully reports config + binary resolution and leaves live
liveness undetermined rather than guessing. Worth a one-line doc note so an operator
does not read `alive: null` as "server down".

## Recommendations

- Accept the readiness verb and provisioning surface as shipped; the operator story is
  coherent and the defaults are discoverable from help alone.
- Add a short doc sentence clarifying that `server doctor` run from the CLI reports
  binary resolution and config, while live supervised-server liveness is observable
  from the daemon's own state surfaces (`server status` / `server info`). Track under
  the docs reframe rather than blocking.

## Codification candidates

None. The server-first defaults, the `--local-only` first-class opt-out, and the
provisioning-vocabulary discipline are already captured by the two ADRs' codification
candidates (`server-mode-is-the-default-backend`, `provisioning-reuses-shared-vocabulary`)
authored during the decision phase; this validation confirms them rather than surfacing
a new durable cross-session constraint.
