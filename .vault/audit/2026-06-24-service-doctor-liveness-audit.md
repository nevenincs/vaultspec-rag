---
tags:
  - '#audit'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---



# `service-doctor-liveness` audit: `doctor live-truth + flapping remediation review (PASS)`

## Scope

Reviewed commit `ffee70e` (GitHub #204 residual) against its ADR and plan: the doctor two-axis report and honest `ready`, the breakaway detach-or-fail-loud remediation, the confirmed-dead unlink guard, and the no-mock tests. Confirmed `_machine_lock.py` and `server/_lifespan.py` are untouched (F6/F7 deferred to the singleton campaign). Read-only review; the orchestrator independently re-ran ruff/ty and a 277-test regression (process/singleton/lifecycle/CLI) plus the 11 doctor/flapping tests.

## Findings

**Verdict: PASS - no Critical or High findings. The doctor `ready` is honest across all cases (no daemon / live healthy / dead / stale / local-only) and `/readiness` route parity with `get_readiness()` is preserved; the breakaway path never silently produces a shell-bound daemon and leaks no fd; the unlink guard gates all three unlink sites and cannot false-positive on a live pid (it uses a direct OS liveness probe, not the fuzzy identity heuristic).**

## doctor-exit-code-backcompat | medium | server doctor now exits non-zero when not ready, including the pre-install no-daemon case

The prior `server doctor` always exited 0; the new verb raises `typer.Exit(1)` whenever `overall_ready` is False, which now includes a pure pre-install, deps-not-ready, no-daemon run. A CI/provisioning step that ran `doctor` as a non-gating informational probe and relied on exit 0 will now see a non-zero exit before install completes. This is arguably the more honest contract (and the ADR's intent), but it is a caller-visible behavior change that should be a deliberate, documented decision - confirm no bundled install/CI flow treats a pre-install `doctor` exit as fatal, or note it in release notes.

## doctor-render-heartbeat-isinstance | low | heartbeat-age isinstance check would accept bool

`_render_live_service_axis` uses `isinstance(heartbeat_age, int | float)`, which is True for `bool`. The value originates from `_heartbeat_age_seconds` (`float | None`), so a bool can never arrive; harmless, but the `not isinstance(value, bool)` guard used elsewhere would be more consistent.

## breakaway-test-naming | low | test file name over-promises relative to what it asserts

`test_daemon_survives_shell_exit.py` does not reproduce shell-exit survival (correctly, per its honest docstring - that needs the Windows host); it asserts the spawn never silently produces a shell-bound daemon. The name slightly over-promises. The plan step named the file, so this is cosmetic.

## Recommendations

Resolve the MEDIUM before/with PR: make the doctor exit-code change a deliberate, documented decision (confirm no bundled CI/install flow treats a pre-install `doctor` non-zero exit as fatal; otherwise gate the non-zero exit to the daemon-expected case). LOW notes are optional polish.

## Codification candidates

None this review. The ADR's `doctor-separates-installed-from-running` and `never-unlink-live-discovery-on-ambiguous-identity` are candidates only, promoted after the constraint holds across a full execution cycle.

## Resolution

`doctor-exit-code-backcompat` (MEDIUM) ADDRESSED: the non-zero exit is now gated to the daemon-expected-but-dead case (`present and not live`); a pre-install / no-daemon run keeps exit 0 even when dependencies are not ready, and the `ready`/`ok` fields still report the honest verdict. The doctor test was updated accordingly. `doctor-render-heartbeat-isinstance` (LOW) ADDRESSED: added a `not isinstance(..., bool)` guard on the heartbeat-age render. `breakaway-test-naming` (LOW) acknowledged and kept (cosmetic; the docstring is honest about what is asserted).
