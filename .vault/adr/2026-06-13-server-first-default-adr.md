---
tags:
  - '#adr'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
related:
  - "[[2026-06-12-serving-runtime-research]]"
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
---

# `server-first-default` adr: `server mode is the default rag backend` | (**status:** `accepted`)

## Problem Statement

The product defaults to the pure-Python local vector store and treats the supervised
Qdrant server as an opt-in escape hatch. The adversarial A/B on a real 469k-code-chunk
corpus refutes that default: the local brute-force scan averaged a 70.9-second search
phase (106-second p50 total per code search), while the server returned the identical
query with an 18-millisecond search phase - a ~2,355x reduction on the vector phase and
~54x end to end, with a follow-on quality audit confirming the server results are
correct, relevant, and robust under load. At the scale this product exists to serve -
large codebases and multi-agent saturation - local mode does not clear the interactive
usability bar at all. A default chosen before that evidence existed now points users at
the mode that does not work for the target use case. This ADR flips the default: server
mode becomes the assumed backend; local mode becomes a deliberate, first-class opt-out.

## Considerations

- The win is scale-dependent, not absolute. On small corpora the local store is
  sub-millisecond and needs no external process; it is only at scale that its
  brute-force scan degrades catastrophically. So the decision is not "local is
  obsolete" but "the default must match the product's target use case (large
  corpora), and that target is decisively server-served".
- Anyone running the resident service is already past the lightweight threshold - a
  GPU daemon holding roughly two gigabytes of models. A supervised Qdrant child is an
  incremental cost on an already-heavy process, not a new class of burden, which is
  what makes server-first defensible as the default rather than merely available.
- The escape hatches are what keep a server-first default safe to ship: a one-flag
  local mode for small projects, CI, and constrained hosts; an operator-supplied
  binary path for air-gapped and proxy environments; and graceful, loud failure when
  the server cannot start.
- The packaging mechanism and the runtime default are independent axes. Flipping the
  default does not require changing how the binary is delivered.

## Constraints

- The distribution wheel must remain pure-Python (`py3-none-any`). Flipping the
  default backend must not bundle the Qdrant binary into the wheel; the binary stays
  a runtime-provisioned artifact. Bundling would force a per-platform wheel matrix,
  carry redistribution obligations, and was already rejected in the provisioning
  research.
- Local mode must remain a first-class, single-flag mode, never a vestigial fallback.
  The server-first default is only acceptable because local mode stays fully
  supported and trivially selectable.
- The air-gapped / operator-supplied-binary path and a clean, actionable failure when
  the server is unavailable must remain first-class.
- This decision depends on the supervised-server feature being accepted and stable -
  it is, with a passing code review, real-binary integration coverage, and the A/B
  and quality audit on a large corpus. The single-GPU and zero-mocks test mandates
  carry over unchanged.

## Implementation

The default selection moves from local to server at two layers, while the
provisioning mechanism (the runtime binary provisioner) is unchanged - only its
default trigger flips.

- Runtime default: the resident service starts in server mode unless local mode is
  explicitly selected (a `--local-only` flag or the existing server-mode env knob set
  to off). When server mode is the default and the binary is present, the service
  supervises the Qdrant child and routes every project's stores at it; when local
  mode is selected, the service uses the per-project on-disk store exactly as today.
- Setup default: the setup flow provisions the server binary by default, with
  `--local-only` as the opt-out. The detailed shape of that provisioning front door
  is the subject of the sibling provisioning-and-setup decision; this ADR fixes only
  that its default is server-first.
- Documentation default: the getting-started and CLI help describe the server-mode
  experience as the standard path, and local mode as the explicit minimal / CI /
  air-gapped alternative. The local-versus-server language is reframed from
  "local-first, server optional" to "server-first, local explicit".
- Unchanged: the pure-Python wheel, the provisioning backend, the per-root namespaced
  collections, the security model, and the backend-aware store locking (server mode
  already takes no point-operation locks) all carry over.

## Rationale

The serving-runtime research concluded that the engines, not the language, were the
constraint, and named Qdrant server mode as the next-feature win with a measured
local-mode baseline. The A/B turned that prediction into a measurement: 70.9s to
0.03s on the search phase over a 469k-chunk corpus, with a single warm server search
at 0.71 seconds versus 106 seconds local. The quality audit then closed the obvious
skeptical objection - that a fast search might be returning empty or wrong results -
by verifying around twenty-five top hits against ground truth on disk, exercising
duplicate-definition discovery, confirming filters constrain correctly, and proving
graceful degradation under thirty-six concurrent and sixteen adversarial probes with
zero crashes and zero contamination. A default should point at the mode that is both
faster and proven correct for the product's target scale; the evidence now justifies
flipping it. Local-first was the conservative default chosen before this evidence; it
has served its purpose and is reframed, not removed.

## Consequences

- The default experience finally matches the product's reason for existing: large
  codebases become usable at interactive latency out of the box.
- First-run cost rises for the default path: a one-time binary fetch plus a server
  spawn join the existing model-load cost. This is the deliberate price of a default
  that scales, and it is bounded and one-time. The `--local-only` mode remains for
  anyone who wants the lighter footprint.
- The escape hatches become load-bearing rather than peripheral: CI, offline, and
  small-project users now depend on `--local-only` and the operator-binary path being
  well-documented and reliable. Their first-class status is a hard requirement, not a
  nicety.
- A latent expectation shifts: with the resident service defaulting to a supervised
  child process, service lifecycle, health, and shutdown ordering for that child
  become part of the standard path rather than an opt-in corner, raising the bar on
  their robustness (already addressed by the supervised-server feature, now exercised
  by default).
- Risk: a server-first default that fails opaquely on a constrained host would be
  worse than a local default that merely runs slow. The mitigation is the loud,
  actionable failure contract and the trivially selectable `--local-only` mode -
  both mandated constraints above.

## Codification candidates

- **Rule slug:** `server-mode-is-the-default-backend`.
  **Rule:** Server mode is the assumed RAG backend; local mode is a first-class
  explicit opt-out (`--local-only`), never removed and never the default - and the
  default flip must never bundle the server binary into the pure-Python wheel.
