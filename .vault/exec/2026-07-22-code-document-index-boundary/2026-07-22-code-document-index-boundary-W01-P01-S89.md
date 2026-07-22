---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S89'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S89 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Verify invalid routing leaves real collections, sidecars, ledger rows, and caches unchanged and ## Scope

- `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify invalid routing leaves real collections, sidecars, ledger rows, and caches unchanged

## Scope

- `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py`

## Description

- Seed a real local code collection, metadata sidecar, and extraction-cache
  sentinel before exercising conflicting explicit ownership.
- Exercise both full and incremental public index operations and assert the
  collection, sidecar, and cache remain byte-for-byte unchanged.
- Invoke the public application programming interface in a fresh interpreter
  with model execution unavailable and verify routing refusal precedes model,
  store, or project-state acquisition.
- Exercise service job admission against invalid routing and compare the real
  canonical job snapshot and durable JSON state before and after refusal.

## Outcome

Invalid policy and conflicting ownership fail before observable mutation.
Existing collection identifiers, metadata bytes, cache bytes, canonical jobs,
durable job state, and the project storage directory retain their prior state.

Commit `b0236fe` lands the real collection, sidecar, cache, and durable-job
refusal coverage that supplies this step's implementation evidence.

The W01.P01 phase-boundary invocation passed all 50 policy, preprocessing,
fingerprint, and fail-closed tests, including four real-resource S89 cases.

## Notes

The tests use real temporary files, a real local vector store, and a fresh
Python subprocess. They contain no fake, mock, stub, patch, monkeypatch, skip,
or expected-failure shortcut. No CUDA execution or shared service storage was
used.
