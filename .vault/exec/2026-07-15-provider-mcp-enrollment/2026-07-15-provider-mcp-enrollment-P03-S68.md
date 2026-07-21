---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S68'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace provider-mcp-enrollment with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S68 and 2026-07-15-provider-mcp-enrollment-plan placeholders are machine-filled by
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
     The Close every S67 review finding with strict shared deadlines, race-safe startup publication, and child-incarnation proof and ## Scope

- `service environment`
- `HTTP transport`
- `service discovery`
- `startup fixture`
- `managed Qdrant identity and teardown`
- `real Windows and POSIX regressions`
- `focused gates`
- `documentation`
- `and formal review` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Close every S67 review finding with strict shared deadlines, race-safe startup publication, and child-incarnation proof

## Scope

- `service environment`
- `HTTP transport`
- `service discovery`
- `startup fixture`
- `managed Qdrant identity and teardown`
- `real Windows and POSIX regressions`
- `focused gates`
- `documentation`
- `and formal review`

## Description

- Restore every environment mutation after partial context-entry failure.
- Enforce one monotonic deadline across HTTP authentication recovery and retry.
- Serialize every service-status writer through one cross-process lock and
  unique atomic replacement.
- Publish daemon and managed-Qdrant identity before model warming, preserving
  authoritative daemon and attached-child identity across parent writes and
  heartbeats.
- Reserve failure-teardown grace inside the shared model-to-readiness startup
  deadline.
- Bind managed-Qdrant cleanup to owner and child process-incarnation witnesses,
  image, loopback listener, pinned version, storage, and readiness.
- Bound Windows process-start, image, listener, termination, and child-reaping
  inspection by the caller's remaining deadline.
- Add real Windows and WSL regressions for every corrected race, timeout,
  identity, and teardown boundary.
- Update the service-discovery contract and record independent review evidence.

## Outcome

All five S67 findings and every later independent-review finding were
implemented with real-behavior regression coverage. Focused Windows evidence
passed for environment restoration, HTTP recovery deadlines, cross-process
status locking, parent/daemon publication races, readiness-expiry teardown,
subsecond termination, and managed-Qdrant identity and orphan handling. Fresh
WSL evidence passed for attached identity through a later heartbeat, restart
publication failure cleanup, complete ordinary-orphan witness rejection, and
forced-stop child-incarnation rejection.

Repository Ruff, BasedPyright, Ty, and diff-integrity checks passed after the
latest focused corrections. The fourth independent formal review is the
remaining S68 closure gate; the complete platform release campaign remains
assigned to S69 and receives no carried runtime credit from this step.

## Notes

The first formal review found seven defects beyond the original S67 findings;
the second found three additional medium-severity deadline and attached-identity
defects. The third found two high- and three medium-severity gaps in live-owner
proof, late Windows spawn cleanup, pre-yield rollback, reaper witness timing,
and process-creation accounting. Each finding was accepted and corrected before
broader testing.

No pull request, approval, merge, tag, package publication, release, or ambient
installed-service mutation was performed. Failed test-owned processes were
identified and cleaned explicitly; unrelated installed services were left
untouched.
