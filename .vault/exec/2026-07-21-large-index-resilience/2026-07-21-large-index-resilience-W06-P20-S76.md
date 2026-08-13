---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:6e0b5fbe5630e08f54a4fc48dac935470a8cfcf4d669f9be6196c50e9afee409'
step_id: 'S76'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Repoint every subprocess test off the resident tier it inherited, and make declaring both a collection-time violation

## Scope

- `src/vaultspec_rag/tests/integration/`
- `src/vaultspec_rag/tests/_tier_gate.py`
- `src/vaultspec_rag/tests/test_marker_discipline.py`

## Description

- Established where the second tier actually came from: almost none of the 67 tests wrote it, and it arrived from a module-level default, a class decorator, or a class-level default depending on the module.
- Repointed each module by shape - all-subprocess modules declare the tier once at module level; mixed modules drop the inherited default and let each test name its own tier; redundant decorators removed.
- Made declaring both a collection-time violation beside the existing untiered and fast-beside-slow rules, so the untangle cannot drift back one module at a time.
- Kept the runtime selection gate: a selection can still hold both tiers without any test declaring both, so the two checks answer different questions.
- Updated the guard that had asserted the pairing was intended, and the rationale that described the suite as it was before this change.

## Outcome

Every collected test's effective markers were compared before and after, taken from the collector rather than re-derived: the same 5,050 node ids, exactly 67 changed, every one of them losing the resident tier and gaining nothing, none left declaring both, none untiered. Lane counts follow - the resident tier 723 where it was 790, the subprocess tier 67, the fast lane and the performance tier unchanged - and the resident selection is no longer refused, because it no longer selects what it could not run. The fast lane passed 4,238 with 2 skipped.

## Notes

Two faults in the transformation, both caught by verification rather than by reading the diff.

The first inserted a decorator below the definition line rather than above it on tests that carried no decorators. The second walked only classes, so tests defined inside a platform conditional were invisible; removing the module default orphaned them, and the symptom was the whole suite ceasing to deselect on any marker expression at all. Each was restored from the committed state and the transformation rerun.

The lesson is in how it was verified rather than in either fault: an approximation of mark inheritance was what produced both, so the check was moved onto the collector's own resolution, which is the thing that decides what runs.
