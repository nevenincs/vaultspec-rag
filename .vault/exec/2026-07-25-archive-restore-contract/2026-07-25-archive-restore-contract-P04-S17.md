---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-25'
body_schema: 'body-v1'
body_hash: 'sha256:75b32b50d9e0ab43a6c2a157e1013b48ceea1f8776e36d23cd07fdba9f7f25f6'
step_id: 'S17'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Cover the verb's refusal exit codes and its single-envelope contract, including the JSON-without-yes refusal the other destructive verbs enforce

## Scope

- `src/vaultspec_rag/tests/test_storage_adversarial.py`

## Description

Cover the verb's refusal exit codes and its single-envelope contract, including the JSON-without-yes refusal the other destructive verbs already enforce.

## Outcome

Covered in `src/vaultspec_rag/tests/test_storage_adversarial.py` by `TestRestoreRefusesInOneEnvelope`, plus `server.storage.restore` added to the existing JSON-without-yes parametrization the other destructive verbs already share.

Asserted: a missing archive exits 2 with one `archive_not_found` envelope and without opening a client; a complete archive against a dead port exits 3 with one `service_not_running` envelope; each of the four domain refusals renders one envelope with `ok: false`, the reason as `error`, and operator wording that is a sentence rather than the token echoed back; a preview names the exact destination collections; and every reason the domain can return has wording.

Stdout lines are counted rather than parsed, so a traceback or a stray human line on the result channel fails the test - zero or two envelopes is the defect being pinned, not just a malformed one.

## Notes

Failure proofs, each applied alone and reverted:

| Guard               | Mutation                         | Observed                                                     |
| ------------------- | -------------------------------- | ------------------------------------------------------------ |
| missing archive     | dropped the `is_dir` guard       | exit 3, `service_not_running` instead of `archive_not_found` |
| refusal envelope    | rendered refusals as `ok: true`  | all four parametrized cases failed on the `ok` assertion     |
| preview list        | reported the archive's own names | destination assertion failed                                 |
| reason completeness | removed the Windows entry        | failed naming exactly that reason                            |

One mutation went astray and is worth recording. The first attempt at the preview proof matched the `collections` line in `_render_delete` instead of `_render_restore`, and the restore test correctly stayed green - the mutation had not touched the code under test. It was re-applied against an anchor unique to the restore renderer, where it failed as intended. A mutation that changes nothing relevant proves nothing; a green run under one is not evidence.
