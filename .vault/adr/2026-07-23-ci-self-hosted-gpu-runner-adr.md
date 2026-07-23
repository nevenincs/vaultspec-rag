---
tags:
  - '#adr'
  - '#ci-self-hosted-gpu-runner'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - "[[2026-07-23-ci-self-hosted-gpu-runner-research]]"
---

# `ci-self-hosted-gpu-runner` adr: `Self-hosted GPU CI runner with trusted-event tier split` | (**status:** `accepted`)

## Problem Statement

CI runs only on GitHub-hosted Linux with no GPU, so the entire GPU-bearing test
tier is deselected by marker exclusion and never executes. A green CI light
certifies only the tokenless unit subset, while integration, quality,
performance, robustness, subprocess-GPU, and CUDA coverage is left to
"run it on a quiet machine later." The project is GPU-only; the gate that
matters is exactly the one that never runs. The host of this work is itself a
CUDA workstation and the intended runner, so the fix is available in place. The
decision must resolve where each tier runs and, because the repository is
public, how to keep untrusted fork code off the workstation.

## Considerations

- The suite splits by cost into a portable unit tier and a CUDA-bound heavy
  tier that additionally needs `HF_TOKEN` for a gated model
  (`2026-07-23-ci-self-hosted-gpu-runner-research`).
- A self-hosted runner on a public repo executes fork PR code on the host by
  default — remote code execution plus secret exfiltration
  (`2026-07-23-ci-self-hosted-gpu-runner-research`).
- The workstation already hosts an unrelated runner; a second instance must not
  disturb it, and no machine identity (paths, user, host, token) may enter
  tracked files (`2026-07-23-ci-self-hosted-gpu-runner-research`).
- Hosted minutes are free and parallel for the cheap tier; the workstation is
  the only GPU available and should carry only what needs it.

## Considered options

- **All-hosted, keep deselecting the GPU tier (status quo).** Free and safe, but
  the GPU tier never runs — the defect itself. Rejected.
- **GPU cloud runners for the heavy tier.** Real GPU execution without exposing
  a workstation, but recurring cost and provisioning weight for a single-dev
  project. Rejected as disproportionate.
- **Self-hosted GPU runner, unguarded `pull_request`.** Executes the tier, but
  hands fork authors code execution and secrets on the host. Rejected outright.
- **Self-hosted GPU runner for the heavy tier, hosted for the cheap tier, GPU
  job gated to trusted events (chosen).** Real GPU green on trusted events; fork
  PRs get the hosted tiers only, no secrets, no runner access.
- **Ephemeral self-hosted runners.** Stronger residue isolation, but needs an
  autoscaler/controller that is overkill here; the trusted-event gate already
  removes the untrusted-code vector. Deferred.

## Constraints

- Public repository: the trusted-event gate is load-bearing, not optional. It
  must pair with the repo Actions setting requiring approval for outside
  collaborators.
- 16 GB VRAM: `subprocess_gpu` tests must run in a separate pytest invocation
  from the serialized markers so their out-of-lock process VRAM does not
  co-schedule.
- The heavy tier needs `HF_TOKEN`; it is a repo secret, exposed only to the
  trusted-event-gated job.
- The runner install, its `_work` tree, and its registration credential live
  outside the repo; workflow files reference generic labels only, and
  `.github/actionlint.yaml` must enumerate every custom label.
- A second runner instance coexists with the pre-existing one only by living in
  its own directory with its own service; the existing runner is never
  reconfigured.

## Implementation

A dedicated runner instance is installed outside the tree (its own directory,
`_work`, and Windows service), registered to the repository with the labels
`self-hosted`, `windows`, `gpu`, `cuda`, and run as a delayed-auto-start
service under the default machine service account, which reaches the
system-wide CUDA driver and stays isolated from the developer's per-user
resident service. The registration token is minted on demand and used
transiently.

CI keeps its cheap tiers on GitHub-hosted Linux — workflow lint, the combined
lint/type/config/link/markdown/citations/complexity job, the hosted unit
`Tests` job, vault audit, and dependency audit — all firing on every push, pull
request, and manual dispatch. A new `GPU Tests` job runs on the self-hosted
labels and executes the complement of the hosted unit selector: the serialized
GPU markers plus `cuda` in one pytest invocation, then `subprocess_gpu` in a
second, both driven through a single shared `just dev test gpu` recipe so local
and CI stay identical. The job verifies CUDA visibility, provisions the Qdrant
binary, and passes `HF_TOKEN` from a secret. It is guarded by
`github.event_name != 'pull_request' || head.repo.full_name == github.repository`
so pushes, manual dispatch, and same-repo PRs run it while fork PRs are refused
before any secret is in scope. Event triggers across the workflow were audited
and left as the already-lean push-main / pull_request / workflow_dispatch set.

## Rationale

The tier split wins because it puts each tier where it is cheapest and safest:
the free hosted fleet keeps carrying the fast, parallel gates on every event
including fork PRs, while the one scarce resource — the GPU — carries only what
genuinely needs it. Against the unguarded-runner alternative the decisive edge
is security: the trusted-event gate is a single boolean that structurally
removes fork code from the host, which the research shows is the entire attack
surface for a public-repo self-hosted runner. Against GPU cloud the edge is
cost and simplicity for a single-developer project whose workstation is already
the target device. The shared `just` recipe is what keeps the gate honest — the
same command developers run locally is the command CI runs, so a passing local
run and a passing gate mean the same thing.

## Consequences

- The GPU tier now executes in CI on trusted events: green means the real suite
  passed, not that it was skipped. This will honestly surface any pre-existing
  integration failure that deselection had been hiding — an intended exposure,
  not a regression of this change.
- Fork PRs run only the hosted tiers and never touch the workstation or its
  secrets; contributors still get lint/type/unit signal.
- A red GPU tier can block `main`; until the heavy suite is reliably green, the
  `GPU Tests` check should not be marked required for merge, and can be promoted
  to required once it is stable.
- The workstation is now a CI dependency: if it is offline, trusted-event GPU
  runs queue. The runner is persistent (not ephemeral), so residue isolation
  rests on the trusted-event gate; revisit ephemerality if the trust model
  widens.
- Operability cost: the runner service, its labels, and the repo approval
  setting are now part of the CI contract and must be kept in sync with the
  workflow's `runs-on` labels and `actionlint.yaml`.
