---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S25'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add an integration test for the default install provisioning path reporting heterogeneous per-dependency outcomes

## Scope

- `src/vaultspec_rag/tests/integration/test_install.py`

## Description

- Extend `src/vaultspec_rag/tests/integration/test_install.py` with a
  `TestProvisioningReport` class driving the real `install_run` provisioning path
  with no mocks and no large downloads.
- Make the test network-free by construction: `local_only=True` skips the qdrant
  binary download and `provision_skip={"models"}` skips the model fetch, so the
  only real work is the torch configurator patching the temp workspace's own
  `pyproject.toml` - yielding three honest, different per-dependency outcomes.
- Add a STATUS_DIR-isolating fixture so the qdrant resolution stays off any
  ambient managed dir and the live service is untouched.
- Assert the report carries a `provision_outcome`, the JSON `provisioning` key is
  heterogeneous and serialisable (distinct per-step details, the `--local-only`
  reason on qdrant), and the enrollment torch step reports the applied,
  sync-pending two-phase state.
- Add a captured-console renderer assertion proving the human report surfaces the
  qdrant skip with its local-only reason and the bounded `Provisioning:` summary,
  plus a dry-run test proving the preview writes no binary into the isolated dir.

## Outcome

The default install provisioning path is covered end-to-end: the report carries
heterogeneous per-dependency outcomes (torch sync-pending vs models vs qdrant),
the JSON envelope is honest and serialisable, and the human renderer surfaces the
same outcome. The whole scoped suite runs green (`54 passed`). The renderer
assertion swaps the shared Rich console to a captured buffer by direct attribute
assignment restored in a `finally` (the established no-mocks pattern in this
repo), so it asserts real rendered bytes.

## Notes

The test deliberately exercises the already-satisfied / opted-out paths rather
than triggering a real binary or model download, so it is network-free and cannot
disturb the live resident service, per the operability persona-test and
STATUS_DIR-isolation disciplines.
