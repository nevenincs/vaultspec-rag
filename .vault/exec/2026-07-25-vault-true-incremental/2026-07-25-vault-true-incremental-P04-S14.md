---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:7fe63f10f46999db6c0e58e463d70131a9fb5af228ebf1df62107ac7e68b3669'
step_id: 'S14'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Prove the body guard bidirectionally: assert a body edit re-embeds, drop the body digest from the fingerprint, watch it fail, restore, watch it pass

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Add `TestBodyChangeStillReEmbeds` to the same integration module.
- Assert a body edit yields `updated == 1`, `payload_updated == 0`, and stored
  vectors that differ from before.
- Drive it red by mutation, restore, drive it green.

## Outcome

Proven able to fail, in one uninterrupted sequence. Dropped the body from the
fingerprint - digesting a constant instead of the normalised body in
`fingerprint_text()` - ran the guard alone, and watched it fail on its own
re-embed assertion: `a body edit did not re-embed; the stored vectors no longer describe the document`, `assert 0 == 1`. Restored the body digest; the guard
passed again. No mutation was left on disk.

That mutation is the exact silent-degradation shape this plan exists to prevent.
Under it the index answers every query and fails nothing, while serving vectors
that describe text the document no longer contains.

## Notes

`payload_updated == 0` is asserted alongside `updated == 1`, so the guard also
catches the opposite misroute: a body edit taking the cheap branch would leave
stale vectors behind a freshly rebuilt payload, which is worse than either branch
being wrong on its own because the payload would look current.
