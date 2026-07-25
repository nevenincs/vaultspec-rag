---
tags:
  - '#adr'
  - '#security-hardening'
date: 2026-04-04
modified: '2026-06-30'
related:
  - '[[2026-04-04-security-hardening-research]]'
  - '[[2026-04-02-service-graph-code-review-audit]]'
  - '[[2026-04-02-service-graph-adr]]'
---

# `security-hardening` adr: defense-in-depth for MCP service | (**status:** `accepted`)

## Problem Statement

The service-graph code review (Round 3) identified four security findings
(SEC-001 through SEC-004) in the MCP server and CLI service daemon. All are
mitigated by localhost binding (127.0.0.1 only) but need defense-in-depth
hardening before beta. A malicious or misconfigured MCP client on the same
machine could index arbitrary filesystem paths, read sensitive workspace
files, fingerprint hardware, or kill unrelated processes via PID poisoning.

## Considerations

- The MCP server binds to 127.0.0.1 — network exposure is zero. All attack
  vectors require local access at the same user privilege level.

- vaultspec-rag is a vault search tool. Paths without `.vault/` are
  semantically meaningless and should be rejected early.

- `get_code_file` is a direct file read tool, not an index lookup. It
  bypasses `.gitignore` pruning and any future `.vaultragignore` logic.

- The `/health` endpoint is raw HTTP (no MCP session required). Information
  disclosed there has a wider audience than MCP tool responses.

- On Windows, PID recycling is aggressive. A stale `service.json` PID can
  match an unrelated process. Unix verification via `/proc/{pid}/cmdline`
  has no Windows equivalent without ctypes.

- Testing mandates: no mocks, patches, or stubs. All fixes must be testable
  with real filesystem operations and real process checks.

## Constraints

- No new dependencies. All fixes use stdlib (`pathlib`, `fnmatch`, `ctypes`).
- No breaking changes to MCP tool signatures or `/health` response schema
  (additive changes only where possible; `projects` → `project_count` is a
  breaking change but `/health` has no external consumers in alpha).
- GPU always available (RTX 4080). Tests exercise real code paths.
- Must pass `pre-commit` and `ruff` without suppressions.

## Implementation

### D1: Vault boundary validation in `_resolve_root()` and `_default_root()`

Add a `.vault/` directory existence check after `Path.resolve()`. If the
resolved path does not contain a `.vault/` directory, raise `ValueError`.
This covers the 7 MCP tools that pass `project_root` through
`_resolve_root()`. Additionally, `get_vault_document` calls
`_default_root()` directly — the validation must also be applied there.
Extract the check into a shared `_validate_vault_root(path)` helper
called by both `_resolve_root()` and `_default_root()`.

### D2: Sensitive file deny-list in `get_code_file`

Define `_SENSITIVE_PATTERNS` as a module-level tuple of glob patterns:
`.env*`, `.git/*`, `*.pem`, `*.key`, `*credentials*`, `*secrets*`,
`service.json`, `.vaultspec-rag/*`. Check the relative path (forward-slash
normalized) against each pattern using `fnmatch.fnmatch`. Return a generic
`ValueError("access denied")` without revealing which pattern matched.

### D3: Health endpoint information reduction

In `health_handler`: replace `projects` (list of absolute paths) with
`project_count` (integer). The `cuda` field already returns boolean only —
no GPU name leak. Keep `uptime_s` (non-sensitive).

In `get_index_status`: remove `gpu_name` field from `IndexStatus`. Replace
`storage_path` and `target_dir` absolute paths with a boolean
`indexed: true/false` or relative paths. Since this is an MCP tool
(authenticated session), keep `vram_gb` for diagnostic value.

Update `HealthResponse` and `IndexStatus` Pydantic models accordingly.

### D4: Windows process verification in `_is_our_service()`

On Windows, after `_is_pid_alive()` confirms the PID exists, use
`kernel32.QueryFullProcessImageNameW` via ctypes to get the executable
path. Check `"python" in exe_path.lower()`. If `OpenProcess` fails
(elevated process), fall back to `True` (current behavior — acceptable
since we can't kill elevated processes anyway).

## Rationale

- **D1** closes the widest attack surface with minimal code. The `.vault/`
  boundary is inherent to the tool's purpose — it's not an arbitrary
  restriction but a semantic correctness check. The shared
  `_validate_vault_root()` helper ensures both explicit `project_root`
  params and implicit `_default_root()` callers (like `get_vault_document`)
  are covered.

- **D2** follows established patterns (GitHub Copilot, Cursor, and other
  AI coding tools all maintain sensitive file deny-lists). The deny-list
  approach is more maintainable than an allowlist and handles the common
  cases. Future `.vaultragignore` support (PR #36) can layer on top.

- **D3** follows the principle of least privilege for unauthenticated
  endpoints. Project count is sufficient for health monitoring. GPU name
  serves no monitoring purpose.

- **D4** achieves parity with Unix process verification using only stdlib
  ctypes. The `QueryFullProcessImageNameW` API is available on all
  supported Windows versions (10+, required by Python 3.13). Checking for
  "python" in the exe path is pragmatic — combined with port-liveness, it
  provides sufficient confidence.

## Consequences

- **D1** will cause `ValueError` for MCP clients that currently pass
  non-vault paths. This is intentional — such usage was always meaningless
  and now fails explicitly rather than silently producing empty results.

- **D2** may block legitimate reads of files matching deny patterns
  (e.g., a file literally named `credentials-readme.txt`). This is
  acceptable — users can read such files directly through their editor.

- **D3** breaks the `/health` response schema (`projects` list → integer
  `project_count`). No known external consumers in alpha. The
  `HealthResponse` Pydantic model will be updated.

- **D4** adds ~20 lines of Windows-specific ctypes code. The fallback
  path (return `True` on `OpenProcess` failure) preserves current behavior
  for edge cases.
