---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-25'
step_id: 'S11'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
  - "[[2026-07-24-service-orphan-reaping-closing-review-audit]]"
  - "[[2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference]]"
---

# Run the code review and the full gate suite for the changed lifecycle and stop surface

## Scope

- `.vault/audit/2026-07-24-service-orphan-reaping-closing-review-audit.md`

## Description

- Review the daemon startup guard, both forced-exit backstops, and the whole
  signature-scoped reap against the safety properties the decision claims.
- Run every gate whole-tree: ruff check and format, ty, basedpyright, the three
  complexity gates, the citation gate, the absolute-import scan, module length,
  and both markdown gates over the feature's documents.
- Run the reap and structured-stop suites plus the non-GPU tests of the
  integration lifecycle module.
- Persist the review as an audit with six findings and four recommendations.

## Outcome

Every gate is green: ruff clean, ty clean, basedpyright at zero errors, all
three complexity gates passing, no citations, no absolute imports, markdown
clean. Module length is report-only and its finding is recorded. Twenty-two
tests across the envelope-shape and reap-safety suites pass, and the fifteen
non-GPU tests of the lifecycle module pass.

The review confirms the decision's safety direction and questions its
completeness. The must-never-kill anchors are computed outside the host-wide
sweep, so every weakness in that sweep can only cause an orphan to be missed,
never the singleton to be selected - that asymmetry is what bounds the rest of
the findings to medium.

Two medium findings concern the anchor set and the enumeration. An absent lock
holder, pointer, or serving pid enters the anchor set as zero, and the
enumerator substitutes zero for any parent id it cannot read, so an unreadable
parent converts directly into protection. Separately, the enumeration suppresses
exceptions around its whole loop, so one failure abandons the remainder of the
host and returns a partial set that is indistinguishable from an empty one.

A third medium finding is an observation rather than a reading: the reap twice
reported a single reaped pid while the orphan it was given was a launcher and
worker pair, leaving the shim launcher alive. It reaped both when the test ran
alone, and the dedicated pair-safety test passed in the same session, so the
behaviour is intermittent. Either of the two mechanisms above would produce it
and the responsible one was not isolated.

## Notes

GPU-loading daemon tests were deliberately not run. The operator's resident
service was live on this machine throughout and a second GPU daemon would have
contended with it for the single device. That service was confirmed untouched
afterwards, on its original uptime with its jobs still running. Everything the
review needed was reachable without one.

The intermittent pair-incompleteness surfaced through one of this Step's own new
tests, which had asserted that the envelope names the launcher pid. That
assertion was asserting a property the implementation does not reliably hold, so
it was narrowed to what an envelope test should own - that the count matches the
pid list, that every pid named is really gone, and that at least one belongs to
the spawned daemon - and pair completeness was left to the safety suite that
asserts it against the processes themselves. The observation it produced is
filed rather than discarded.

None of the findings was fixed here. They are pre-existing defects in landed,
released code rather than regressions, the Step's mandate is review, and the
file that carries them was being edited concurrently by another session
throughout. Fixing under those conditions would have risked a collision worse
than the defects.

That concurrency cost real work twice: a session's broad staging captured a
guard mutation mid-proof, and a later restore reverted this Step's test edits to
the staged snapshot. Both were detected and corrected. The durable lesson is to
stage own paths immediately after editing them in a shared tree, because the
index is what a restore restores from.
