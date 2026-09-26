---
tags:
  - '#exec'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:67622a03eb868c375845ca693f91bb30e1b5af89ccb87c979173869fc2807151'
related:
  - "[[2026-09-26-gpu-single-owner-plan]]"
---

# `gpu-single-owner` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/_process_probe.py`
- `S01` `A` `src/vaultspec_rag/tests/test_process_lineage.py`
- `S01` `verify:` `ruff check` -> `pass`
- `S01` `verify:` `ruff format --check` -> `pass`
- `S01` `verify:` `ty check` -> `pass`
- `S01` `verify:` `basedpyright` -> `pass`
- `S01` `verify:` `pytest test_process_lineage.py test_process_probe_os_guards.py test_process_probe_source_structure.py` -> `pass`
- `S01` `by:` `orchestrator`
- `S02` `M` `src/vaultspec_rag/_anchor_claim.py`
- `S02` `M` `src/vaultspec_rag/_gpu_admission.py`
- `S02` `M` `src/vaultspec_rag/_win32.py`
- `S02` `A` `src/vaultspec_rag/tests/test_hardware_anchor.py`
- `S02` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S02` `verify:` `ruff check` -> `pass`
- `S02` `verify:` `ruff format --check` -> `pass`
- `S02` `verify:` `ty check` -> `pass`
- `S02` `verify:` `basedpyright` -> `pass`
- `S02` `verify:` `pytest -m unit test_hardware_anchor gpu_admission test_existing_anchor_observation test_gpu_borrow_lease test_gpu_borrow_captured_target` -> `pass`
- `S02` `verify:` `guard mutations (env-read anchor dir, temp-dir load window, no read-only fallback) fail then pass` -> `pass`
- `S02` `by:` `orchestrator`

## Notes

- `S02` `test_substitution_discipline` fails on the base branch for `test_storage_maintenance_tick.py` (substitution added by d18045e8, outside this plan); left untouched
