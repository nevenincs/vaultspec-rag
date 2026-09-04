---
tags:
  - '#adr'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:abf108faf968d72f80d208151315db09b8c383fff6f39b303bbff8f69c1de3a6'
related:
  - "[[2026-09-04-cuda-provisioning-research]]"
  - "[[2026-07-14-tool-env-gpu-continuity-adr]]"
  - "[[2026-09-01-gpu-less-install-footprint-adr]]"
  - "[[2026-06-24-torch-dependency-group-adr]]"
  - "[[2026-07-23-ci-self-hosted-gpu-runner-adr]]"
---

# `cuda-provisioning` adr: `holder-safe CUDA provisioning and its isolated live proofs` | (**status:** `accepted`)

## Problem Statement

The durable CUDA pin is applied by a whole-environment replacement that destroys the
environment whenever anything is running out of it, and the product both prescribes that
command to operators and executes it itself. A field incident on 2026-09-03 left an
operator's tool environment unrunnable; `2026-09-04-cuda-provisioning-research` establishes
that the automatic path reaches the same end by construction on Windows, that the guard in
front of it answers a different question than the one that matters, and that no test has
ever observed real uv acting on a held environment.

`2026-07-14-tool-env-gpu-continuity-adr` already requires the installer to detect and
refuse before invoking the replacement, and made a real-Windows execution proof a gate on
execution. That gate was never met, and the reproduction now shows the shape it chose
cannot meet it. This record decides what replaces it, and - because provisioning
robustness is unprovable without a way to stage hostile environments - the test and CI
structure that makes such proofs repeatable across this repository and vaultspec-core.

## Considerations

- uv replacement is non-atomic and destroys on a blocked removal, while resolve and fetch
  failures leave the environment intact; uv serialises concurrent tool installs under its
  own tool-directory lock (`2026-09-04-cuda-provisioning-research`).
- A holder is any process whose image path or working directory sits under the environment
  root; the working-directory case is invisible to an image-path test and destroys more.
- The invoking interpreter is itself a holder whenever the target is its own environment,
  which the current transaction guarantees by only ever targeting that environment.
- `psutil` is already a direct dependency and `_process_probe` already establishes the
  fail-closed contract that an undeterminable observation is never reported as clear.
- A whole-environment replacement by package name also re-resolves version and extras, so
  a repair consented to as a torch fix silently upgrades and re-specifies the tool.
- `2026-09-01-gpu-less-install-footprint-adr` introduced a deliberately torch-free install
  that the current defect classifier reads as broken.
- The torch pin version has two independent sources, which the canonical-code rule forbids.
- Tier markers in this repository are enforced at collection and coupled to GPU leasing and
  a Hugging Face token; vaultspec-core enforces nothing but declares comparable markers.
- vaultspec-core gates pull requests on a hosted Windows runner; this repository excludes
  every Windows job from pull requests to keep fork code off self-hosted machines, so its
  existing Windows-only tests cannot block a merge (`2026-09-04-cuda-provisioning-research`).

## Considered options

**D1 - execution shape of the durable pin.**

- **O-1a (chosen) - never replace an environment from inside it; refuse and hand over the
  command.** The transaction runs the holder preflight, reports every holder, and returns a
  refusal carrying the exact command for the operator to run from a clean shell.
- **O-1b - detached relauncher.** Rejected for this record: the escape observed in
  grounding won a race against a warm-cache resolve rather than closing it, and a correct
  version needs a third process that waits on the original pid before invoking uv.
- **O-1c - out-of-environment orchestrator.** Deferred, not rejected: it is the only shape
  that could restore a fully automatic repair, and O-1a is a precondition for it either way.
- **O-1d - keep the current synchronous in-environment invocation.** Rejected: proven to
  destroy the target on Windows.

**D2 - what the preflight checks.**

- **O-2a (chosen) - holders of the target environment, by image path and by working
  directory, failing closed on any undeterminable observation.**
- **O-2b - the machine service only.** Rejected: this is the shipped guard, blind to CLI
  invocations, MCP servers before they claim the singleton, and the invoking process.
- **O-2c - a pidfile registry of the product's own processes.** Rejected as the primary
  mechanism, since it cannot see an unrelated interpreter; retained as a possible
  complement.
- **O-2d - Windows open-handle enumeration.** Rejected: new platform code, elevation
  questions, and no existing precedent in either repository.

**D3 - scope of an automatic repair.** **O-3a (chosen)** - the request a repair hands
over may change the torch wheel only: it pins the installed version and reuses the
extras the receipt already records. **O-3b** - keep the current latest-version,
`[gpu,mcp]`-imposing behaviour. Rejected: it is an unannounced upgrade offered under a
prompt about torch.

Amended during execution. This decision originally also required the repair to carry its
own consent flag rather than inherit file-overwrite `--force`. D1 removed the mutation
that consent authorised, so the prompt was removed rather than re-flagged: asking for
permission to print a command is friction with no consequence, and demanding it made a
defective tool environment undiagnosable from a non-interactive run. An opt-out
(`--no-tool-repair`) skips the check itself, which is the only choice left that changes
anything.

**D4 - torch absent by design.** **O-4a (chosen)** - absence of torch in an install that
never requested the GPU extra is a state, not a defect; the repair does not fire and
install completes. **O-4b** - keep treating it as defective. Rejected: it makes the
footprint ADR's install impossible to complete without a terminal.

**D5 - torch pin version source.** **O-5a (chosen)** - one derivation from the lockfile.
**O-5b** - keep two independent values and add a drift test. Rejected: two implementations
of one fact is what the canonical-code rule forbids.

Amended during execution. Deleting the runtime constant outright, as this decision
originally also required, is not possible: a published wheel ships neither `uv.lock` nor
`pyproject.toml`, so an installed runtime has nothing to derive from, and the constant is
the only thing an environment holding no torch can name a wheel by. The derivation is
therefore singular and lives in the package (`torch_config._lockfile`), the build tooling
consumes it rather than reimplementing it, and the constant remains as a mirror that a
test holds to the lockfile's value wherever a checkout is reachable. That is one
derivation with a mechanically verified copy, not the two hand-maintained values O-5b
would have kept.

**D6 - proof harness.** **O-6a (chosen)** - real uv against redirected tool, bin and cache
directories, stand-in wheels served over loopback HTTP, real holder subprocesses, receipts
parsed back. **O-6b** - `file://` stand-ins. Rejected on fidelity: uv records those under a
path key, so the receipt matcher's real branch would never execute. **O-6c** - an injected
runner seam only. Kept as a complement for branch classification, rejected as the primary:
it cannot observe uv's destructive semantics. **O-6d** - recorded fixtures. Confined to the
pure parsers that already use hand-written input.

**D7 - tier and CI, decided once for both repositories.** **O-7a (chosen)** - these tests
carry the fast tier marker, live beside the code they exercise, are selected by marker
rather than directory, and run on a hosted Windows leg at pull-request time in both
repositories; vaultspec-core inherits this by its existing hosted Windows leg, and this
repository gains one scoped to this class. **O-7b** - promote the existing self-hosted
Windows job into the pull-request lane. Rejected: it reintroduces the fork exposure that
topology exists to prevent. **O-7c** - accept the proofs as advisory and post-merge.
Rejected as the primary outcome, since it reproduces the present situation where a
Windows-only regression cannot block a merge; retained as the fallback if the hosted leg
proves unaffordable in runtime budget.

## Constraints

- Every uv behaviour this record relies on was observed on `uv 0.12.8` on Windows. uv is a
  fast-moving dependency whose receipt serialisation has already changed across releases,
  so the receipt shape is a versioned assumption, not a stable contract.
- POSIX replacement ordering is untested. If unlink semantics make the held-file failure
  impossible there, the refusal in D1 is Windows-necessary and elsewhere merely
  conservative; the implementation must not assume the hazard is universal without proof.
- Holder enumeration cannot see cross-user processes without elevation, so the preflight is
  complete only for the invoking user and must say so rather than implying certainty.
- D7 depends on a hosted Windows runner being able to execute this class without the warm
  model cache the self-hosted fleet provides. This is expected, since the class needs no
  model weights, but it is unverified and is the one input that could force O-7c.
- D7 spans a repository this record does not govern. vaultspec-core needs its own record of
  the same convention; this ADR is not authority over that repository's vault.
- Disk exhaustion has no honest reproduction against real uv and stays outside the proof
  set rather than being simulated misleadingly.

## Implementation

A holder module gains one query: given an environment root, return the live processes whose
image path or working directory resolves under it, each carrying its pid, image, command
line and which relation matched, with an explicit undeterminable result where a process
cannot be inspected. It builds on the existing process-probe primitives and their
fail-closed contract, and is bounded to the environment's own holders rather than a machine
dump.

The repair transaction changes shape rather than gaining a check. Its terminal outcomes
grow a holder-detected refusal that names the holders and the remediation appropriate to
each relation - close this process, or leave this directory - and the destructive
invocation is removed from the in-environment path entirely, replaced by the command it
would have run. The consent surface separates from file overwrite, states what will be
replaced, and the human renderer prints the outcome that today only appears in JSON. The
defect classifier learns the difference between torch absent by design and torch present
but processor-only. The pin version derivation collapses to the lockfile-backed one.

Readiness reports holders as an informational dimension, so an operator learns that an
environment is held before attempting anything, rather than at the moment of refusal.

The proof harness is a fixture set: a redirected tool, bin and cache environment; a
loopback wheel index serving stand-in distributions, including one shaped like a CUDA torch
release and one with a deliberately wrong interpreter tag; and a holder subprocess helper
following the pattern both repositories already use for real lock holders. On that
foundation sit the proofs this campaign owes - that a held environment is refused rather
than destroyed, that a refusal launches no uv child, that a receipt written by real uv
satisfies the matcher, that a resolve failure leaves the environment intact, and that the
in-environment invocation is gone.

## Rationale

The knockout is that D1's rejected option cannot work rather than merely being risky: the
grounding reproduces the current transaction destroying its own target, so no guard placed
in front of it changes the outcome. Once the destructive invocation leaves the
in-environment path, the preflight's job narrows to telling the operator the truth before
they run the command themselves, which is also the only shape that is correct on a machine
whose holders include editor sessions this product does not control.

D2 follows from a single observation that an image-path test alone would have called that
machine clear. D6 follows from a single measurement: the obvious cheap harness would have
passed every receipt test without exercising the branch that matters. D7 is chosen against
the alternative of writing proofs that cannot block a merge, which is the failure mode the
grounding found already operating on eight existing Windows-only tests.

## Consequences

The automatic repair becomes less capable: an operator on a defective tool environment is
handed a command instead of having it run for them. That is the honest position until an
out-of-environment orchestrator exists, and D1 leaves that path open rather than closing it.

Refusals will occur where the shipped code proceeded, including cases that would have
succeeded, because a working-directory holder blocks the operation whether or not it would
have collided. Fail-closed enumeration makes the preflight conservative by design, and an
uninspectable process becomes a refusal rather than an unexamined risk.

The proof harness introduces a dependency on real uv in a commit-gating lane, so a uv
release that changes receipt serialisation will fail these tests. That is the intended
alarm, and it is why recorded fixtures were rejected for this surface.

Adopting D7 gives this repository its first pull-request-gating Windows coverage, which
benefits the eight existing Windows-only tests that currently cannot block a merge, beyond
this campaign's own scope. It also commits both repositories to one convention, which
requires a mirrored record in vaultspec-core before that half is real.
