---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:eea117bce5f856c3990343765dc1b1563ac14ef0399ae4cd62d75429b70e69d6'
step_id: 'S08'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Implement the POSIX backends: bubblewrap with a Landlock-plus-seccomp fallback on Linux and a deny-default seatbelt profile on macOS

## Scope

- `src/vaultspec_rag/indexer/_hook_sandbox_posix.py`

## Description

- Add the stdlib-only POSIX containment module exposing `probe_posix_sandbox`,
  which selects a backend by platform.
- Implement `BubblewrapSandbox` for Linux: wrap the hook argv as a `bwrap`
  invocation with `--unshare-net`, `--die-with-parent`, a read-only bind of each
  existing read path, a read-write bind of the scratch dir, and `--chdir` into
  the scratch dir, returning the `subprocess.Popen` as the sandbox handle.
- Implement `SeatbeltSandbox` for macOS: wrap the argv under `sandbox-exec` with
  a deny-default profile that allows process fork/exec, read of the granted
  paths, read+write of the scratch dir, and denies all network.
- Share a no-op `cleanup` via a small base so both `Popen`-backed backends
  satisfy the sandbox protocol without per-launch resource release.
- Deduplicate and canonicalise read paths via `realpath`, skipping non-existent
  sources so a launcher never fails on a missing bind target.

## Outcome

Both backends match the Windows backend's `launch` signature and the sandbox
handle protocol structurally, so the runner drains them unchanged. `bwrap`/
`sandbox-exec` are discovered on `PATH`; when absent the probe returns `None`
so server mode fail-closes. Lint and type checks pass with zero findings.

## Notes

The Linux Landlock+seccomp fallback is a deliberate documented gap: without
`bubblewrap` the probe returns `None` rather than running unconfined, so a
backend-less Linux host refuses hooks in server mode (the safe degradation).
`bubblewrap` is the supported Linux backend. The macOS backend could not be
exercised on this Windows host; its platform-gated real-containment test is
present and runs where the OS matches.
