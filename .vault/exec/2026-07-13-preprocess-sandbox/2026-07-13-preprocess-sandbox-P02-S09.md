---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S09'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Route the runner subprocess launch through the resolved sandbox backend, preserving the timeout, output caps, and argv hygiene inside it

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

- Extend `PreprocessContext` with `project_root`, `server_mode`, and
  `unsandboxed`, keeping the dataclass picklable for the spawn worker.
- Populate the new fields at both construction sites: the indexer derives
  `server_mode` from the configured Qdrant URL (matching the store) and
  `unsandboxed` from the resolved preprocess mode; the worker unit test's
  context builder sets local, unsandboxed values.
- Thread the three fields through the chunk worker's `run_preprocessor` call and
  the CLI `preprocess run-one` call (local, non-server).
- Route the runner launch through the resolved backend: stage the source into a
  scratch dir, rewrite the argv so the hook reads the staged copy, resolve the
  backend once per worker with a memoized fail-closed policy, and grant read of
  the scratch dir, the interpreter prefixes, and the project root.
- Split the launch from the bounded drain so a `Popen` (unsandboxed/local) and a
  backend-launched contained child share the identical timeout, output-cap, and
  pipe-drain logic; release the backend's per-launch resources and remove the
  scratch dir in a `finally`.
- Curate the child environment and place the project root on `PYTHONPATH` so a
  project-local `entry_point` or `python -m` command hook can import its own
  module tree from the read-granted root.

## Outcome

Every server path now launches hooks through the containment seam with staged
input and a curated, secret-free environment; server mode with no backend maps
a `SandboxUnavailableError` onto a per-file skip with an actionable reason rather
than an unconfined run. All preprocess unit suites pass (52 passed, 1 platform
skip) and the runner stays importable from the CPU-only spawn worker without
loading torch. Lint and type checks are clean.

## Notes

Staging changes the path the hook observes: a hook that echoes its input path
into anchors now sees the staged copy's path (basename preserved), so two
existing runner/worker assertions that pinned the original absolute path were
relaxed to assert the preserved basename. The curated environment strips
`PYTHONPATH`; the runner re-adds only the project root, which the entry-point and
worker tests rely on to resolve a project-local hook module - a real behaviour
change surfaced to the team lead as the resolution contract for project-local
hooks.
