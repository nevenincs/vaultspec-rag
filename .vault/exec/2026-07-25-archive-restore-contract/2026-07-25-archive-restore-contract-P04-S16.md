---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:32d2e3fc47b303cd8844af652e0bc1f8899cc415974d392964fb486c340d1015'
step_id: 'S16'
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
     The S16 and 2026-07-25-archive-restore-contract-plan placeholders are machine-filled by
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
     The Emit exactly one structured envelope on every exit path of the verb in JSON mode, refusal and success alike and ## Scope

- `src/vaultspec_rag/cli/_service_storage.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Emit exactly one structured envelope on every exit path of the verb in JSON mode, refusal and success alike

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Every `--json` exit path emits exactly one envelope.

- Missing archive and `--json`-without-`--yes` converge on the group's existing single-envelope error helpers.
- An unreachable server emits one envelope from the shared storage-op wrapper.
- Success, preview, and refusal each render one envelope through `_render_restore`.

A refusal emits `ok: false` with the domain's own reason as `error`, its operator wording as `message`, and the full outcome still under `data`. A broker branches on `error` and gets the cause, not a generic failure with the reason buried.

That is deliberately stricter than the sibling `delete` verb, which renders its own `failed` status as `ok: true` and exits zero. Restore is the verb that writes into a namespace, so a refusal it reports as success is the more expensive mistake.

Writing the refusal wording surfaced a real gap. An applied restore is refused on Windows by a shared constant, and that reason had no entry, so it reached the operator as a bare token echoed back. Every reason `restore_archive` can return now has a sentence, and `test_every_reason_the_domain_can_return_has_operator_wording` enumerates them from the domain module so a newly added reason is caught rather than remembered.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
