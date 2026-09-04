---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:ffa4ebfc6739b846c3d30d66d45361874c598f7f5187daf9ba14d106c467d545'
step_id: 'S06'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Separate repair consent from the file-overwrite flag and constrain repair scope to the torch wheel, preserving installed version and receipt extras

## Scope

- `src/vaultspec_rag/commands/_install.py and src/vaultspec_rag/cli/_install.py`

## Changes

- `M src/vaultspec_rag/commands/_tool_torch.py`
- `M src/vaultspec_rag/commands/_install.py`
- `M src/vaultspec_rag/cli/_install.py`
- `M src/vaultspec_rag/tests/test_tool_torch_repair.py`
- `M .vault/adr/2026-09-04-cuda-provisioning-adr.md`

## Notes

The Step was written to separate repair consent from the file-overwrite flag.
Execution found there is no longer anything to consent to: the previous Step
removed the replacement, so the prompt guarded a report. It is removed rather
than re-flagged, and `DECLINED`, `SKIPPED_NON_TTY` and `SKIPPED_EOF` go with
it, since none is reachable without a mutation to refuse. A defective tool
environment is now diagnosable from a non-interactive run, which the consent
gate previously made impossible - it exited 2 before saying anything useful.

`--no-tool-repair` replaces consent as the only choice that still changes
anything: it skips the check itself.

Scope is constrained where it actually mattered, in the request handed over.
`_tool_package_requirement` pins the installed version and reuses the extras
the receipt records, so the command no longer tells an operator to upgrade the
tool and adopt this build's extras while fixing a torch wheel. An environment
recording neither falls back to the bundled specification.

The ADR's D3 was amended in place to record the consent change and why, per the
template's rule that a refinement rewrites the accepted record rather than
superseding it.

Guard proof: dropping the version pin from the handed-over request failed
`test_the_handed_over_command_pins_the_version_and_keeps_recorded_extras` on
its equality assertion. Restored; zero MUTATION markers remain. Gates: ruff,
ty, 19 repair and provisioning tests, 32 CLI install tests, and the 183-test
install suite green.
