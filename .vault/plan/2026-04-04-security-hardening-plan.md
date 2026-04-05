---
tags:
  - '#plan'
  - '#security-hardening'
date: 2026-04-04
related:
  - '[[2026-04-04-security-hardening-adr]]'
  - '[[2026-04-04-security-hardening-research]]'
  - '[[2026-04-02-service-graph-code-review-audit]]'
---

# `security-hardening` plan

Defense-in-depth hardening for SEC-001 through SEC-004 from the
service-graph code review audit. Four isolated, non-breaking fixes
targeting `mcp_server.py` (D1, D2, D3) and `cli.py` (D4).

## Proposed Changes

Per ADR decisions D1–D4: add vault boundary validation to root resolution,
add a sensitive file deny-list to the code file reader, reduce information
disclosure in the health endpoint and index status tool, and add Windows
process name verification for PID ownership checks.

## Tasks

- Phase 1: Core security fixes (4 tasks, parallelizable in pairs)

  1. **SEC-001: Vault boundary validation** — Extract `_validate_vault_root(path)`
     helper in `mcp_server.py`. Call it from both `_resolve_root()` and
     `_default_root()`. Raises `ValueError` when `path / ".vault"` is not a
     directory. All MCP tools and the `vault://` resource are covered.

  1. **SEC-002: Sensitive file deny-list** — Add `_SENSITIVE_PATTERNS` tuple
     and `_is_sensitive_path(rel_path)` function in `mcp_server.py`. Patterns:
     `.env*`, `.git/*`, `*.pem`, `*.key`, `*credentials*`, `*secrets*`,
     `service.json`, `.vaultspec-rag/*`. Check in `get_code_file` before
     reading. Raise `ValueError("access denied")`.

  1. **SEC-003: Health endpoint info reduction** — In `health_handler`:
     replace `projects` list with `project_count` integer. In
     `get_index_status`: remove `gpu_name` field from `IndexStatus` model
     and response construction. Keep `vram_gb` for diagnostics. Update
     `HealthResponse` Pydantic model to match.

  1. **SEC-004: Windows PID verification** — In `_is_our_service()`: on
     Windows, use `kernel32.QueryFullProcessImageNameW` via ctypes to get
     the process executable path. Check `"python" in exe_path.lower()`.
     Fall back to `True` if `OpenProcess` fails (elevated process).

- Phase 2: Tests (4 tasks, parallelizable)

  1. **Test SEC-001** — Test `_validate_vault_root` with: valid vault dir,
     missing `.vault/`, non-existent path. Test `_resolve_root` raises
     `ValueError` for non-vault paths. Test that all MCP tool handlers
     reject non-vault roots (via `_resolve_root` integration).

  1. **Test SEC-002** — Test `_is_sensitive_path` against each deny pattern.
     Test `get_code_file` raises `ValueError` for `.env`, `.git/config`,
     `*.pem` paths. Test that non-sensitive paths pass through.

  1. **Test SEC-003** — Test `health_handler` response contains
     `project_count` (int) not `projects` (list). Test `get_index_status`
     response lacks `gpu_name`. Verify `HealthResponse` model validates
     the new schema.

  1. **Test SEC-004** — Test `_is_our_service` on current platform.
     On Windows: verify it returns True for current process PID (Python
     process). On Unix: verify `/proc/{pid}/cmdline` check works.
     Test with PID 0 and PID -1 (invalid).

- Phase 3: Integration verification

  1. **Run full test suite** — `uv run pytest src/vaultspec_rag/tests/ -x`
     to confirm no regressions.

  1. **Run pre-commit** — `git add . && pre-commit run --all-files` to
     confirm linting and formatting pass.

## Parallelization

- Phase 1 tasks 1+2 (mcp_server.py changes) can run sequentially since
  they modify the same file but different functions.
- Phase 1 tasks 3+4 are independent (different files).
- Phase 2 tests can all be written in parallel after Phase 1.
- Use 2 subagents: one for mcp_server.py (SEC-001, SEC-002, SEC-003 + tests)
  and one for cli.py (SEC-004 + tests).

## Verification

- All existing tests pass (0 regressions).
- New tests cover each SEC finding with positive and negative cases.
- No mocks, patches, stubs, or skips in new tests.
- `ruff check` and `ruff format --check` pass.
- `ty check` passes (type annotations correct).
- Pre-commit hooks pass on all modified files.
- Manual verification: `_resolve_root("/tmp")` raises ValueError.
- Manual verification: `get_code_file(".env")` raises ValueError.
- Manual verification: `/health` response lacks absolute paths.
- Manual verification: `_is_our_service(os.getpid())` returns True on Windows.
