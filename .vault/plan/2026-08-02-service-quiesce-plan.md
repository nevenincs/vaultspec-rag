---
tags:
  - '#plan'
  - '#service-quiesce'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:1f3c631e5013d733cc7e167f1a9e00a6b7fd6f3e1b4e166edde16a0befcfa65d'
tier: L2
related:
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-27-cli-service-operability-hardening-adr]]'
  - '[[2026-08-02-service-quiesce-paused-state-legibility-research]]'
---

# `service-quiesce` plan

Make a held service say so, and make the hold belong to whoever asked for it.

## Description

Two approved amendments drive this plan. `2026-07-24-service-quiesce-adr` governs Phase
`P01` and most of Phase `P02`: it binds ownership of a quiescence to the request that
produced it, adds a non-secret witness saying a hold is bound, and requires the health
verdict and operator surfaces to report the hold rather than its side effects.
`2026-07-27-cli-service-operability-hardening-adr` governs Step `P02.S10` alone, because
inverting structured failure forwarding from an allowlist to exclusion is a guarantee
about every CLI error envelope rather than anything specific to a pause.
`2026-08-02-service-quiesce-paused-state-legibility-research` grounds both, including the
live reproduction of the capture.

Client and service are pinned to exact version equality, so no compatibility shim is
required for the new snapshot field or the new health state, and none is planned. A
mismatched pair is already refused before either is read.

Phase `P01` is ordered ahead of `P02` because the witness it publishes is what `P02` reads
to choose remediation. Building the surfaces first would produce a status row that can name
a hold but not say who may end it, which is the defect being removed rather than a smaller
version of it.

## Steps

### Phase `P01` - Quiescence ownership and its witness

Bind a quiescence to the request that produced it, and publish a non-secret boolean saying a hold is bound without saying by whom. Ownership is the load-bearing change; the witness is what lets every later surface explain the hold.

- [ ] `P01.S01` - Add the non-secret borrower_bound field to the controller snapshot and its envelope; `src/vaultspec_rag/service_quiesce.py`.
- [ ] `P01.S02` - Stamp the binding onto every externally-visible snapshot through one registry helper; `src/vaultspec_rag/service.py`.
- [ ] `P01.S03` - Bind only a borrower-driven transition and refuse an observed unbound quiescence; `src/vaultspec_rag/server/_routes.py`.
- [ ] `P01.S04` - Give every lifecycle refusal a sentence distinct from its error code; `src/vaultspec_rag/server/_routes.py`.
- [ ] `P01.S05` - Accept the new field in the borrower safe-snapshot gate and name the pause in its lease refusal; `src/vaultspec_rag/cli/_gpu_lease.py`.
- [ ] `P01.S06` - Accept the new field in the preflight snapshot match; `src/vaultspec_rag/cli/_service_preflight.py`.

### Phase `P02` - Operator surfaces stop contradicting the controller

Make the health verdict, the status rows, and the structured failure envelopes report the hold the controller already knows about, and offer only remediation that can end it.

- [ ] `P02.S07` - Report a deliberate quiescence as its own health state rather than a degradation; `src/vaultspec_rag/server/_lifespan.py`.
- [ ] `P02.S08` - Name the hold and the work it holds in the status condition labels; `src/vaultspec_rag/cli/_status_labels.py`.
- [ ] `P02.S09` - Select the hold remediation from the bound witness and offer none when nothing ends it; `src/vaultspec_rag/cli/_status_render.py`.
- [ ] `P02.S10` - Forward service-published failure fields minus the keys the entry point owns; `src/vaultspec_rag/cli/_render.py`.

## Parallelization

Phase `P01` must land before Phase `P02` begins; the witness is a hard dependency, not a
convenience. Within `P01`, Steps `S01` and `S02` are one ordered pair because a field
nobody stamps reports false on every envelope that matters, and `S03` through `S06` all
read that stamped shape, so they follow it. `S03` and `S04` touch the same module and are
sequenced to avoid a conflict rather than because the work depends.

Within `P02`, Step `S07` precedes `S08` and `S09` because both render the verdict it
produces. Step `S10` shares no state with the rest of the phase and may be executed at any
point after `P01`, including in parallel with `S07`.

## Verification

The plan is complete when every Step is closed and the following hold.

A borrower that calls pause against a quiescence it did not cause is refused
`borrower_pause_not_owned`, the controller state is unchanged by that refusal, and the
operator's own unqualified resume still succeeds afterwards. This is the reproduction from
the grounding research run again: it failed before this plan and must pass after it.

A borrower that calls pause twice against its own binding succeeds both times, so the
ownership rule did not break retry after a lost response.

The published snapshot carries `borrower_bound`, it reads true only while a binding exists,
and it never carries a capability or a PID. The borrower safe-snapshot gate, the jobs view,
and preflight all accept the widened field set.

`vaultspec-rag server status` against a quiesced service names the hold, reports held work
as held rather than idle, and does not print `server doctor`. Against an operator-owned
hold it offers resume; against a bound hold it offers no command.

A search refused during a hold reaches the caller carrying the service's `retryable` flag
and controller block, in both JSON and human output.

Every lifecycle refusal renders a sentence that is not its own error code.

Each guard added here is proven able to fail before it is trusted: break the guard, run the
test alone, watch it fail on the assertion it names, restore, watch it pass.
