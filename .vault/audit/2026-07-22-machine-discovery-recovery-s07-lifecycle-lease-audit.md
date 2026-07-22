---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace machine-discovery-recovery with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `machine-discovery-recovery` audit: `s07 lifecycle lease`

## Scope

<!-- What was audited and why -->

Audited W01.P03.S07 against the approved ADR, research, reference, and plan. The
review covered retained `MachineLockLease` ownership from startup through
shutdown, synchronous heartbeat quiescence before cancellation of an
`asyncio.to_thread` caller, owner-only removal of both discovery views,
pre-yield cleanup and atexit retry registration, component teardown before the
last lease release, removal of obsolete cleanup APIs, and the focused real-file
and real-lock tests in `test_machine_discovery.py`,
`test_service_discovery_schema.py`, `test_server.py`, and
`integration/test_service_lifecycle.py`.

The current implementation correctly creates one `_DiscoveryPublisher` from
the acquired lease, threads it through phase publication, Qdrant identity
publication, heartbeat, and shutdown, installs the atexit hook before the first
publication or subordinate startup action, and calls `quiesce()` before task
cancellation. The publisher's `RLock` joins an in-flight synchronous heartbeat
and makes later ticks inert. Owner cleanup occurs while the retained lease is
live, and store teardown exceptions no longer release that lease.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### s07 lifecycle lease | {level} | {summary}

     followed by a paragraph carrying the detail. s07 lifecycle lease is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### s07 lifecycle lease | high | Qdrant stop can report success while the owned child survives

`_shutdown_components` now retains the lease when `_stop_active_qdrant` reports
failure, but the convergence signal is not authoritative. In
`QdrantSupervisor.stop`, a child that survives the bounded wait after `kill()`
only produces a log entry; the method then clears `_proc` and returns normally.
A timed-out output-drain join also returns normally. Consequently
`_stop_active_qdrant` returns `True`, clears the active supervisor, and permits
`release_machine_lock_lease` even though the owned process or its single-writer
log drain may still be live. This violates the ADR's release-last invariant and
allows a successor service to overlap resources that the prior owner failed to
tear down.

### s07 lifecycle lease | high | Focused lifecycle tests do not collect after compatibility API removal

The production compatibility wrapper `_unlink_status_file_silently` has been
removed, but `test_server.py` still imports and calls it. The focused pytest run
failed during collection with an unknown import, before any lifecycle assertion
ran. Ruff also reported the stale import's downstream unused import plus an
`Iterator` type-only import violation, and basedpyright reported two
unknown-symbol errors. This is a test migration regression, not a reason to
restore the compatibility wrapper. The same lifecycle-helper class still uses
`pytest.MonkeyPatch` in its shutdown test, contrary to the repository's
real-behavior test rule.

### s07 lifecycle lease | medium | Status-path resolution can bypass independent owner cleanup

`_DiscoveryPublisher.cleanup` resolves `_status_file_path()` before entering
its guarded, per-view cleanup attempts. If configuration or path resolution
raises, machine-pointer deletion is never attempted, the failure is not reduced
to the promised `False` convergence result, and `_shutdown_components` exits
before managed work, stores, and Qdrant are drained. `_publish_locked` has the
same pre-try path resolution despite its stated independent-view contract. Each
view must remain independently publishable and removable when resolution of the
other view fails.

### s07 lifecycle lease | medium | Failure-path coverage does not prove the release-last contract

The focused tests exercise real owner publication and idempotent cleanup, but
they do not demonstrate that the machine lease remains held after a real
Qdrant-stop non-convergence, a status-view cleanup failure, or a component
teardown failure. They also do not exercise the atexit retry after a transient
cleanup failure. Without those real-process and real-filesystem cases, the
highest-risk S07 ordering guarantees can regress while the happy path remains
green.

## Recommendations

<!-- Actionable recommendations -->

Make `QdrantSupervisor.stop` return or raise an authoritative convergence
outcome: do not clear `_proc` when the child is still alive, treat a surviving
post-kill wait and retained output drain as failures, and propagate that result
through `_stop_active_qdrant`. Release the machine lease only after confirmed
store, child-process, output-drain, and discovery convergence.

Finish the no-compatibility test migration by deleting the obsolete helper
import and test call, invoking `_DiscoveryPublisher.cleanup()` directly where
cleanup behavior is relevant, and replacing the remaining monkeypatch-based
lifecycle assertion with isolated real state and real owner resources. Re-run
the focused pytest, Ruff, and basedpyright commands until collection and all
checks pass.

Move status-path resolution into the status-view try block in both cleanup and
publication, log resolution failures there, and always attempt the
lease-authenticated machine-pointer operation independently. Add non-tautological
tests using real isolated filesystem permissions/lock contention and a real
supervised child process to prove cleanup retry, quiescence, failure retention,
and exact release-last behavior without mocks, patches, skips, or xfails.
