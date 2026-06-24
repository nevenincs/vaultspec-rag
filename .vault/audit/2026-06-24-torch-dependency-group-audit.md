---
tags:
  - '#audit'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-torch-dependency-group-plan]]"
---



# `torch-dependency-group` audit: `optional dependency-group placement review (PASS)`

## Scope

Reviewed commit `5e91195` (GitHub #186) against its ADR and plan: the `--torch-group` optional-value flag, the parameterised group write helper and target resolver, the location-bearing marker with legacy back-compat, the marker-recorded-surface uninstall, the warn-and-no-op-on-changed-target and inert-pin warnings, and the no-mock tomlkit tests. Read-only review by a `vaultspec-code-reviewer` persona; the orchestrator independently re-ran ruff/ty/pytest (143 passed).

## Findings

**Verdict: PASS - no Critical or High findings. The load-bearing correctness risk (marker back-compat and install/uninstall symmetry) is implemented correctly and proven by no-mock tests: a legacy boolean `true` marker uninstalls from project deps, a group-recorded marker uninstalls from its group, an unmarked user-declared torch (project or group) is never touched, and the default no-flag path is byte-for-byte unchanged. The `--torch-group` optional-value mechanism is robust (bare->dev, =x->x, omitted->project, and it does not swallow a following option), and the location-string round-trip is injection-safe.**

## empty-torch-group-accepted | low | an empty/whitespace --torch-group name is silently accepted

`--torch-group=` or `--torch-group ""` writes torch into an empty-named group (`[dependency-groups]` with a `"" = [...]` key). The round-trip is symmetric and reversible, but an empty group name is unusable (uv cannot enable `--group ""`). Consider rejecting an empty/whitespace group name in the CLI or `_group_dependencies` with a clear error. Optional.

## inert-pin-warning-only-on-fresh-apply | low | inert-pin reminder does not fire on an idempotent re-run already in the group

`_inert_pin_warning` fires only when torch is freshly `applied` to a group; re-running `install --torch-group dev` against an already-group-placed torch (`already`, same location) emits no reminder to enable the group. The warning is most needed on first apply, which is covered. Optional.

## uninstall-coupled-to-block-state | low | managed torch dep removal is gated on the cu130 block being removed (pre-existing, out of scope)

Uninstall removes the managed torch dep only inside the CANONICAL + block-REMOVED branch; if the cu130 block were independently removed while the marker remained set, the managed dep would be orphaned. This calling structure is pre-existing and unchanged by this commit (the diff only retargets which surface removal hits, not when it runs). Noted for a possible future fully-marker-driven removal; not a defect introduced here.

## Recommendations

Merge. Both actionable LOW findings are optional polish (reject empty group name; optionally emit the inert-pin reminder on idempotent group re-runs). The pre-existing uninstall/block coupling is a candidate follow-up if fully marker-driven removal is desired.

## Codification candidates

None this review. The ADR's `managed-dependency-marker-records-location` is a candidate only, promoted after the constraint holds across a full execution cycle, per the codify discipline.

## Resolution

`empty-torch-group-accepted` (LOW) ADDRESSED: `_group_dependencies` now rejects an empty/whitespace group name with a clear conflict, covered by `test_empty_torch_group_is_rejected`. `inert-pin-warning-only-on-fresh-apply` (LOW) ADDRESSED: the inert-pin reminder now also fires on an idempotent re-run when torch is already in the requested group, covered by `test_rerun_torch_already_in_requested_group_warns_inert_pin`. `uninstall-coupled-to-block-state` (LOW) deferred as pre-existing and out-of-scope.
