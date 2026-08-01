---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:767f67f639c318746fb772422a9725e6649610e6acf8104d557274d27f5a53f8'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `W01.P02.S05 real owner proof`

## Scope

Intent, test-integrity, and authority review of the real-process proof for owner-only machine
discovery mutation.

## Findings

No critical, high, medium, or low findings remain. The test imports the production lease and
pointer primitives directly. Its competing holder is a real interpreter child holding the
real isolated OS advisory lock; no fake, mock, stub, patch, monkeypatch, skip, or expected
failure substitutes for ownership behavior.

The proof first establishes a real sentinel through a retained owner, then releases that
lease and observes refusal against a distinct live holder PID. Both stale-lease publication
and deletion raise and the sentinel bytes still decode to the original payload. Cleanup
targets only the fixture-created holder and positively observes lock release before the new
owner is acquired.

The successor lease additionally rejects a foreign payload PID, replaces the sentinel,
leaves no operation-temporary file, and deletes only while ownership remains active. The
test therefore covers authorization, payload identity, atomic replacement, cleanup, and
owner success without duplicating production logic.

Status: **PASS**. The owner-lease phase is complete with no unresolved finding.

## Recommendations

Proceed to heartbeat convergence. Thread the retained lease through lifecycle state instead
of adding another PID-derived authorization path.
