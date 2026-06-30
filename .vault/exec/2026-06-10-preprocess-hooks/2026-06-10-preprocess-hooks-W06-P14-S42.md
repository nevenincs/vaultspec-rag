---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S42'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Scaffold a disposable toy workspace with sample binary data, a project-side extractor, and a .vaultragpreprocess.toml (D1, D13)

## Scope

- `tmp toy project (manual)`

## Description

Stood up a disposable toy workspace (temp dir) mirroring a downstream consumer: a `tools/`
extractor that reads a fake PDF and emits a two-page `PreprocOutput` with page anchors, a
`tools/` failing extractor (exits 7) to exercise `on_error=skip`, two real binary `.pdf`
files under `corpus/`, and a root `.vaultragpreprocess.toml` with two `command` rules
(annual -> good extractor at priority 10, broken -> failing extractor).

## Outcome

Toy workspace built and configured. `preprocess check` reports `OK - 2 valid preprocess rule(s)` (exit 0).

## Notes

**Finding (real Windows gotcha):** a `command` with a backslash interpreter path breaks the
runner's `shlex.split(posix=True)` even inside a TOML literal (backslashes are eaten as
escapes); forward-slash paths are required on Windows. The docs already advise forward
slashes - this manual run confirms the guidance is load-bearing, not optional.
