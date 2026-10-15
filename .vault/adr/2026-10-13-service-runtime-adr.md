---
tags:
  - '#adr'
  - '#service-runtime'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:8b3cf3e8b4777b70940a632fb2a96f284cd6e029f826010ce8f519d38762bf3c'
related:
  - "[[2026-10-13-service-runtime-audit]]"
  - "[[2026-07-14-tool-env-gpu-continuity-adr]]"
  - "[[2026-09-26-tool-upgrade-cycle-adr]]"
  - "[[2026-10-05-qdrant-provisioning-trust-adr]]"
  - "[[2026-09-04-cuda-provisioning-adr]]"
  - "[[2026-06-24-service-doctor-liveness-adr]]"
  - "[[2026-09-01-gpu-less-install-footprint-adr]]"
  - "[[2026-10-13-monitor-provisioning-adr]]"
---

# `service-runtime` adr: `Run the service from a managed runtime when the launching environment cannot` | (**status:** `accepted`)

Accepted 2026-10-13 by the user ("fix all"), in reply to a proposal that named this decision: make `uvx vaultspec-rag server start` and GPU-less installs start the service, and make every install and provisioning message one cause and one command.

## Problem Statement

The daemon always runs from the interpreter that launched `server start` (`src/vaultspec_rag/cli/_process.py:480`). An environment without the GPU stack can therefore never start the service: a bare `uvx vaultspec-rag`, a `pip install vaultspec-rag` on Windows (where PyPI's torch is CPU-only), or a project client. The refusals it receives are contradictory and often unrunnable (`2026-10-13-service-runtime-audit`, uvx-start and windows-pip). This record decides where the daemon runs when the launching environment cannot serve, and what every refusal on the install and start paths may say.

## Considerations

- GPU-only, no CPU fallback; the base wheel stays torch-free (`2026-09-01-gpu-less-install-footprint-adr`).
- An environment is never replaced from inside itself (`2026-09-04-cuda-provisioning-adr`, D1); a separate environment is not that hazard.
- Models, the Qdrant binary and the monitor are already provisioned automatically on `server start`, with `server start` as consent (`2026-10-05-qdrant-provisioning-trust-adr`, `2026-10-13-monitor-provisioning-adr`). The Python environment the daemon runs in is the one dependency still left to the user.
- A uv tool environment's own repair cycle is settled (`2026-09-26-tool-upgrade-cycle-adr`) and works when followed.
- A client refuses a service from another release, so whatever serves must be the launcher's exact release.
- uv can prune or replace a uvx cache environment at any time; a long-lived daemon must not depend on one (`2026-07-14-tool-env-gpu-continuity-adr`).

## Considered options

- Managed service runtime: when the launching environment cannot serve, `server start` creates a private, versioned environment holding this exact release with its GPU extra, and runs the daemon there. Chosen: one command works from every launcher, release coupling is exact by construction, and it follows the provisioning pattern the other three start dependencies already use.
- Install or repair the user's `uv tool` environment from `server start`. Rejected: it mutates a user-owned tool namespace, can clobber a different release the user installed on purpose, and cannot run on Windows while that environment's launcher is the caller.
- Repair the launching environment in place by swapping torch. Rejected: it replaces an environment from inside itself (D1), and a uvx cache or a pip venv is not ours to change.
- Refuse, with one coherent command. Rejected as the end state. It remains the behaviour when the runtime cannot be created (no uv, no supported GPU).

## Constraints

Selection. `server start` judges the launching environment exactly as today. If that environment can run the service and is not a uvx cache environment, the daemon runs there, so tool hosts and development environments are unchanged. Otherwise the daemon runs from the managed runtime. A uvx cache environment never serves a daemon. Only `server start` creates a runtime: never the MCP adapter, the CLI's other verbs, or `install`.

Content. The runtime holds exactly the launching release of `vaultspec-rag[gpu]`. Its source is the launching distribution's own origin: the package index at that version, or the same local file or URL when the distribution was installed from one. An editable or source install is never reproduced; when it cannot serve, start refuses with one command. Torch comes from the CUDA index already pinned for host installs on Windows and Linux, and from PyPI on Apple silicon. The runtime's interpreter is `HOST_PYTHON`.

Trust and lifecycle.

- The runtime lives under the service directory, one directory per release. It is built in a staging directory and published by atomic rename under an exclusive lock; an incomplete build is deleted.
- Before first use it is judged with the same service-environment judgement. A runtime that cannot run the service fails the start with that one reason; no CPU runtime is ever accepted.
- A present, complete runtime costs no network access.
- After a start served from a runtime, superseded release directories are removed. A removal that fails is retried at the next start.
- Creation is reported through the provisioning outcome vocabulary as one more start dependency, and in JSON mode inside the one start envelope.

Tooling. The runtime is created with uv: the executable uv exposes to its children, else an absolute `uv` on PATH. Without uv, start refuses with exactly one command, which installs uv. This is the only `uv` subprocess on the start path.

Messaging.

- Every refusal on the install, start, doctor and status paths states one cause in one sentence and at most one command. The command is built for the environment kind and platform actually present, and uses `HOST_PYTHON`.
- No surface prints any of the following: a warning or repair for a state that is not present, alternative commands, internal design notes, or a command that would mutate uv's cache.
- `server doctor` reports not ready, and exits non-zero, whenever a `server start` would fail or no service is running. Every start dependency is one of its rows.
- `status` names `server start` as the next action when no service runs.

Affected rulings, reconciled on acceptance:

- `2026-07-14-tool-env-gpu-continuity-adr`, O-C1: the loud uvx-ephemeral warning is retired along with the uvx daemon; the classifier stays. The codification candidate `gpu-remediation-prints-exact-commands` is narrowed to one command for the resolved environment. The constraint against a `uv` subprocess on the start path gains the runtime exception above.
- `2026-10-05-qdrant-provisioning-trust-adr`: whenever this record selects the managed runtime, "the interpreter that will run the daemon" is the runtime's interpreter. A launching environment that cannot serve is no longer told it cannot provision.
- `2026-09-04-cuda-provisioning-adr` and `2026-09-26-tool-upgrade-cycle-adr` are unchanged. They govern repairing an environment the user owns, which this record never touches.

## Implementation

We will add a managed service runtime, selected by `server start` when the launching environment cannot serve, and make every install and start refusal one cause and one command. Hypotheses that may change within the constraints:

- The selection sits behind `_resolve_daemon_interpreter` (`src/vaultspec_rag/cli/_process.py:480`), so the existing preflight, dependency provisioning and spawn run unchanged against the runtime's interpreter.
- The runtime module is torch-free and reuses the existing file-lock and atomic-write helpers.
- Creation runs `uv venv --python 3.13`, then `uv pip install --python <runtime> <spec>` with the CUDA index and strategy from `src/vaultspec_rag/operator_state/_provisioning.py`.
- A `runtime.json` completion record carries the release, the source and the judged capability.

## Rationale

`server start` already fetches and verifies every other start dependency without a user step. The interpreter was the last one left, and it is what made every non-tool route fail. A separate environment avoids each hazard the earlier decisions guard against (self-replacement, mutating user tool environments, depending on uv's cache) and makes the release coupling exact. Refusal remains only where creation is impossible, and then it is one sentence and one command (`2026-10-13-service-runtime-audit`).

## Consequences

`uvx vaultspec-rag server start`, `pip install vaultspec-rag` and project clients start the service with one command. The first such start downloads the GPU stack (several gigabytes) into the service directory, once per release, alongside any tool environment the user also keeps. Superseded runtimes are reclaimed automatically. Reconsider if uv stops exposing a stable environment-creation surface, if PyPI begins shipping CUDA torch for Windows, or if a second process per machine ever needs its own runtime.
