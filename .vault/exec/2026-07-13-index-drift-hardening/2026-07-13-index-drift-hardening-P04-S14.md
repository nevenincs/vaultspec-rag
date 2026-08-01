---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:5bb46d857e3bee93673760afa8071b42e777c448385409cdb5ef24cc4fa23b3f'
step_id: 'S14'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# Document the tri-state, the trust flow, and the drift-epoch self-healing in the README and the server start help text, replacing every mention of the removed enable knob

## Scope

- `README.md`

## Description

- Add a "Preprocessing hooks" section to the README: on-by-default under
  trust-on-first-use, the `preprocess trust` flow, self-revoking trust on
  command edits, the tri-state env vars and their CLI flag mirrors, and the
  drift self-healing behavior for control-file edits.
- Rewrite the security-posture section of the preprocessing guide from the old
  "declared equals trusted" model to the TOFU model, keeping the
  treat-as-executable-config review advice.
- Add the two tri-state env vars to the configuration reference's
  preprocessing table.
- Add `preprocess trust`, `untrust`, and `status` to the CLI reference's verb
  index and body, mirroring the existing entry format, and note the
  `--no-preprocess` / `--preprocess-trust-all` flags.
- Remove every mention of the deleted enable knob from operator-facing docs.

## Outcome

README plus three docs files updated; no stale enable-knob or
"same trust model as the project's own code" framing remains in README.md or
docs/. The server-start help-text half of this step shipped with the P03 CLI
work (flag help plus the untrusted-config start notice), so this record covers
the documentation half.

## Notes

Documentation was drafted by a delegated executor and reviewed by the
orchestrator, who corrected one wording error in the security-posture section
(review-and-trust, not index, the command set). No skipped work.
