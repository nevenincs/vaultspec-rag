---
generated: true
tags:
  - '#index'
  - '#preprocess-sandbox'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - '[[2026-07-13-preprocess-sandbox-P01-S01]]'
  - '[[2026-07-13-preprocess-sandbox-P01-S02]]'
  - '[[2026-07-13-preprocess-sandbox-P01-S03]]'
  - '[[2026-07-13-preprocess-sandbox-P01-S04]]'
  - '[[2026-07-13-preprocess-sandbox-P01-S05]]'
  - '[[2026-07-13-preprocess-sandbox-P01-summary]]'
  - '[[2026-07-13-preprocess-sandbox-P02-S06]]'
  - '[[2026-07-13-preprocess-sandbox-P02-S07]]'
  - '[[2026-07-13-preprocess-sandbox-P02-S08]]'
  - '[[2026-07-13-preprocess-sandbox-P02-S09]]'
  - '[[2026-07-13-preprocess-sandbox-P02-S10]]'
  - '[[2026-07-13-preprocess-sandbox-P02-summary]]'
  - '[[2026-07-13-preprocess-sandbox-P03-S11]]'
  - '[[2026-07-13-preprocess-sandbox-P03-S12]]'
  - '[[2026-07-13-preprocess-sandbox-P03-S13]]'
  - '[[2026-07-13-preprocess-sandbox-P03-summary]]'
  - '[[2026-07-13-preprocess-sandbox-P04-S14]]'
  - '[[2026-07-13-preprocess-sandbox-P04-S15]]'
  - '[[2026-07-13-preprocess-sandbox-P04-summary]]'
  - '[[2026-07-13-preprocess-sandbox-adr]]'
  - '[[2026-07-13-preprocess-sandbox-audit]]'
  - '[[2026-07-13-preprocess-sandbox-plan]]'
  - '[[2026-07-13-preprocess-sandbox-research]]'
---

# `preprocess-sandbox` feature index

Auto-generated index of all documents tagged with `#preprocess-sandbox`.

## Documents

### adr

- `2026-07-13-preprocess-sandbox-adr` - `preprocess-sandbox` adr: `OS-sandboxed hooks replace consent as the server boundary` | (**status:** `superseded`)

### audit

- `2026-07-13-preprocess-sandbox-audit` - `preprocess-sandbox` audit: `adversarial security review of the hook-containment boundary`

### exec

- `2026-07-13-preprocess-sandbox-P01-S01` - Delete the trust store module and every reference to it
- `2026-07-13-preprocess-sandbox-P01-S02` - Remove the trust branch from load_preprocess_rules so rules resolve for any root, replacing the mode enforcement with the off kill switch and the unsandboxed escape hatch only
- `2026-07-13-preprocess-sandbox-P01-S03` - Retire trust_all, add VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED, and resolve the amended preprocess_mode (on-sandboxed default, off, unsandboxed)
- `2026-07-13-preprocess-sandbox-P01-S04` - Drop the trust and untrust verbs, repoint preprocess status at sandbox-backend availability, keep --no-preprocess and add the unsandboxed flag
- `2026-07-13-preprocess-sandbox-P01-S05` - Rework the preprocess-config unit tests off the trust store onto the resolve-for-any-root and kill-switch behavior
- `2026-07-13-preprocess-sandbox-P01-summary` - `preprocess-sandbox` `P01` summary
- `2026-07-13-preprocess-sandbox-P02-S06` - Create the HookSandbox abstraction: backend protocol, staged-input plus curated-env plus scratch-cwd contract, capability probe, and the fail-closed server-mode policy
- `2026-07-13-preprocess-sandbox-P02-S07` - Implement the Windows AppContainer backend with a kill-on-close Job Object, no network capability, and an ACL grant for the staged input dir
- `2026-07-13-preprocess-sandbox-P02-S08` - Implement the POSIX backends: bubblewrap with a Landlock-plus-seccomp fallback on Linux and a deny-default seatbelt profile on macOS
- `2026-07-13-preprocess-sandbox-P02-S09` - Route the runner subprocess launch through the resolved sandbox backend, preserving the timeout, output caps, and argv hygiene inside it
- `2026-07-13-preprocess-sandbox-P02-S10` - Unit-test the sandbox contract and each backend: staged-only filesystem read, denied network, denied secret env, process-tree teardown, and the fail-closed refusal when no backend resolves
- `2026-07-13-preprocess-sandbox-P02-summary` - `preprocess-sandbox` `P02` summary
- `2026-07-13-preprocess-sandbox-P03-S11` - Make the watcher change filter recognize preprocessable files independent of the removed trust state
- `2026-07-13-preprocess-sandbox-P03-S12` - Thread preprocess_skipped and preprocess_failures into the job record and the /jobs response so extraction failures are client-visible
- `2026-07-13-preprocess-sandbox-P03-S13` - Add the /reindex pre-flight signal reporting whether a root ships a preprocess config and whether hooks will run under the resolved sandbox
- `2026-07-13-preprocess-sandbox-P03-summary` - `preprocess-sandbox` `P03` summary
- `2026-07-13-preprocess-sandbox-P04-S14` - Prove end-to-end against real backends that a contained hook cannot read outside the staged dir nor open a socket, and that a worktree shipping a hook indexes its corpus through the service with no interaction
- `2026-07-13-preprocess-sandbox-P04-S15` - Document the sandbox model, the tri-state control, fail-closed behavior, and the removed trust surface across the README and preprocessing docs
- `2026-07-13-preprocess-sandbox-P04-summary` - `preprocess-sandbox` `P04` summary

### plan

- `2026-07-13-preprocess-sandbox-plan` - `preprocess-sandbox` plan

### research

- `2026-07-13-preprocess-sandbox-research` - `preprocess-sandbox` research: `containment replaces consent for non-interactive server hooks, and driving main green`
