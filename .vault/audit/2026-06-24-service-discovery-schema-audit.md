---
tags:
  - '#audit'
  - '#service-discovery-schema'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-service-discovery-schema-plan]]"
---



# `service-discovery-schema` audit: `discovery-file schema/version/timestamp contract review (PASS)`

## Scope

Reviewed commit `a201f6c` (GitHub #190) against its ADR and plan: the shared `(schema, version)` discriminator and `_discovery_timestamp()` helper, both writers (`_write_service_status` and `_heartbeat_tick_sync`), the consumer-facing schema doc, and the no-mock tests. Read-only review by a `vaultspec-code-reviewer` persona; the orchestrator independently re-ran ruff/ty/pytest (34 passed).

## Findings

**Verdict: PASS - no Critical or High findings. All five ADR decisions (D1-D5) and every plan step land correctly: both writers route through one shared timestamp helper and emit identical `(schema, version)`, back-compat is additive and safe (every production reader uses per-key `.get`, and the `started_at` microsecond->second shrink is tolerated by `datetime.fromisoformat`), atomicity is preserved in both writers, no import cycle is introduced, and the docs match the emitted fields.**

## test-coverage-unversioned-upgrade | medium | the older/unversioned-parent upgrade path is exercised but not asserted

The heartbeat unconditionally re-asserts `schema`/`version`, so an unversioned older-parent file IS upgraded on the first tick (verified by inspection). But the new dedicated test seeds the file via the current parent writer (already versioned), so it proves preservation, not upgrade; the pre-existing unversioned-file tick test asserts only `last_heartbeat`/`pid`/`parent_pid`. Recommend one added assertion that `schema`/`version` appear after a tick on a bare `{pid, port, started_at}` file. Coverage gap, not a defect.

## mirrored-staleness-constant | low | CLI keeps a hand-mirrored stale-threshold constant now slightly more redundant

`cli/_process.py` mirrors `_HEARTBEAT_STALENESS_SECONDS = 60` to avoid importing the server package on the CLI hot path - sound and pre-existing. The new machine-readable `stale_after_s` field makes the mirror marginally more redundant; a future cleanup could have the CLI status reader prefer the file's value. Out of scope for #190.

## Recommendations

Optional follow-ups only; nothing blocks merge. (1) Add the unversioned-upgrade assertion (MEDIUM). (2) Consider, in a later change, having the CLI staleness reader consume the file's `stale_after_s` rather than its mirrored literal (LOW).

## Codification candidates

None this review. The ADR's `discovery-file-is-a-versioned-interface` is a candidate only and is promoted after the constraint holds across a full execution cycle, per the codify discipline.
