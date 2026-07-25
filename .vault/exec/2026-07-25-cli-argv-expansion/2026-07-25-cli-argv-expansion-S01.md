---
tags:
  - '#exec'
  - '#cli-argv-expansion'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-cli-argv-expansion-plan]]"
---

# Route every program invocation through one call that disables the command-line rewriting pass

## Scope

- `src/vaultspec_rag/cli/_app.py`
- `src/vaultspec_rag/cli/__init__.py`
- `src/vaultspec_rag/__main__.py`

## Description

- Locate the rewriting pass empirically before designing anything. A plain
  script printing its arguments received the quoted pattern intact from both
  PowerShell 7 and Git Bash; the same interpreter running the package as a
  module reproduced the expansion. That ruled out both shells and the
  console-script launcher and placed the pass inside the process, in click's
  own command-line handling.
- Add `run_cli` to `cli/_app.py`, invoking the application with the expansion
  pass disabled, and export it from the package.
- Point the package execution shim in `__main__.py` at `run_cli`, preserving
  the interrupt guard around the import that the shim exists for.
- Point the module's own execution guard in `cli/__init__.py` at `run_cli` so
  no bare invocation of the application remains.

## Outcome

The reported command now reaches the search service with its pattern intact and
returns a real answer from it. Measured before and after on the same box: the
released build reports the pattern as a wall of unexpected filenames, the fixed
build validates the filter and queries the service.

The keyword lands on a named parameter of click's `main` rather than in the
context, and the pass it disables is guarded by an operating-system check
upstream, so the change is inert off Windows.

## Notes

The original report attributed the expansion to the packaged console-script
wrapper or the C runtime and suggested rebuilding the wrapper. That was wrong,
and following it would have produced no fix. The measurement that settled it -
same interpreter, same directory, same quoted argument, one invocation through
a script and one through the module - is worth repeating before trusting any
claim about where an argument was rewritten.

Home shorthand is no longer expanded for the few path-typed options that had no
expansion of their own, which is a visible failure rather than a silent one and
is recorded in the decision's consequences.
