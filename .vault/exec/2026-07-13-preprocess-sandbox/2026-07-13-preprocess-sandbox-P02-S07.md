---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-14'
step_id: 'S07'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Implement the Windows AppContainer backend with a kill-on-close Job Object, no network capability, and an ACL grant for the staged input dir

## Scope

- `src/vaultspec_rag/indexer/_hook_sandbox_windows.py`

## Description

- Implement the Windows AppContainer backend: derive a stable AppContainer SID
  (create-or-derive the profile), grant the SID read+execute on the scratch and
  read-path dirs via `icacls`, and launch the hook via `CreateProcessW` with a
  `STARTUPINFOEX` carrying `SECURITY_CAPABILITIES` (AppContainer SID, zero
  capability SIDs so network is denied) plus a `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`
  admitting only the two pipe write ends.
- Wrap the child in a `KILL_ON_JOB_CLOSE` Job Object for process-tree teardown.
- Return a `SandboxHandle` over the process handle and captured pipes.
- Probe support by creating/deriving the profile; unavailable hosts return None
  so the resolver fail-closes.

## Outcome

Proven on this host with a hostile probe: the child reads its staged input, but
reading a secret outside the staged dir is PermissionError, opening a network
socket is PermissionError, and the daemon's secrets are absent from its env,
while the hook still runs and emits correct output. Ruff and basedpyright clean.

## Notes

Four Win32 gotchas each cost an iteration, now captured in code comments and a
reference memory: (1) an env block built via `c_wchar_p` or
`create_unicode_buffer(str)` truncates at the first embedded NUL - build it
char-by-char; (2) `CREATE_UNICODE_ENVIRONMENT` must be set or the wide block is
misread as ANSI; (3) AppContainer init needs several path env vars present or it
fails with 203; (4) `msvcrt.open_osfhandle` needs `handle.value`, not
`int(handle)`. The child cannot read its own interpreter unless the AppContainer
SID is granted read on `sys.base_prefix` and `sys.prefix`; a project-local hook
also needs the project root granted plus `PYTHONPATH`.
