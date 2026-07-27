---
tags:
  - '#research'
  - '#security-hardening'
date: 2026-04-04
modified: '2026-07-27'
related:
  - '[[2026-04-02-service-graph-code-review-audit]]'
  - '[[2026-04-02-service-graph-adr]]'
---

# `security-hardening` research: defense-in-depth for SEC-001 through SEC-004

Structured research on four security findings from the Round 3 service-graph
code review audit. All findings are mitigated by localhost binding
(127.0.0.1 only) but warrant defense-in-depth hardening for production
readiness.

## Findings

### SEC-001: Restrict `_resolve_root` to valid workspaces

**Current state:** `_resolve_root()` in `mcp_server.py` calls
`Path(project_root).resolve()` with no validation. Any MCP client can pass
an arbitrary path (`/etc`, `C:\Windows\System32`) and the service will index
and expose its contents.

**Analysis:**

- vaultspec-rag is a vault search tool — paths without a `.vault/` directory
  are semantically meaningless. The `.vault/` boundary is the natural
  validation gate.

- `Path.resolve()` follows symlinks, which is correct — a symlinked workspace
  is still a valid workspace if it contains `.vault/`.

- The check must happen before `_registry.get_project(root)` since that call
  triggers `_create_slot()` which opens a Qdrant store and starts indexing.

**Recommendation:**

- Add a `.vault/` directory existence check in `_resolve_root()`.
- Raise `ValueError` with a clear message when no `.vault/` exists.
- This is a single-point fix — all 7 MCP tools and both resources flow through
  `_resolve_root()`.

**Edge cases:**

- `_default_root()` (env var or cwd fallback) should also be validated. A
  service started from a non-vault directory would otherwise silently accept.
- The `reindex_vault` tool with `clean=True` on a non-vault path would create
  empty collections — wasteful but not dangerous. The check prevents this.

### SEC-002: Sensitive file exclusion in `get_code_file`

**Current state:** `get_code_file` in `mcp_server.py` validates path traversal
(rejects paths outside workspace via `is_relative_to`) but allows reading any
file within the workspace boundary, including `.env`, `.git/config`,
credentials files, and `service.json`.

**Analysis:**

- `.vaultragignore` support does not exist yet (PR #36 not merged). The
  indexer uses `.gitignore`-aware pruning via `pathspec` but `get_code_file`
  is a direct file read, not an index lookup — it bypasses all ignore logic.

- A deny-list approach is appropriate: block known-sensitive patterns rather
  than trying to allowlist all safe files. The deny-list is small and stable.

- Patterns should match against the resolved path relative to the workspace
  root, using `fnmatch` or simple string checks.

**Recommended deny-list:**

| Pattern                | Rationale                                  |
| ---------------------- | ------------------------------------------ |
| `.env*`                | Dotenv files (secrets, API keys)           |
| `.git/**`              | Git internals (config, credentials, hooks) |
| `**/*.pem`             | TLS certificates / private keys            |
| `**/*.key`             | Private key files                          |
| `**/credentials*`      | Generic credentials files                  |
| `**/secrets*`          | Generic secrets files                      |
| `service.json`         | PID file (SEC-004 vector)                  |
| `**/.vaultspec-rag/**` | Service data directory                     |

**Implementation approach:**

- Define `_SENSITIVE_PATTERNS` as a tuple of glob patterns at module level.
- Use `PurePosixPath` for consistent forward-slash matching on Windows.
- Check the relative path (not absolute) against each pattern using
  `fnmatch.fnmatch` or `pathlib.PurePath.match`.
- Return `ValueError` with a generic "access denied" message (do not
  reveal which pattern matched — information disclosure).

### SEC-003: Health endpoint information disclosure

**Current state:** `health_handler` in `mcp_server.py` returns:

```json
{
  "status": "ready",
  "cuda": true,
  "models_loaded": true,
  "projects": ["C:/projects/worktrees/main"],
  "uptime_s": 42.5
}
```

Additionally, `get_index_status` returns `gpu_name`, `vram_gb`,
`storage_path`, and `target_dir` as absolute paths.

**Analysis:**

- The `/health` endpoint is unauthenticated raw HTTP (not MCP). On shared
  machines, absolute paths disclose workspace layout. GPU identity enables
  hardware fingerprinting.

- `get_index_status` is an MCP tool (requires MCP session). Lower risk but
  still exposes more than necessary.

- `uptime_s` is non-sensitive and useful for monitoring.

**Recommendation for `/health`:**

| Field           | Current                   | Proposed              |
| --------------- | ------------------------- | --------------------- |
| `status`        | Keep                      | Keep                  |
| `cuda`          | `true`/`false` + GPU name | `true`/`false` only   |
| `models_loaded` | Keep                      | Keep                  |
| `projects`      | Absolute paths list       | Project count integer |
| `uptime_s`      | Keep                      | Keep                  |

- Replace `projects` list with `project_count` integer.
- `cuda` already returns only boolean — confirmed correct, no GPU name leak.

**Recommendation for `get_index_status`:**

- Strip `gpu_name` from response. Keep `vram_gb` (generic, not fingerprinting).
- Replace `storage_path` and `target_dir` with relative paths or omit.
- Since this is an MCP tool (authenticated session), this is lower priority
  but still good hygiene.

### SEC-004: Windows PID verification in `_is_our_service`

**Current state:** `_is_our_service()` on Unix reads `/proc/{pid}/cmdline`
and checks for `"vaultspec_rag"`. On Windows, it returns `True` for any alive
PID — no process name verification.

`_is_pid_alive()` already has the `GetExitCodeProcess` fix (PHASE4-005
was FIXED in the service-graph PR).

**Analysis:**

- The Windows fallback means `service_stop` could kill any process owned by
  the same user if `service.json` is tampered with or contains a stale PID
  that was recycled by the OS.

- PID recycling on Windows is real: the PID space is 32-bit and PIDs are
  reused aggressively after process exit.

- `QueryFullProcessImageNameW` with `PROCESS_QUERY_LIMITED_INFORMATION`
  (0x1000) is the correct ctypes approach to get the executable path.
  Available on Windows Vista+ (Python 3.13 requirement already implies
  Windows 10+).

- Checking for `"python"` in the exe path is necessary but not sufficient
  (many Python processes may run). However, combined with the port check
  (health probe), it provides reasonable defense:

  1. PID is alive (existing check)
  1. PID is a Python process (new check)
  1. Health probe succeeds on expected port (existing check in `service_start`)

**Recommended implementation:**

```
_is_our_service(pid) on Windows:
  1. _is_pid_alive(pid) → False → return False
  2. OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)
  3. QueryFullProcessImageNameW → exe_path
  4. Check "python" in exe_path.lower()
  5. If not Python → return False
  6. Return True (Python process on our port = sufficient confidence)
```

**Edge cases:**

- Elevated processes: `OpenProcess` may fail with `ERROR_ACCESS_DENIED`.
  Fallback to `True` (current behavior) is acceptable — if we can't query
  the process, it's likely ours or we can't kill it anyway.

- PyInstaller/frozen executables: exe path would not contain "python". Not a
  current concern (project runs from source via `uv`).

## Summary of recommendations

| Finding | Severity | Fix complexity | Single-point fix?                                    |
| ------- | -------- | -------------- | ---------------------------------------------------- |
| SEC-001 | MEDIUM   | Low            | Yes — `_resolve_root()` only                         |
| SEC-002 | MEDIUM   | Low            | Yes — `get_code_file` only                           |
| SEC-003 | LOW      | Low            | Two functions: `health_handler` + `get_index_status` |
| SEC-004 | MEDIUM   | Medium         | Yes — `_is_our_service()` only                       |

All four fixes are isolated, non-breaking, and testable without mocks.
SEC-001 and SEC-002 are the highest value — they close the widest attack
surface. SEC-003 is cosmetic hardening. SEC-004 improves Windows parity.
## Sources
- Related record identifiers: `2026-04-02-service-graph-code-review-audit`, `2026-04-02-service-graph-adr`.
