---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:42180b7c296188e9a8897f907f4f00fc4c4dbf260e276251dc9a3acec7d0d4b0'
step_id: 'S17'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace archive-restore-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S17 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Cover the verb's refusal exit codes and its single-envelope contract, including the JSON-without-yes refusal the other destructive verbs enforce and ## Scope

- `src/vaultspec_rag/tests/test_storage_adversarial.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover the verb's refusal exit codes and its single-envelope contract, including the JSON-without-yes refusal the other destructive verbs enforce

## Scope

- `src/vaultspec_rag/tests/test_storage_adversarial.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Covered in `src/vaultspec_rag/tests/test_storage_adversarial.py` by `TestRestoreRefusesInOneEnvelope`, plus `server.storage.restore` added to the existing JSON-without-yes parametrization the other destructive verbs already share.

Asserted: a missing archive exits 2 with one `archive_not_found` envelope and without opening a client; a complete archive against a dead port exits 3 with one `service_not_running` envelope; each of the four domain refusals renders one envelope with `ok: false`, the reason as `error`, and operator wording that is a sentence rather than the token echoed back; a preview names the exact destination collections; and every reason the domain can return has wording.

Stdout lines are counted rather than parsed, so a traceback or a stray human line on the result channel fails the test - zero or two envelopes is the defect being pinned, not just a malformed one.

## Notes

Failure proofs, each applied alone and reverted:

| Guard | Mutation | Observed |
| --- | --- | --- |
| missing archive | dropped the `is_dir` guard | exit 3, `service_not_running` instead of `archive_not_found` |
| refusal envelope | rendered refusals as `ok: true` | all four parametrized cases failed on the `ok` assertion |
| preview list | reported the archive's own names | destination assertion failed |
| reason completeness | removed the Windows entry | failed naming exactly that reason |

One mutation went astray and is worth recording. The first attempt at the preview proof matched the `collections` line in `_render_delete` instead of `_render_restore`, and the restore test correctly stayed green - the mutation had not touched the code under test. It was re-applied against an anchor unique to the restore renderer, where it failed as intended. A mutation that changes nothing relevant proves nothing; a green run under one is not evidence.
