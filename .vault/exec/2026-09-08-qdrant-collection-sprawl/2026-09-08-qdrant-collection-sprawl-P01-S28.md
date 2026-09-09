---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:2953bf040da20f3a22adf2ecf4817e6f3b25698accacb5ccdab9742a50cc2b8c'
step_id: 'S28'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Carry an uncountable collection through the survey as unverifiable rather than as zero points, so a failed count cannot mis-tier a data-bearing namespace as empty

## Scope

- `src/vaultspec_rag/storage_survey_ops.py`

## Changes

- `M` `src/vaultspec_rag/storage_survey_ops.py`
- `M` `src/vaultspec_rag/storage_survey.py`
- `M` `src/vaultspec_rag/storage_reclamation.py`
- `M` `src/vaultspec_rag/storage_manifest.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `M` `src/vaultspec_rag/tests/test_storage_safety.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_survey.py test_storage_ops.py test_storage_safety.py test_storage_ops_reclaim.py test_storage_manifest.py test_index_lifecycle.py` -> `pass`

## Notes

Threading the unverifiable count reached four modules beyond the scoped one.
`classify_namespaces` and `NamespaceSurvey` carry the new signal, the two
tiering functions and the activity clock consume it, and two existing
pre-drop-gate tests were repointed: a namespace the survey cannot count is
now held at evaluation, so a stand-in refusing every count no longer reaches
the gate those tests exist to prove, and each now fails its own count only
after the survey has taken one.
