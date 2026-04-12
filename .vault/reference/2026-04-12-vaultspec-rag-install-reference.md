---
tags:
  - '#reference'
  - '#install-command'
date: 2026-04-12
related:
  - '[[2026-04-12-vaultspec-rag-install-adr]]'
---

# vaultspec-core Install/Uninstall/Sync Pipeline Reference

This document captures vaultspec-core's concrete implementation patterns for bundling, installation, uninstall, and sync operations.

## 1. Builtins Bundling

### pyproject.toml Force-Include (lines 96-100)

Source `.vaultspec/rules/` bundled into wheel as `vaultspec_core/builtins/`:

```toml
[tool.hatch.build.targets.wheel.force-include]
".vaultspec/rules" = "vaultspec_core/builtins"
```

### seed_builtins() - src/vaultspec_core/builtins/__init__.py:48-87

Recursively walk bundled tree, skip Python artifacts, write if not exists or force=True:

```python
def seed_builtins(target_rules_dir: Path, *, force: bool = False) -> list[str]:
    src = _builtins_root()
    written = []
    for src_file in sorted(src.rglob("*")):
        if not src_file.is_file() or src_file.name in ("__init__.py", "__pycache__"):
            continue
        rel = src_file.relative_to(src)
        dest = target_rules_dir / rel
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest)
        written.append(str(rel).replace("\\", "/"))
    return written
```

### check_outdated() - src/vaultspec_core/builtins/__init__.py:107-133

Binary comparison detects out-of-date files. Used by sync to prompt for upgrade.

## 2. Install Orchestration

### install_run() - src/vaultspec_core/core/commands.py:596-863

Step order:

1. Validate provider, bootstrap WorkspaceContext
1. Create .vaultspec/ and .vault/ directories
1. Seed builtins to .vaultspec/rules/
1. Call init_run() which scaffolds providers and calls init_paths()
1. Call sync_provider() to propagate rules/skills/agents
1. ensure_gitignore_block() with recommended entries
1. Write manifest.json with installation metadata

**Workspace Init:** Creates .vaultspec/ and .vault/ if needed. For upgrade, existing .vaultspec/ required.

## 3. Atomic Writes

### atomic_write() - src/vaultspec_core/core/helpers.py:201-228

PID-suffixed temp file + Path.replace() on POSIX. Windows fallback: copyfile + unlink.

```python
def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_bytes(content.encode("utf-8"))
    try:
        tmp.replace(path)
    except PermissionError:
        shutil.copyfile(tmp, path)
        tmp.unlink(missing_ok=True)
```

## 4. Gitignore Management

### ensure_gitignore_block() - src/vaultspec_core/core/gitignore.py:154-262

Markers delimit managed block:

```python
MARKER_BEGIN = "# >>> vaultspec-managed (do not edit this block) >>>"
MARKER_END = "# <<< vaultspec-managed <<<<<"
```

Idempotent: detect markers, update in-place, append if missing. Handles malformed blocks by removing all and appending fresh. Preserves line ending (CRLF vs LF), BOM, uses advisory lock.

### get_recommended_entries() - src/vaultspec_core/core/gitignore.py:22-77

Returns dynamically computed entries: .vaultspec/\_snapshots/, .vault/\*, .mcp.json, provider dirs and config files.

## 5. MCP Scaffolding

### mcp_sync() - src/vaultspec_core/core/mcps.py:215-286

Collects MCP definitions from .vaultspec/rules/mcps/\*.json, merges into .mcp.json:

```python
def mcp_sync(dry_run: bool = False, force: bool = False) -> SyncResult:
    sources = collect_mcp_servers()
    with advisory_lock(mcp_json):
        existing = {}
        if mcp_json.exists():
            existing = json.loads(mcp_json.read_text())
        servers = existing.setdefault("mcpServers", {})
        
        for name, (_, config) in sources.items():
            if name not in servers:
                servers[name] = config
            elif servers[name] != config:
                if force:
                    servers[name] = config
        
        if changed and not dry_run:
            atomic_write(mcp_json, json.dumps(existing, indent=2) + "
")
```

**JSON shape:** `.mcp.json` has top-level `mcpServers` dict.

**Merge pattern:** Additive by default, preserves user entries, non-destructive without force.

## 6. Uninstall Safety

### uninstall_run() - src/vaultspec_core/core/commands.py:866-1160

Safety boundaries:

- --force required (unless dry_run)
- keep_vault=True by default (preserves .vault/)
- Surgical .mcp.json cleanup via mcp_uninstall()
- Per-provider protection (shared directories preserved if any owner skipped)

### mcp_uninstall() - src/vaultspec_core/core/mcps.py:289-340

Removes only managed entries from mcpServers, preserves user entries, deletes file if empty. Falls back to {"vaultspec-core"} if registry unavailable.

## 7. CLI Wiring

### cmd_install - src/vaultspec_core/cli/root.py:179-326

Typer argument for provider, options: --target, --upgrade, --dry-run, --force, --skip (repeatable), --json.

### cmd_sync - src/vaultspec_core/cli/root.py:445-661

Calls sync_provider(provider, dry_run=dry_run, force=force, skip=set(skip)).

## 8. Sync Propagation

### sync_provider() - src/vaultspec_core/core/commands.py:1271-1370

Pass order: rules, skills, agents, system, config, (optional) mcps.

Post-sync hook (if provider=="all"):

```python
from vaultspec_core.hooks import fire_hooks
fire_hooks("config.synced", {"root": str(ctx.target_dir), "event": "config.synced"})
```

**Integration in install_run:** Direct function call (not subprocess). Errors logged as warnings, non-fatal.

## Key Design Insights for vaultspec-rag

1. Builtins discoverable via importlib.resources + directory detection
1. Seeding idempotent: force controls overwrite
1. Atomic writes: PID-suffixed temp + Path.replace()
1. Gitignore managed with markers, idempotent logic
1. MCP defs merged in shared file, preserves user entries
1. Sync called after scaffold
1. Uninstall safe: --force required, preserves .vault/, surgical removal
1. **Important:** rag can optionally call vaultspec-core sync via direct function call (gracefully skip if core unavailable) or subprocess
