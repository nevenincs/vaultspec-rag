---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# `storage-autoprune-safety` `P03` summary

Both Steps complete (S10 implementation, S11 tests), executed in
parallel with P01/P02 by a dedicated executor, one commit per Step.

- Modified: `src/vaultspec_rag/cli/_service_lifecycle.py`
- Modified: `src/vaultspec_rag/tests/test_cli_server_stop.py`

## Description

Every service termination is now attributable from one record:
`_initiator_fields()` carries the terminating process' pid, bounded
command line, and cwd onto the `cli_terminate` audit event - now emitted
on ALL platforms, not only win32 - and into exactly the three
terminating stop envelopes (`stopped`, `stopped --port`, `reclaimed`);
`already_stopped` and `cleaned` deliberately carry none. This closes the
forensic gap that made the 2026-07-13 deliberate stop look like a prune
bug for hours. Verification: 17 stop-suite tests green including a live
audit-line test against a real non-python child under isolated singleton
paths; audit passed with the argv-no-secrets constraint documented.
