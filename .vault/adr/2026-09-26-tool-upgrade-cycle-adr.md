---
tags:
  - '#adr'
  - '#tool-upgrade-cycle'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:c94c9dc5ae045eeac5992410c04322e376a0f18d90f44106a721a9e486bc055d'
related:
  - "[[2026-09-26-tool-upgrade-cycle-research]]"
  - "[[2026-07-14-tool-env-gpu-continuity-adr]]"
  - "[[2026-09-04-cuda-provisioning-adr]]"
  - "[[2026-09-23-status-messages-adr]]"
  - "[[2026-09-26-gpu-single-owner-audit]]"
---

# `tool-upgrade-cycle` adr: `a receipt-carried CUDA source and in-place repair make installing and upgrading one cycle` | (**status:** `accepted`)

## Problem Statement

A `uv tool` GPU host must stay a GPU host across every upgrade, and upgrading
must keep working, without the operator re-deriving a repair each time. The
shipped mechanism does neither: it keeps CUDA only by pinning a direct torch
wheel and the installed release into the receipt, which freezes both, and its
repair replaces the environment wholesale, which the running service or an
agent's MCP adapter can break half-way (`2026-09-26-tool-upgrade-cycle-research`
F1, F5; `2026-09-26-gpu-single-owner-audit`). The research shows uv can carry a
dynamic CUDA source in the receipt and apply it in place, so the decision is
how installation, repair and upgrade use that to become one self-sustaining
cycle. The user directed on 2026-09-26 that the install and upgrade cycle must
be a persistent and dependable automanagement cycle.

## Considerations

- The index and index strategy given at install time are persisted in the
  receipt by every uv release from 0.9.0 on; `--torch-backend` is not
  (`2026-09-26-tool-upgrade-cycle-research` F2).
- Only the first-match strategy resolves the real package with the CUDA index;
  first-index is unsatisfiable and best-match silently prefers PyPI's CPU build
  when PyPI leads (F3).
- A bare `uv tool upgrade` of an options-carrying, unpinned receipt moves the
  release and keeps CUDA (F4).
- In-place installs and upgrades succeed while the environment is held, where
  a wholesale `--force` replacement does not (F5,
  `2026-09-04-cuda-provisioning-research`).
- An installation already in the field is brought onto the cycle by one
  in-place command that changes only torch (F6).
- `2026-09-04-cuda-provisioning-adr` D1 forbids replacing an environment from
  inside it; D3 forbids a repair that silently upgrades or re-specifies the
  tool. `2026-07-14-tool-env-gpu-continuity-adr` O-A1 chose the direct wheel
  because it believed no index option survives in the receipt.
- `2026-09-23-status-messages-adr` makes typed operator-state enums own labels
  and remediation, consumed by install, doctor and status alike.

## Considered options

- **Receipt-carried CUDA index with the first-match strategy, no version pin,
  applied in place (chosen).** Torch resolves dynamically at every upgrade,
  the release stays upgradable, and nothing replaces the environment.
- **Keep the direct wheel and the version pin.** Rejected: freezes the release
  and torch (F1).
- **`--torch-backend`.** Rejected: not persisted, and `uv tool upgrade` cannot
  take it (F2).
- **The CUDA index with the default first-index strategy.** Rejected:
  unsatisfiable for the real package (F3).
- **Best-match across indexes.** Rejected: selects the CPU build whenever PyPI
  publishes a torch release first (F3).
- **A product-run orchestrator that stops the service and force-reinstalls.**
  Rejected for now: in-place application needs no stop and no replacement
  (F5), so the orchestrator would add a failure mode without removing one.

## Constraints

- The CUDA source is offered only where PyTorch publishes CUDA wheels (Windows
  x86_64, Linux x86_64 and aarch64); elsewhere the platform-checked builder's
  refusal or Apple Metal guidance stands.
- The repair changes torch only and records no version pin, which keeps D3's
  guarantee against a silent upgrade without freezing the tool. Upgrading is a
  separate, named step.
- Nothing replaces an environment wholesale; D1's prohibition stands, and the
  in-place repair is the only mutation the product performs on its own
  environment. Because a changed interpreter request turns a plain
  `uv tool install` into a wholesale rebuild
  (`2026-09-26-tool-upgrade-cycle-research` F5), every command names the target
  environment's own interpreter, and the product runs one only when uv's tool
  entry for the package is the environment the running interpreter belongs to.
- Under pytest the repair runner refuses any tool environment outside the
  containment root, so no test can mutate a real installation whatever it
  consents to.
- The product runs the repair itself only on explicit consent - an interactive
  confirmation or `--yes` - and verifies both the compute build and the receipt
  afterwards; without consent it hands over the same command and exits
  non-zero, as today.
- This record replaces O-A1 of `2026-07-14-tool-env-gpu-continuity-adr` and the
  version pin of D3 in `2026-09-04-cuda-provisioning-adr`; every other decision
  in both records stands.

## Implementation

The torch-free operator-state layer gains a typed receipt verdict for a tool
environment: durable (both options present, no version pin, no direct torch
wheel), version-pinned, torch-wheel-pinned, carrying no CUDA source, or
unreadable. Each verdict owns its label and the one command that makes the
receipt durable.

The single command builder produces two commands. The repair re-installs the
tool in place with its recorded extras and interpreter, the CUDA index, the
first-match strategy and an upgrade of torch alone. The upgrade is a bare
`uv tool upgrade` of the tool once the receipt is durable, and the repair with
a full upgrade otherwise; either is followed by restarting the service so the
running daemon matches the installed release. The direct-wheel machinery and
the version pin are deleted rather than kept beside the new commands.

`install` treats a tool environment whose receipt is not durable as needing
the repair even when its current torch build works, because the next upgrade
would break or freeze it. With consent it runs the repair from its own process
and verifies the result; otherwise it prints the command. Doctor and status
report the receipt verdict beside the compute verdict and print the same
command, and every upgrade recommendation comes from the same builder.
Installation documentation installs the tool with the two options from the
start.

## Rationale

The receipt is the only state uv consults on every upgrade, so a CUDA source
recorded there is the only one that survives upgrades nobody supervises; a
dynamic index rather than a wheel is what keeps that from turning into a
freeze. First-match is the one strategy that both resolves the package and
cannot quietly prefer the CPU build over an available CUDA one. Applying
changes in place removes the failure the provisioning record was written
around, which is what lets the product run the repair on consent instead of
only describing it.

## Consequences

- A host installed or repaired this way upgrades with plain
  `uv tool upgrade vaultspec-rag` and stays on CUDA; no command has to be
  rebuilt between releases.
- An upgrade leaves the running service on the previous release until it is
  restarted; the release-compatibility refusal already names the restart, and
  the upgrade command is printed together with it.
- First-match trusts the PyTorch index for every package it mirrors, and a
  mirrored package may resolve to an older version that still satisfies its
  requirement. The index is already trusted for torch.
- Where no CUDA build satisfies a future torch requirement, first-match falls
  through to PyPI; on Windows that is a CPU build, caught by the start
  preflight and the post-install verification rather than prevented.
- MCP adapters launched through uvx stop sharing the host environment once its
  receipt carries the options, so their cached environments can drift from the
  host's release (`2026-09-26-tool-upgrade-cycle-research` F7). Tracking the
  host release there is a follow-on decision.
- The receipt shape is a uv behaviour, pinned by the proof harness in
  `2026-09-04-cuda-provisioning-adr` D6; a uv release that stops persisting the
  options fails those tests.
