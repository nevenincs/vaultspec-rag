---
tags:
  - '#plan'
  - '#service-orphan-reaping'
date: '2026-07-23'
modified: '2026-07-23'
tier: L2
related:
  - '[[2026-07-23-service-orphan-reaping-adr]]'
  - '[[2026-07-23-service-orphan-reaping-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `service-orphan-reaping` plan

### Phase `P01` - confirm the launcher-daemon pair origin

Reproduce a race-losing daemon in isolation and capture its process tree so the reap predicate handles the launcher plus daemon pair, not a lone process.

- [ ] `P01.S02` - Reproduce a race-losing daemon in an isolated sandbox and capture the launcher-daemon process tree, persisting the pair-origin confirmation; `.vault/reference/service-orphan-reaping`.

### Phase `P02` - guarantee daemon self-exit on a failed claim

Route a failed machine-singleton claim and a failed port bind through the daemon's os._exit backstop so a race-losing daemon terminates instead of wedging at interpreter shutdown.

- [x] `P02.S01` - Move the machine-singleton claim inside the lifespan startup try-guard so its failure routes through _exit_standalone_daemon; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P02.S03` - Make the release-on-failure teardown tolerate a claim that produced no lease; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P02.S04` - Add a top-level entrypoint os._exit backstop on any startup exception escaping uvicorn.run; `src/vaultspec_rag/server/_main.py`.
- [ ] `P02.S05` - Add a bidirectional guard test that a race-losing spawned daemon terminates instead of lingering; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

### Phase `P03` - add the bounded signature-scoped orphan reap

Add an opt-in server stop reap that clears accumulated orphans by daemon signature while provably never touching the real singleton or an isolated-config instance.

- [ ] `P03.S06` - Add the daemon-signature enumeration and the lock-and-pointer-anchored reap predicate; `src/vaultspec_rag/cli/_service_stop.py`.
- [ ] `P03.S07` - Wire the opt-in server stop --orphans flag with its structured reaped-count success and refusal-fault envelope; `src/vaultspec_rag/cli/_service_stop.py`.
- [ ] `P03.S08` - Add guard tests that the reap never targets the singleton, a foreign process, or an isolated-config instance; `src/vaultspec_rag/tests/test_service_stop_port.py`.
- [ ] `P03.S09` - Add a test that the reap clears a real lingering launcher-daemon orphan pair; `src/vaultspec_rag/tests/integration/test_qdrant_orphan_reap.py`.

### Phase `P04` - verify and review

Prove self-exit and reap against regression and the broker structured-stop contract, then run the gate suite and code review.

- [ ] `P04.S10` - Reconcile the reap envelope with the broker and control-plane structured-stop regression suite; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.
- [ ] `P04.S11` - Run the code review and the full gate suite for the changed lifecycle and stop surface; `.vault/audit/service-orphan-reaping`.

## Description

Fixes the orphaned-daemon bug where a resident daemon that loses the
machine-singleton race lingers alive and stays invisible to `server stop`, so
repeated starts accumulate orphans and the operator cannot recover the machine.
Executes `2026-07-23-service-orphan-reaping-adr`, grounded in
`2026-07-23-service-orphan-reaping-research`, and extends the machine-singleton
reap of `2026-06-24-service-hardware-singleton-adr` (which reaps dead Qdrant
orphans and the lock holder, not live idle server daemons). P01 confirms the
launcher-daemon pair's origin so the reap predicate is trusted. P02 is part one
of the decision - guaranteed daemon self-exit on a failed claim or port bind,
which stops accumulation at the source. P03 is part two - a bounded, opt-in
signature reap that clears the backlog while provably never touching the real
singleton or an isolated-config instance. P04 verifies both against the
service-lifecycle and broker structured-stop regression suites and runs review.

## Steps

## Parallelization

P01 leads: its pair-origin confirmation is a hard prerequisite for the P03 reap
predicate, so P03 must not start until P01 lands. P02 (self-exit) shares no code
with P03 (reap) - `server/_lifespan.py` and `server/_main.py` versus
`cli/_service_stop.py` - so P02 and P01 may run in parallel, and P02 may proceed
independently of P03. Within P02 the Steps are ordered: the claim move
(`P02.S01`) and the teardown reconciliation (`P02.S03`) touch the same file and
must land together before the self-exit guard test (`P02.S05`). Within P03 the
predicate (`P03.S06`) precedes the flag wiring (`P03.S07`) and both precede the
guard tests. P04 is strictly last: it verifies the landed surface of P02 and P03.

## Verification

The plan is complete when every Step is closed. Success criteria, each a
verifiable check: a real spawned daemon that loses the singleton race is
observed to terminate rather than linger (the `P02.S05` bidirectional guard
test, proven to fail when the self-exit is broken); `server stop --orphans`
clears a real lingering launcher-daemon pair (`P03.S09`) and, by the `P03.S08`
guard tests proven to fail when the predicate is mutated, never terminates the
real singleton, a foreign process, or an isolated-config instance; every
`--json` stop exit emits exactly one structured envelope with the reaped-count
success status and a non-zero fault when an orphan refuses to die, reconciled
against the broker and control-plane stop suites (`P04.S10`); and the code
review plus the full ruff/ty/basedpyright/complexity gate suite pass on the
changed lifecycle and stop surface (`P04.S11`). Tests that touch the
machine-global singleton isolate the status and Qdrant storage dirs per the
managed-singleton isolation rule.
