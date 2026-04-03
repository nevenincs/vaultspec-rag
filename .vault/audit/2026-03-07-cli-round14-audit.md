---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
related: []
---

# Round 14 Audit -- cli.py (full audit)

**Auditor:** docs-researcher-2-2
**File:** `src/vaultspec_rag/cli.py` (469 lines)
**Date:** 2026-03-07

______________________________________________________________________

## Check 1: `test` Command

### `handle_test()` (lines 446-464)

```python
@app.command(
    "test",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_test(ctx: typer.Context):
    import subprocess
    import sys
    test_dir = str(Path(__file__).resolve().parent / "tests")
    cmd = [sys.executable, "-m", "pytest", test_dir, *ctx.args]
    raise SystemExit(subprocess.call(cmd))
```

- **Args forwarding:** `*ctx.args` spreads all extra CLI args to pytest. `allow_extra_args=True` + `ignore_unknown_options=True` ensures Typer doesn't reject unknown flags (e.g., `-m integration`, `--timeout=120`).
- **Execution:** Uses `subprocess.call()` which runs pytest and returns the exit code.
- **Exit code:** `raise SystemExit(subprocess.call(cmd))` propagates pytest's exit code to the parent process.
- **Test directory:** `Path(__file__).resolve().parent / "tests"` correctly resolves to `src/vaultspec_rag/tests/`.

**Verdict: PASS.** Args forwarded correctly, exit code propagated, test directory derived from `__file__`.

### R14-m1: `raise SystemExit` vs `raise typer.Exit` (Minor)

`raise SystemExit(code)` works but bypasses Typer's exit handling (R21-M5 noted this). `raise typer.Exit(code=result)` would be more idiomatic. Functionally equivalent since `typer.Exit` inherits from `SystemExit`.

**File:** `cli.py:464`

______________________________________________________________________

## Check 2: GPU Error Handling

### `_handle_gpu_error()` (lines 34-48)

```python
def _handle_gpu_error(exc: Exception) -> None:
    if isinstance(exc, ImportError):
        console.print("[bold red]Error:[/] GPU dependencies not installed....")
    elif "CUDA" in str(exc) or "cuda" in str(exc):
        console.print("[bold red]Error:[/] No CUDA GPU detected....")
    else:
        console.print(f"[bold red]Error:[/] {exc}")
    raise typer.Exit(code=1)
```

Called at:

- `handle_index` line 199-200: catches `(ImportError, RuntimeError)`
- `handle_search` line 290-291: catches `(ImportError, RuntimeError)`
- `handle_status` line 328-329: catches `ImportError` only

**Verdict: PASS.** Catches the right exception types. `ImportError` for missing packages, `RuntimeError` for missing CUDA (raised by `_check_rag_deps()`). The `"CUDA" in str(exc)` heuristic (R21-m7) could match unrelated exceptions mentioning CUDA, but in practice only `_check_rag_deps()` raises these.

### R14-m2: `_handle_gpu_error` string matching is a heuristic (Minor)

Line 41: `"CUDA" in str(exc) or "cuda" in str(exc)` could match RuntimeError messages that mention CUDA incidentally. A more robust check would be `isinstance(exc, RuntimeError)` before the string check. Low risk in practice.

**File:** `cli.py:41`

______________________________________________________________________

## Check 3: `--target` Ignored for `test` and `server`

### `main()` callback (lines 129-130)

```python
if ctx.invoked_subcommand in ("test", "server"):
    return
```

When `ctx.invoked_subcommand` is `"test"` or `"server"`, the function returns immediately without resolving the workspace. The `--target` flag is parsed but silently ignored.

### R14-m3: `--target` is silently ignored for `test` and `server` commands (Minor)

If a user runs `vaultspec-rag --target /foo test`, the `--target` flag has no effect and no warning is shown. The user may believe their target override was applied. This is R21-m8, still unfixed.

**File:** `cli.py:129-130`

______________________________________________________________________

## Check 4: `configure_logging(debug, verbose)` Precedence

### Line 123

```python
configure_logging(debug=debug, level="INFO" if verbose else None)
```

If both `--debug` and `--verbose` are passed:

- `debug=True`
- `level="INFO"`

The behavior depends on `configure_logging()` internals. Without reading that function, the precedence is unclear. If `debug=True` sets `DEBUG` level but `level="INFO"` overrides it, the user gets INFO (unexpected). If `debug` takes precedence, `level` is ignored (verbose has no effect).

### R14-m4: `--debug` and `--verbose` interaction is undocumented (Minor)

The CLI does not enforce mutual exclusivity or document precedence. R21-m9 noted this. Likely `debug` takes precedence inside `configure_logging()`, but the behavior is opaque from the CLI code alone.

**File:** `cli.py:123`

______________________________________________________________________

## Check 5: UTF-8 Reconfiguration

### Lines 14-17

```python
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
```

- **Safe?** Yes -- `hasattr` check ensures `reconfigure` exists (only on text streams, not binary). Windows console defaults to the system codepage (often cp1252), which can't render Unicode spinners/arrows from Rich.
- **Subprocess impact?** `subprocess.call()` in `handle_test()` creates a new process with its own stdout/stderr. The parent's reconfiguration does not affect the child process. If pytest output contains non-UTF-8 bytes, `subprocess.call()` passes them through since it doesn't capture output.

**Verdict: PASS.** Safe, platform-guarded, does not affect subprocess output.

______________________________________________________________________

## Check 6: `handle_index` -- Full vs Incremental

### Lines 210-228

```python
# Phase 1: Vault indexing
if do_vault:
    ...
    v_res = v_indexer.incremental_index()
    ...

# Phase 2: Codebase indexing
if do_code:
    ...
    c_res = (
        c_indexer.full_index()
        if clean
        else c_indexer.incremental_index()
    )
```

### R14-M1: `handle_index` vault indexing always uses `incremental_index()` regardless of `--clean` flag (MEDIUM)

When `--clean` is passed:

- The `.qdrant/` directory is deleted (line 186) and a fresh `VaultStore` is created (line 194)
- Codebase indexing correctly uses `full_index()` (line 225)
- But vault indexing always uses `incremental_index()` (line 212)

Since the store was just created fresh (empty), `incremental_index()` will work correctly -- it sees all documents as "new" and indexes them all. So the result is functionally equivalent to `full_index()`. However, `incremental_index()` has extra overhead: it loads metadata (empty), scans vault, hashes all files, computes deltas. `full_index()` would be more direct and semantically correct for a clean rebuild.

**Severity: MEDIUM** -- functionally correct but semantically wrong and slightly less efficient.

**File:** `cli.py:212`

______________________________________________________________________

## Check 7: `handle_search` -- Store/Model Creation and Cleanup

### Lines 287-297

```python
store = VaultStore(target)
try:
    model = EmbeddingModel()
except (ImportError, RuntimeError) as e:
    _handle_gpu_error(e)
searcher = VaultSearcher(target, model, store)

if search_type == "vault":
    results = searcher.search_vault(query, top_k=max_results)
else:
    results = searcher.search_codebase(query, top_k=max_results)
```

### R14-M2: `handle_search` does not close VaultStore after use (MEDIUM)

`VaultStore(target)` is created at line 287 but never closed. The function returns without calling `store.close()`. For a CLI command (single invocation), the process exits and file handles are released by the OS. But on Windows, Qdrant's file locks may not be released until GC runs, which could cause `PermissionError` for a subsequent `vaultspec-rag index --clean` command run shortly after.

### R14-m5: `handle_search` does not close store if `EmbeddingModel()` raises non-GPU error (Minor)

If `EmbeddingModel()` raises an exception that is NOT `ImportError` or `RuntimeError` (e.g., `MemoryError`, `OSError`), the exception propagates without closing `store`. The `_handle_gpu_error` path calls `typer.Exit()` which also doesn't close the store.

**File:** `cli.py:287-297`

______________________________________________________________________

## Check 8: `--clean` Flag -- Delete `.qdrant/` Before Reindexing

### Lines 181-194

```python
if clean:
    console.log(f"Cleaning existing index at [cyan]{store.db_path}[/]...")
    store.close()
    if store.db_path.exists():
        try:
            shutil.rmtree(store.db_path)
        except PermissionError as e:
            console.print(
                f"[bold red]Error:[/] Cannot delete index — a file is locked ..."
            )
            raise typer.Exit(code=1) from None
    store = VaultStore(target)
```

**Verdict: PASS.** Correctly:

1. Closes the store before deleting (line 183)
1. Handles `PermissionError` on Windows (lines 187-193)
1. Creates a fresh store after deletion (line 194)

The `PermissionError` handler gives a clear error message and exits cleanly.

______________________________________________________________________

## Check 9: `handle_server` / MCP Start

### `mcp_start()` (lines 359-365)

```python
@mcp_app.command("start")
def mcp_start(_ctx: typer.Context):
    from .mcp_server import main as run_mcp
    console.print("[bold green]Launching FastMCP server...[/]")
    run_mcp()
```

**Verdict: PASS.** Deferred import of `mcp_server.main` (avoids loading GPU models at CLI startup). Calls `mcp.run()` which starts the stdio transport. Simple and correct.

Note: The `_ctx` parameter is unused (accepted to satisfy Typer's callback signature).

______________________________________________________________________

## Check 10: Unhandled Exceptions

### Exception handling coverage

| Command         | Exception Handler                                    | Coverage                                     |
| --------------- | ---------------------------------------------------- | -------------------------------------------- |
| `main()`        | `WorkspaceError` -> user-friendly exit               | PASS                                         |
| `handle_index`  | `(ImportError, RuntimeError)` -> `_handle_gpu_error` | PASS for GPU errors                          |
| `handle_search` | `(ImportError, RuntimeError)` -> `_handle_gpu_error` | PASS for GPU errors                          |
| `handle_status` | `ImportError` -> `_handle_gpu_error`                 | Missing `RuntimeError`                       |
| `handle_test`   | None                                                 | PASS -- subprocess isolates errors           |
| `mcp_start`     | None                                                 | OK -- `mcp.run()` has its own error handling |

### R14-m6: `handle_status` does not catch `RuntimeError` from torch CUDA check (Minor)

Line 326-329:

```python
try:
    import torch
except ImportError as e:
    _handle_gpu_error(e)
```

If `torch` imports successfully but `torch.cuda.is_available()` at line 332 raises a `RuntimeError` (e.g., CUDA driver crash), it won't be caught. In practice, `is_available()` returns `False` rather than raising, so this is low risk.

**File:** `cli.py:326-332`

### `pretty_exceptions_enable=False` (line 54)

The Typer app disables pretty exceptions, so unhandled exceptions will produce standard Python tracebacks. This is appropriate for CLI tools (avoids Rich's verbose exception formatting).

### R14-m7: `handle_status` does not close VaultStore (Minor)

Same issue as `handle_search` -- `VaultStore(target)` created at line 341 but never closed.

**File:** `cli.py:341`

______________________________________________________________________

## Summary

| ID     | Severity | Finding                                                                                                 |
| ------ | -------- | ------------------------------------------------------------------------------------------------------- |
| R14-M1 | MEDIUM   | `handle_index` vault always uses `incremental_index()` even with `--clean` -- should use `full_index()` |
| R14-M2 | MEDIUM   | `handle_search` does not close VaultStore after use (Windows file lock risk)                            |
| R14-m1 | MINOR    | `raise SystemExit` instead of `raise typer.Exit` in `handle_test`                                       |
| R14-m2 | MINOR    | `_handle_gpu_error` CUDA string matching is a heuristic                                                 |
| R14-m3 | MINOR    | `--target` silently ignored for `test` and `server` commands                                            |
| R14-m4 | MINOR    | `--debug` and `--verbose` interaction undocumented                                                      |
| R14-m5 | MINOR    | `handle_search` doesn't close store on non-GPU exceptions                                               |
| R14-m6 | MINOR    | `handle_status` doesn't catch `RuntimeError` from torch                                                 |
| R14-m7 | MINOR    | `handle_status` does not close VaultStore                                                               |

**2 MEDIUM findings. 7 MINOR findings.**
