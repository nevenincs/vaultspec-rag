---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S09'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
---

# Add a test that the reap clears a real lingering launcher-daemon orphan pair

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_orphan_reap.py`

## Description

- Ran the reap integration suite `test_qdrant_orphan_reap.py` on Linux and
  observed one failure: the reap target guard `pid_image_is_qdrant` classified
  the test's own python process as a qdrant target.
- Traced the false positive to the POSIX branch scanning the whole
  `/proc/<pid>/cmdline`, so any process whose argv merely names qdrant (a
  pytest run over the qdrant test file) matched.
- Fixed the guard to match the executable image only - the `/proc/<pid>/exe`
  basename, with `comm` as a world-readable fallback - mirroring the Windows
  tasklist image check, so the cmdline argv is no longer consulted.
- Re-ran the full file green and confirmed both platforms.

## Outcome

The reap integration guard test - spawning real lingering sleeper processes and
asserting the reap clears the orphan while sparing a live holder and any
recycled-pid non-qdrant process - passes 9/9 on both Linux and Windows. The
target-image guard is now correct on POSIX, closing a safety gap where the reap
could have hard-killed an unrelated process whose command line mentioned
qdrant. The negative guard `test_this_python_process_is_not_a_qdrant_target`
was observed to fail before the fix (returned a target where none exists) and
pass after, in one sequence.

## Notes

The guard fix landed as its own commit ahead of this record. No mocks: the
tests reap real subprocesses. Windows had always passed; the defect and its
regression coverage were POSIX-only.
