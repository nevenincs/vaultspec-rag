---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
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

# `large-index-resilience` audit: `independent closing review — passed with two follow-ups`

## Scope

The mandatory closing review of the large-index-resilience plan, performed by an independent reviewer with no authorship in the work. Recorded here because the plan fixed a silent data-loss defect and a self-perpetuating index cascade, so its resume, rollback, and retirement logic warranted adversarial scrutiny before the plan is called closed. Verdict: PASS, with two follow-ups that do not block closure.

## Findings

### central-claim-holds | none | The checkpoint and resume ordering that carried the data-loss defect is correct, verified directly

The plan's load-bearing claim holds under independent check. Re-opening a source-digest-drifted path deletes the published store points BEFORE clearing the ledger evidence, so an interruption between the two steps replays as a clean no-op: the path is still recorded indexed at the old digest, the resumed attempt re-detects the drift, finds no points left to delete, and re-opens. The obsolete-delete path uses the same safe order. Nothing strands ledger units against deleted points on the paths this plan owns. The data-loss fix itself is exemplary - a deletion that restores original semantics, the sibling query examined rather than assumed, the bounded-scan intent restored by an idempotently backfilled index, and every guard proven by neutering the repair and watching the test fail with the incident's own symptoms.

### hard-crash-skips-retirement-counter | medium | A hard crash leaves a generation resumable without charging the retirement counter, so a deterministic hard-crash input livelocks forever

This is a gap in the plan's own resilience thesis, so it is tracked rather than waved. The retirement mechanism bounds only GRACEFUL failure: the consecutive-failure counter advances only in the generation-finish path, which runs only from the exception handler. A hard crash - an OS out-of-memory kill, a native tree-sitter or torch segfault, power loss, an external kill - skips that handler entirely, leaves the generation in the RUNNING state, and is resumed on the next attempt without the counter being charged. There is no stale-RUNNING reclaim and no job-level attempt cap. So an input that deterministically hard-kills the process before the next resource checkpoint samples - a file that reliably triggers the OS OOM-killer, say - resumes, crashes, and resumes again without ever retiring. The mechanism is confirmed; the trigger is plausible rather than demonstrated. It is partially self-mitigated: the memory-budget work converts a CUDA-ceiling breach it CATCHES into a typed error that does charge the counter, so the caught-CUDA case is bounded - but an RSS spike killed before the next checkpoint, and native segfaults, are not. This is liveness, not corruption: the run gets stuck, no data is lost. Remediation: charge a resume against a durable per-generation counter when a RUNNING generation is picked up, or add a stale-RUNNING reclaim with an attempt cap.

### rollback-point-survival-pre-existing | low | A separate rollback regression remains open, disclosed by the author, needing its own bisect

Recorded so that "large-index-resilience closed" is not misread as "the rollback path is clean." The data-loss commit message itself discloses a distinct open regression: a point surviving a failed attempt that should have been rolled back, which predates the plan's work by a wide margin. It is separate from the intentional, correct, flip-to-red-proven point RETENTION in the checkpoint-resume contract (a failed attempt keeps its storage-confirmed points for resume, by design). This is the accidental survival of a point that should have been removed - pre-existing and outside this plan's introduced scope, hence low, but it needs the bisect the author called for.

## Recommendations

Close the plan on this PASS. The introduced work is sound: the data-loss fix, the resume/re-open ordering, the generation retirement for graceful failure, the bounded resilience surface, and the memory-budget ceilings all hold under independent review, and the guards are non-vacuous.

Open the hard-crash retirement gap as a named liveness follow-up rather than folding it silently into "closed": it touches the plan's own thesis (a generation that cannot be retired is not resilient against every failure mode, only graceful ones), and its remedy - a durable resume-charged counter or a stale-RUNNING reclaim with an attempt cap - is a bounded, testable change. Whether to fix it now or schedule it is a scope decision for the plan owner.

Track the pre-existing rollback point-survival as its own bug awaiting the bisect its discoverer called for. It is not this plan's to fix, but a closing record should name it so the rollback path is not assumed clean.

Neither follow-up blocks closure: both are recorded, one is liveness-with-partial-self-mitigation on a plausible-not-demonstrated trigger, the other is pre-existing and out of scope.
