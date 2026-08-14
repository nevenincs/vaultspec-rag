---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:98d023248b1446590b1d58ade98d0c667799bd2b130ca5cb33e9ac43a4c190bd'
step_id: 'S16'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Emit exactly one structured envelope on every exit path of the verb in JSON mode, refusal and success alike

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

Emit exactly one structured envelope on every exit path of the verb in JSON mode - refusal, preview, and success alike - so no exit ever leaves stdout empty or writes twice.

## Outcome

Every `--json` exit path emits exactly one envelope.

- Missing archive and `--json`-without-`--yes` converge on the group's existing single-envelope error helpers.
- An unreachable server emits one envelope from the shared storage-op wrapper.
- Success, preview, and refusal each render one envelope through `_render_restore`.

A refusal emits `ok: false` with the domain's own reason as `error`, its operator wording as `message`, and the full outcome still under `data`. A broker branches on `error` and gets the cause, not a generic failure with the reason buried.

That is deliberately stricter than the sibling `delete` verb, which renders its own `failed` status as `ok: true` and exits zero. Restore is the verb that writes into a namespace, so a refusal it reports as success is the more expensive mistake.

Writing the refusal wording surfaced a real gap. An applied restore is refused on Windows by a shared constant, and that reason had no entry, so it reached the operator as a bare token echoed back. Every reason `restore_archive` can return now has a sentence, and `test_every_reason_the_domain_can_return_has_operator_wording` enumerates them from the domain module so a newly added reason is caught rather than remembered.

## Notes

The refusal envelope is deliberately stricter than the sibling `delete` verb, which renders its own `failed` status as `ok: true` and exits zero. That is a gap in `delete` rather than a pattern worth matching: restore writes into a namespace, so a refusal reported as success is the more expensive mistake. Reconciling `delete` is not in this plan's scope.
