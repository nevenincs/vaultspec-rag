---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:573fd04bc11a58957761a632246e629ff1aa94a7e8cb76244ecd69cc38eb18ae'
step_id: 'S37'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Preserve builtin node topology across failed install rollback

## Scope

- `src/vaultspec_rag/commands/_install.py and real symlink/junction rollback tests`

## Description

- Replace byte-or-absent rollback snapshots with lstat-based node snapshots for
  regular files, absent paths, directories, symlinks, and Windows junctions.
- Restore symlinks from exact link text without following or mutating their
  targets, including broken relative links.
- Recreate Windows junctions through a bounded native PowerShell operation with
  capped printable failure diagnostics.
- Exercise natural force and upgrade rollback for live and broken symlinks,
  genuine junction seed blockers, and direct real junction replacement repair.

## Outcome

The topology regression surface passes seven tests and the complete install,
mode, torch, native-host, and rollback surface passes 202 tests. Ruff,
formatting, Ty, BasedPyright, complexity, lock consistency, and diff hygiene
pass.

## Notes

Core's atomic writer cannot replace a Windows junction: the native replace and
copy fallback both refuse the directory reparse point. The install test
therefore proves junction preservation as the real ordered blocker, while a
separate real snapshot/rollback test exercises junction recreation directly.
S38 restarts the complete 1,820-test aggregate.
