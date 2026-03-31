# Filesystem Watcher Libraries for Python

**Date**: 2026-03-08
**Task**: #6
**Status**: Complete

## Recommendation

**Use `watchfiles`** (by Samuel Colvin, pydantic author). Rust backend via `notify` crate.

## API

- `watch(*paths, debounce=1600, step=50)` — sync generator, yields `set[tuple[Change, str]]`
- `awatch(*paths, debounce=1600, step=50, stop_event=None)` — async generator, uses `anyio.to_thread.run_sync` internally
- `Change` enum: `added`, `modified`, `deleted`
- `watch_filter` parameter: callable `(change, path) -> bool`

## Built-in Debounce

Default 1600ms window. Waits 50ms (`step`) for additional changes, repeating up to `debounce` ms before yielding the batch. This IS the coalescing solution — no manual Timer needed.

## Integration Pattern

```python
from watchfiles import awatch, Change

async def watch_vault(vault_dir: Path):
    async for changes in awatch(vault_dir, debounce=2000):
        changed_paths = {Path(p) for _, p in changes}
        await trigger_incremental_reindex(changed_paths)
```

## Comparison

| Criterion | watchfiles | watchdog |
|---|---|---|
| Async support | Native (anyio awatch) | None (threading only) |
| Built-in debounce | Yes (1600ms default) | No (manual Timer) |
| Event batching | Yes (set of changes) | No (one event per change) |
| Backend | Rust (notify crate) | Python + C extensions |
| Windows | Yes (ReadDirectoryChangesW) | Yes |
| Dependencies | anyio only (already in tree) | None |

## Why Not watchdog

- No async support — pure threading model
- No built-in debounce — each save triggers 2-3 events
- Would need manual `threading.Timer` coalescing
- Would need async bridge to integrate with MCP server
