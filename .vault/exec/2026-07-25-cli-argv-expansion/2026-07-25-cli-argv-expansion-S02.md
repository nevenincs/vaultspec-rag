---
tags:
  - '#exec'
  - '#cli-argv-expansion'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S02'
related:
  - "[[2026-07-25-cli-argv-expansion-plan]]"
---

# Guard the argv path with subprocess tests and prove the delivered pattern filters real results

## Scope

- `src/vaultspec_rag/tests/test_cli_argv_expansion.py`
- `src/vaultspec_rag/tests/test_cli.py`

## Description

- Establish why the suite never caught this: every in-process CLI test invokes
  through a runner that supplies its own argument list, and the rewriting pass
  runs only over a command line the parser reads for itself. Roughly two
  hundred call sites are all on the unreachable side.
- Add subprocess guards that run the CLI from a seeded workspace, since the
  glob resolves against the working directory and a pattern matching nothing
  would pass whether or not the pass is disabled.
- Cover three limbs. A repeated pattern option must keep its glob, asserted by
  the seeded filenames being absent from the output and the run producing its
  structured filter rejection. A scalar option value carrying a variable
  reference, and one carrying a home shorthand, must arrive exactly as typed -
  asserted against the value the rejection quotes back, which makes what the
  parser received directly observable.
- Cover the filtering itself, which had no test at all: an include pattern
  keeps only its subtree, an exclude pattern drops one, and a substituted file
  list is not the filter the pattern was.
- Remove a stale comment in an existing subprocess scenario that avoided glob
  metacharacters to work around the defect this step closes.

## Outcome

Six tests, all passing. The whole processor-only tier passes with them.

Both directions were checked in one sequence. Re-enabling the pass at the
single invocation site failed all three argv guards on their own assertions,
not on collection or import: the pattern case on `src/**` having become the two
seeded filenames, the variable case on the reference resolving to the exported
value, the home case on the shorthand resolving to an absolute path. Restoring
it passed all six. No mutation was left on disk, and both directions are
recorded in the test module for the next reader.

## Notes

The fourth filtering test was wrong on its first draft and the failure was
informative. It asserted that a substituted list carrying the local path
separator could not match stored paths, which is false on this platform:
`fnmatch` normalises case and separators on Windows, so the two forms match.
The test was rewritten onto the real harm, which is also the portable one - a
substituted list names only what sat next to the caller, so anything else the
pattern covered is dropped silently, and the search still returns results and
reads as successful.

Two type-checker findings remain in an untouched test module unrelated to this
work; they predate it and were left alone.
