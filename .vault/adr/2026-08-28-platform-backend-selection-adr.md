---
tags:
  - '#adr'
  - '#platform-backend-selection'
date: '2026-08-28'
modified: '2026-08-28'
body_schema: 'body-v2'
body_hash: 'sha256:1e95fe8b721656f2958d174484fe7903ecc6c85f9c701e74e1597b492dd2139f'
related:
  - "[[2026-08-28-platform-backend-selection-research]]"
  - "[[2026-03-06-gpu-only-rag-stack-adr]]"
---

# `platform-backend-selection` adr: `admit any accelerator, and provision the CUDA stack the way every other platform already does` | (**status:** `proposed`)

## Problem Statement

`2026-03-06-gpu-only-rag-stack-adr` records a user mandate - GPU-only
inference, no CPU fallback - and the code enforces it through a single gate
that tests for CUDA. Two reported failures come out of that one substitution of
"CUDA" for "GPU", and they look like opposite complaints: a machine with a
working GPU is refused, and a machine with no GPU is made to carry five
gigabytes of CUDA.

Read together they are one question asked twice. Neither is a case for
softening the mandate, and neither can be answered by a local edit at the site
that reports the symptom, because the CUDA assumption is in the gate and in the
packaging rather than in either reporting path.

This record settles two things and deliberately leaves a third open: what
"GPU-only" admits, where the CUDA stack is provisioned, and - not settled here

- whether any particular non-CUDA backend is supported, which is a measurement
  this project has not yet been able to take.

## Considerations

- The mandate's stated intent is to use the GPU and never the CPU; it is not a
  statement about a vendor (`2026-03-06-gpu-only-rag-stack-adr`).
- macOS falling outside the supported set is an accepted consequence recorded
  in that same ADR, not a regression to repair
  (`2026-08-28-platform-backend-selection-research`).
- One gate already owns the admit/refuse decision, but `torch.cuda` calls have
  leaked past it into seven modules
  (`2026-08-28-platform-backend-selection-research`).
- Admission is the deepest coupling: it reasons about free VRAM on a discrete
  device, and unified memory has no equivalent reading
  (`2026-08-28-platform-backend-selection-research`).
- The CUDA weight on Linux is upstream: torch's CUDA requirements are gated on
  `platform_system == "Linux"`, and the Windows and macOS wheels carry none
  (`2026-08-28-platform-backend-selection-research`).
- Windows and macOS already obtain the GPU build through the install verb
  rather than the dependency set, because the index pin is workspace-scoped
  (`2026-08-28-platform-backend-selection-research`).
- No Apple silicon host has been reachable, so nothing about a second backend
  actually working has been measured
  (`2026-08-28-platform-backend-selection-research`).

## Considered options

**Leave the gate CUDA-shaped and document the limitation.** Honest and free.
It leaves the capability report stating that a machine has no GPU and 0 VRAM
when it has a working one, which is a false claim about hardware rather than a
declared limit, and it keeps the Linux packaging defect untouched.

**Select a device at runtime, admitting CUDA then MPS then CPU.** This is the
shape both issues ask for, and the CPU tail is why it is rejected: a silent
degrade to CPU is precisely what the mandate forbids, and a fallback chain
ending in CPU will be reached by accident on exactly the hosts least able to
afford it.

**Admit any accelerator, refuse CPU, and treat each backend as separately
supported (chosen).** The gate stops asking "is CUDA present" and starts asking
"is there an accelerator this build supports", with the supported set named
explicitly rather than implied by whatever torch happens to expose. CPU stays
refused with the message it already has. A backend enters the supported set
only on measurement, so nothing is advertised before it is known to work.

**Make torch a CPU default and put CUDA behind an extra.** Rejected on the
mandate: it makes the working default the one configuration the project refuses
to run, so the first experience of a correct install is a hard failure.

**Provision the CUDA stack through the install verb on every platform
(chosen).** Linux stops being the one platform where a plain install drags in
CUDA whether or not a GPU exists, and joins the path Windows and macOS are
already on.

## Constraints

- The supported-accelerator set cannot be widened without a host to measure on.
  No Apple silicon machine is currently reachable from the build environment,
  so MPS can be made *representable* by this decision but cannot be declared
  supported by it. That gate is a hard dependency on hardware access, not on
  code.
- Known MPS operator gaps mean a backend that imports and reports available is
  not necessarily one that runs both the dense and the sparse model end to end.
  `PYTORCH_ENABLE_MPS_FALLBACK` silently relocates unsupported operators to the
  CPU, which would satisfy the letter of the gate while violating the mandate,
  so it cannot be used to make a measurement pass.
- Admission is CUDA-specific by construction and has no unified-memory
  equivalent. A second backend needs an admission policy of its own, or an
  explicit decision that it is admitted unconditionally; carrying the VRAM
  computation over unchanged is not available.
- Moving the CUDA stack out of the default dependency set changes what an
  existing environment resolves on its next upgrade, not only what a fresh
  install gets. The migration path for already-provisioned environments is a
  real obligation of this decision.
- The change touches the parts of the tree that must stay torch-free in service
  mode, so it inherits that constraint rather than relaxing it.

## Implementation

The gate keeps its position and changes its question. `load_torch()` resolves a
device from an explicitly declared set of supported accelerators instead of
testing a single vendor predicate, returns that device alongside torch, and
refuses with the message it already uses when the set is empty. CPU is never in
the set. The declaration is data, so adding a backend is an edit to a list plus
the measurement that justifies it, not a new branch at each call site.

The `torch.cuda` calls that leaked past the gate move behind it. The capability
and readiness reporters describe the resolved backend by name rather than
reporting a CUDA device or nothing, and memory is reported in the terms the
backend actually has - which for a unified-memory device means not reporting a
VRAM figure rather than reporting zero. Admission stays CUDA's, and a backend
without an admission policy is refused rather than admitted by default, so the
conservative direction is the automatic one.

On packaging, the CUDA index pin moves from workspace-scoped configuration into
the provisioning verb's responsibility on Linux, matching Windows and macOS.
The default dependency set then expresses the project's requirement - torch -
without asserting which accelerator build satisfies it, and the runtime gate
continues to refuse anything that is not a GPU build. The existing detection
that recognises a CPU wheel and directs the user to the install verb becomes
the primary path on all three platforms rather than a remediation for two.

## Rationale

The decisive argument is that this is not a relaxation of the mandate, and both
alternatives that look cheaper are.

"GPU-only" was recorded to stop inference silently running on CPU. A device
resolution that admits accelerators and refuses CPU preserves that exactly,
while a fallback chain ending in CPU inverts it. The distinction matters more
than it looks, because the failure mode it prevents is the silent one: a host
that quietly runs slowly is the outcome the original ADR was written against.

On packaging, moving the CUDA stack behind the install verb changes when the
GPU build arrives, not whether it is required. The runtime gate is untouched
and still refuses a CPU wheel, so the project does not accept one silently at
any point. The reason to prefer this over documenting a CPU install is that it
makes the platforms consistent: two of three already work this way, the
mechanism already exists, and the detection that guides a user through it is
already written and already the path Windows users take.

Declaring MPS representable but unsupported is the part most likely to be read
as hedging. It is the opposite: the mandate is about not running inference
somewhere it does not belong, and advertising a backend that has never been run
end to end would be the same mistake in a new place.

## Consequences

The capability report stops making false statements about hardware, and adding
a backend becomes a bounded, reviewable change rather than a refactor. A
GPU-less Linux host stops paying for a CUDA stack it cannot use, and the three
platforms converge on one provisioning story, which removes an asymmetry that
currently has to be explained in the documentation rather than absent from it.

The costs are real. Every Linux user gains a step they did not previously need,
including CI, and an existing environment can silently resolve a CPU wheel on
its next upgrade and only discover it at the gate - so the upgrade path needs
to fail loudly and early rather than at first inference. Two admission policies
where there was one is more surface, and the second one has no VRAM signal to
reason from.

The macOS gap stays open. This decision makes it addressable rather than
addressed, and it will remain open until a host exists to measure on - which is
now an explicit, named blocker rather than an unstated one. That is a smaller
claim than either issue asks for, and it is the largest one the evidence
supports.
