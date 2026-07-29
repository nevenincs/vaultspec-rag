---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S01'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Name the indexed-frontmatter subset beside the payload builders that consume it, so the fingerprint and the payload cannot drift apart silently

## Scope

- `src/vaultspec_rag/_store_models.py`

## Description

- Add `vault_indexed_metadata()` to `src/vaultspec_rag/_store_models.py`, directly
  above the two vault payload builders that consume the same fields, returning the
  frontmatter-derived subset that enters point payloads: path, doc type, feature,
  date, tags, related, title, status.
- Add `VAULT_BODY_PAYLOAD_KEYS` and `VAULT_STRUCTURAL_PAYLOAD_KEYS` beside it, so
  every payload key belongs to exactly one of three classes and none can be
  unclassified by accident.
- Export all three plus `vault_metadata_digest` from the module's `__all__`.

## Outcome

The subset is a single definition rather than a list restated next to a digest.
The volatile `modified:` stamp is excluded by construction, not by an exclusion
list: it is not a `VaultDocument` field, so it cannot be named in the subset at
all, and no future edit can accidentally re-admit it.

Co-location is the enforcement mechanism the decision asked for. A reader adding
a payload field sees the subset in the same screen, and the partition test added
in S03 fails if they still miss it.

## Notes

`vault_indexed_metadata()` returns a mapping rather than a tuple of field names
so there is one definition, not a name list that must be kept in step with an
accessor. The partition test derives the field set from the mapping's keys.
