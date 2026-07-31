---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S15'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Measure an incremental vault run over a stamp-churned corpus against the recorded pre-change baseline and record both figures

## Scope

- `src/vaultspec_rag/tests/integration/`

## Description

- Capture the pre-change baseline before the split fingerprint landed: copy this
  project's own vault corpus to a scratch root, full-index it, refresh the
  `modified:` stamp on every document, and time one unscoped incremental run.
- Re-run the identical measurement after the classifier was wired.
- Add `TestUnscopedEscalationConverges` as the standing regression, which asserts
  the same shape at test scale on every run.

## Outcome

Corpus: 2158 vault documents, every one stamp-churned, nothing else edited. One
unscoped incremental run, same machine, same GPU, same corpus.

|                       | before | after  |
| --------------------- | ------ | ------ |
| documents in corpus   | 2158   | 2173   |
| documents re-embedded | 2158   | 0      |
| payload-only updates  | 0      | 0      |
| wall time             | 86.3 s | 1.90 s |

Every document re-embedded before; none after. Forty-five times faster, and the
remaining two seconds are stat calls, parses, and digests - no GPU work at all.

The corpus grew by the fifteen execution records this plan produced, which is why
the two document counts differ; the comparison is unaffected, since the before
figure re-embedded 100% of its corpus and the after figure re-embedded 0% of a
slightly larger one.

The figure sits in the class the originating research measured: incremental vault
jobs spending hundreds of seconds to commit nothing.

## Notes

The first baseline attempt measured 180.7 s and was discarded. Its stamp helper
wrote with default newline translation, which reflowed every line of all 2158
files, so it measured a whole-corpus rewrite rather than a stamp bump. Both
figures above come from the corrected helper, which preserves line endings.

The full-index timings either side are not comparable and are deliberately not
quoted: the post-change full index shared the GPU with the guard-test suite.
Only the incremental figure was measured in isolation, and it is the figure the
plan asked for.

The standing test asserts the classification rather than a duration. A wall-time
assertion on shared hardware measures whatever else is running.

The after figure was re-taken once more following the review fixes, and it is
that re-take which is quoted. It is slower than the first post-change reading of
1.15 s: the ordinal census the payload branch now reads costs one extra scan, and
this run shared the machine with the unit suite. Both are still the same class of
answer - under two seconds against eighty-six, with no GPU work at all - and
quoting the slower, later, honestly-contended figure is the conservative choice.
