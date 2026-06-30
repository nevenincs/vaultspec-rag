---
tags:
  - '#audit'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# `rag-broker-affordances` audit: `code review verification`

## Scope

Verify-phase review of the `rag-broker-affordances` feature: the `server start` reorder
and `--json` contract (`_service_lifecycle.py`), the machine-global discovery pointer
(`_machine_lock.py` + the daemon `server/_lifecycle.py` write/cleanup), and the tests. The
review focused on the load-bearing safety property of the reorder (the idempotent
early-return must not let a second daemon spawn or mask a genuine conflict), the
one-envelope-per-exit-path `--json` contract, the pointer's crash-safety and
discovery-only role, and test isolation. Verdict: ship.

## Findings

- **Reorder correctness: PASS (the singleton invariant holds).** `_existing_service_running`
  returns a non-None `(pid, port)` only when identity (token via `/health`) AND health are
  confirmed, so the `already_running` early-return fires only for a healthy service we own;
  a foreign port holder still falls through to `port_in_use` and a different config to
  `machine_owned`. Critically, the machine-lock guard was NOT removed by the reorder, so the
  OS lock remains the authoritative backstop - no path lets a second daemon spawn.
- **`--json` contract: PASS.** Every one of the nine terminal outcomes emits exactly one
  `_emit_json` envelope (each `_fail_start` is raised, never fall-through); the qdrant
  install-success message is suppressed in json mode (non-terminal); the spinner is a
  nullcontext in json mode and `_emit_json` bypasses Rich, so stdout carries one clean
  document. The human output is byte-unchanged.
- **Pointer: PASS.** Atomic `.tmp`+`os.replace`, best-effort (a write failure never breaks
  the heartbeat; the STATUS_DIR file is written first), cleaned on shutdown, tolerant reader
  (absent/garbage/non-object -> None), discovery-only (the lock stays authoritative), path
  beside the lock and distinct from the STATUS_DIR file.
- **Tests/isolation: PASS.** Real-file, no-mock tests with managed-singleton isolation and
  lock release; the two `test_cli.py` fixes correctly isolate STATUS_DIR.
- **Medium (addressed): new code comments cited ADR/issue identifiers**, against the
  `no-dev-metadata-in-code` rule (the surrounding files are saturated with the pattern, so
  it matched file-local convention, but the rule is explicit).
- **Low/Nit (one addressed): `read_machine_discovery` resolved the path outside its `try`**
  (a config-resolution failure could in principle propagate despite the "never raises"
  docstring). The deliberate port-mismatch idempotency (`start --port X` while our service
  runs on Y returns `already_running(Y)`) is acknowledged as the correct singleton behavior;
  the `_fail_start` emit-and-return dual responsibility is acknowledged (all call sites
  `raise`).

## Recommendations

Fixed in the same feature branch before merge: stripped the ADR/issue identifiers from the
new comments (keeping the constraint prose), and moved the path resolution inside
`read_machine_discovery`'s `try` so it honors its "never raises" contract. The
acknowledged Lows need no change: the port-mismatch idempotency is the intended
singleton-attach behavior, and the `_fail_start` raise-at-call-site is the deliberate
control-flow choice the docstring documents.

## Codification candidates

- **Source:** the ADR decision plus the reorder/JSON-contract findings.
  **Rule slug:** `broker-facing-cli-outcomes-are-structured-and-idempotent`.
  **Rule:** A lifecycle CLI verb a broker drives must, in `--json` mode, emit exactly one
  structured envelope on every exit path (success and each failure) and treat an
  already-satisfied request as a success (exit 0 with an `already_*` status), never a
  non-zero fault a broker would misread as a gateway error.

Per the codify discipline, this holds one full execution cycle before promotion (first
encounter). The natural promotion occasion is the next broker-driven lifecycle verb to gain
a `--json` contract (e.g. `server stop --json`). Promote with
`vaultspec-core vault rule promote --from 2026-06-27-rag-broker-affordances-audit --as broker-facing-cli-outcomes-are-structured-and-idempotent`.
