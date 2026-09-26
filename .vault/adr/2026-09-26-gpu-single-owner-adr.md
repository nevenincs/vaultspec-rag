---
tags:
  - '#adr'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:8bc76fc30853c597495d91de4a39e2028d2541c2f0938c9f424465a25bce0f01'
related:
  - "[[2026-09-26-gpu-single-owner-audit]]"
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-07-29-gpu-admission-gate-adr]]"
  - "[[2026-06-21-service-first-search-fallback-adr]]"
---

# `gpu-single-owner` adr: `machine-global GPU ownership enforced at the model-load choke point` | (**status:** `accepted`)

## Problem Statement

The product is one model stack per machine: one resident service owns the GPU and
every other process is a client of it. `2026-09-26-gpu-single-owner-audit` shows
that nothing enforces that at the device. A local search with a mandate, the
Python API, and a daemon configured with a second storage directory can each bring
a second stack up beside a live service, of the same release or another, because
the only singleton is scoped to a storage directory and the only device check asks
whether there is room rather than who owns the card.
`2026-07-24-service-quiesce-adr` already rules that no local fallback may
allocate while a singleton is live and that intentional local GPU work needs a
borrower lease; this record decides the mechanism that makes that rule true for
every path and every release.

## Considerations

- The identity lock is keyed to the configured storage directory and guards the
  single-writer Qdrant storage as well as the service
  (`2026-06-24-service-hardware-singleton-adr`); discovery and the borrower anchor
  are derived from it (`2026-09-26-gpu-single-owner-audit`).
- Every model load already passes through one function, where the admission gate
  sits (`2026-07-29-gpu-admission-gate-adr`).
- Pytest redirects every configured singleton path into a per-session root, so an
  anchor resolved through configuration is private to each session; the admission
  record established that a hardware anchor is exempt from that containment.
- The GPU borrow lane runs model loads in the borrowing process and in child
  processes it starts, such as test daemons, while the resident service is
  quiesced but still running (`2026-07-24-service-quiesce-adr`).
- Releases already in the field hold only the storage-scoped identity lock
  (`2026-09-26-gpu-single-owner-audit`).
- The quiesce record forbids publishing a borrower's identity in snapshots, status,
  discovery, logs or errors.

## Considered options

- **A machine-global owner anchor, claimed at the model-load choke point (chosen).**
  One enforcement site covers the service, local search, local index, warmup, the
  Python API and test code; independent of every configured directory.
- **Relocate the identity lock machine-globally.** Rejected: shipped daemons would
  keep holding the old path, so two releases would stop contending, and discovery
  and borrower derivation would move with it.
- **Query the driver for CUDA processes.** Rejected: a new dependency surface and a
  subprocess per check, it cannot tell a vaultspec stack from any other tenant, and
  the admission record already declined it as a predicate.
- **Check only in the CLI search router.** Rejected: the API, index, warmup and
  test daemons bypass it.
- **Release the anchor on quiescence and let the borrower claim it.** Rejected: an
  unrelated process can win the gap, and the service's resume then contends with
  it and can stall in `warming`.
- **Anchor under the user's home directory.** Rejected: it moves with `HOME` and
  `USERPROFILE` and is invisible to a second account sharing the device.

## Constraints

- The ownership module is torch-free and importable from every path, including the
  torch-free CLI, MCP and service-client paths.
- Ownership fails closed: an anchor that cannot be opened refuses the load, unlike
  the load window, which degrades to the free-memory floor.
- The anchor is exempt from pytest containment for the same reason the load window
  is: it is hardware, not per-session state. No other singleton gains the
  exemption.
- The borrower's pid is written only into the local anchor record, which the
  borrower lease record already carries, and never into a snapshot, status,
  discovery record, log line or error.
- Guard tests prove they can fail, and code cites no vault document.

## Implementation

A torch-free ownership module owns one anchor file in a machine-global directory
resolved without configuration, `TEMP` or the home directory: the ProgramData
directory on Windows and `/tmp` elsewhere. The load-window anchor moves beside it.
Anchors there are created readable and lockable by every account, and a process
that cannot open one for writing locks it read-only, at the cost of not publishing
its pid.

`load_accelerator` asks the module for ownership before admission, once per
process. The first ask claims the anchor and retains it until the process exits,
so the service claims it on its first model load and holds it across quiescence.
When the anchor is held elsewhere, the ask succeeds only if the holder's record
lends the GPU to this process or one of its ancestors, verified by pid and start
time; otherwise it raises one typed refusal naming the holder and the way out.
Before a free anchor is claimed, releases that predate it are detected through the
storage-scoped identity lock: the configured one, and outside pytest also the
default-location one. A foreign holder of either is a refusal.

The service lends and reclaims at its borrower binding points: binding a verified
borrower rewrites the service's anchor record to name the borrower's pid, and the
resume or lease loss that clears the binding rewrites it back. `server start`
observes the anchor before spawning, as it already does for the identity lock, and
the search router checks ownership before running a mandated local search, so
both refuse in seconds with a structured error rather than at model load.

## Rationale

The choke point wins on coverage: every path that can put a model on the card
already calls it, so one check there leaves no path to forget, and a check anywhere
else either duplicates it or misses the API and test code. A separate anchor wins
over relocating the identity lock because it adds contention without removing any:
the storage lock keeps guarding storage, and the new anchor makes every release
that carries it contend on the device, whatever directories it was pointed at.
Lending through the owner's own record keeps the owner continuously in possession,
which is what makes the borrow lane race-free, and scoping the loan to a process
tree covers the test daemons the lane starts without letting anything else in.

## Consequences

- A local search, local index or API call beside a live service now refuses with a
  typed error. `--allow-fallback` means local compute when no owner exists, not
  local compute alongside one.
- A long-lived process that loads models through the API owns the GPU until it
  exits, and `server start` refuses meanwhile. That is the single-owner contract,
  and it is a behaviour change for anyone embedding the API.
- A service from a release that predates the anchor, running on a non-default
  storage directory, stays invisible to local compute. The gap closes as
  installations upgrade.
- Where a second account created the anchor, the holder's pid can go unpublished,
  and a refusal then names no pid.
- Tests that load models must run in the borrow lane, which was already the rule;
  a test that loads models outside it now fails instead of contending silently.
- The owner record gains a lending field, so a future handoff or multi-device
  scheme has a place to live.
