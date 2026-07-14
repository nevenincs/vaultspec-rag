---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S10'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-autoprune-safety with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S10 and 2026-07-14-storage-autoprune-safety-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Carry initiator identity (pid, argv command line, cwd) on the cli_terminate audit event and in the stop and stop-port envelope data and ## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Carry initiator identity (pid, argv command line, cwd) on the cli_terminate audit event and in the stop and stop-port envelope data

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Added `_initiator_fields()` returning the terminating process' own pid,
  bounded argv command line (truncated at 300 chars), and cwd as string kv
  fields.
- Rewrote `_terminate_and_confirm` to emit the `cli_terminate` shutdown audit
  line on every platform (previously win32-only), reporting the real platform
  and carrying the initiator fields; the win32 rationale comment is preserved.
- Threaded `_initiator_fields()` into the `_stop_success` envelope data for the
  three paths that actually terminate or reclaim a process: `stopped` (default),
  `stopped` (`--port`), and `reclaimed`. The idempotent `already_stopped` and
  stale-state `cleaned` envelopes are left unchanged, since nothing was
  terminated.

## Outcome

A single shutdown log line and the terminating stop `--json` envelopes now
answer "who stopped the machine service" with the initiator pid, command line,
and cwd. Ruff, ruff format, and basedpyright all pass on the touched file.

## Notes

The audit line platform field now reflects `sys.platform` rather than a
hardcoded `win32`, keeping the mirror line honest on POSIX where it is
additive to the daemon's own clean-shutdown record. No skipped work.
