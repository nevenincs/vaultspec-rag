---
tags:
  - '#adr'
  - '#install-command'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-12-vaultspec-rag-install-research]]'
  - '[[2026-04-12-vaultspec-rag-install-reference]]'
---

# `install-command` adr: `vaultspec-rag install/uninstall as a thin core delegator` | (**status:** `proposed`)

## Problem Statement

vaultspec-rag is a companion package to vaultspec-core. PR #52 landed two
static enrollment artifacts (`vaultspec-rag.builtin.md` and
`vaultspec-rag.builtin.json`) but no CLI command exists to seed them
into a workspace. Issues #54 and #55 require `vaultspec-rag install`
and `vaultspec-rag uninstall`.

The architectural questions to resolve are:

- What is the **dependency relationship** between rag and core?
- Where does install **orchestration code live** in rag's source tree
  (which layer, which file)?
- Which **public core APIs** does rag call directly?
- How does the **CLI surface** align with core's?

A previous draft of this ADR proposed `vaultspec_rag/install.py` as a
standalone top-level module and a try/except-ImportError standalone
fallback. Both decisions were wrong: they violate the layer-separation
conventions documented in
`[[2026-02-22-cli-ecosystem-factoring-adr]]` (which the audit
confirmed in core's actual layout) and contradict the project's
ecosystem direction in `[[2026-04-06-ecosystem-integration-adr]]`,
which already has rag depending on core. This ADR replaces that draft
end-to-end.

## Considerations

**Layer separation conventions in vaultspec-core (the canonical
reference).** The structural audit of `src/vaultspec_core/` shows:

- `cli/` subpackage holds Typer wiring only — `cli/root.py:cmd_install`,
  `cmd_uninstall`, `cmd_sync` are thin wrappers that parse args and
  delegate immediately.
- `core/` subpackage holds business logic. Top-level orchestration
  (`install_run`, `uninstall_run`, `sync_provider`) lives in
  `core/commands.py`. Per-resource logic lives alongside in
  `core/{rules,skills,agents,mcps,system,sync,manifest,gitignore, gitattributes}.py`.
- **There is no file named `install.py` anywhere in core.** Install
  is a *command* implemented inside `core/commands.py`, not a *module*.
- Dependency direction is strictly unidirectional: `cli/` imports from
  `core/`; `core/` never imports from `cli/`. This makes `core/`
  reusable by the MCP server, programmatic callers, and tests without
  pulling in Typer.

**Public API surface of vaultspec-core for downstream callers.** The
audit of `vaultspec_core/core/__init__.py` shows 59 symbols re-exported
as the stable public surface, including (relevant to rag):

- Orchestration: `install_run`, `uninstall_run`, `sync_provider` (in
  `core.commands`, not re-exported through `core/__init__.py` but
  importable directly and called by core's own CLI without
  intermediation).
- Workspace bootstrap: `resolve_workspace` (in
  `vaultspec_core.config.workspace`) and `init_paths` (in
  `vaultspec_core.core.types`). The first computes the
  `WorkspaceContext` from a target path; the second installs that
  context as the active runtime context that `sync_provider` reads
  to locate `.vaultspec/` and `.mcp.json`. Both must be called
  before the first `sync_provider` invocation.
- Per-resource: `mcp_add`, `mcp_remove`, `mcp_list`, `mcp_sync`,
  `collect_mcp_servers`, `rules_sync`, `collect_rules`.
- Helpers: `atomic_write`, `build_file`, `ensure_dir`.
- Types and exceptions: `SyncResult`, `WorkspaceContext`, `ToolConfig`,
  `VaultSpecError`, `ResourceExistsError`, `ResourceNotFoundError`,
  `WorkspaceNotInitializedError`, `ProviderError`,
  `ProviderNotInstalledError`.

All are documented, typed, and stable in core 0.1.9. None are marked
deprecated or experimental.

**Current state of rag's source tree.** The audit of
`src/vaultspec_rag/` shows a **flat** layout: every module (`store`,
`search`, `indexer`, `embeddings`, `api`, `config`, `workspace`,
`mcp_server`, `service`, `watcher`, `cli`, …) lives directly under
`src/vaultspec_rag/`. There is no `cli/` subpackage and no `core/`
subpackage. `cli.py` is ~1800 lines and registers 13 Typer commands.
**The flat layout is a known long-standing divergence from core's
layered structure**, not introduced by this work. Refactoring rag
toward `cli/` + `core/` subpackages is out of scope for this PR (filed
as a follow-up issue) but this PR introduces the **foothold**: a new
`commands.py` module that mirrors core's `core/commands.py` role and
gives the future refactor a clear target.

**Existing dependency on core.** rag's `pyproject.toml` already pins
`vaultspec-core>=0.1.0`. core is therefore already a hard dependency
of rag — there is no "rag works without core" scenario today. The
previous ADR draft's standalone-fallback path was based on a
misreading of the project state.

**Symmetric install/uninstall via core's reconciling sync.** Both
install and uninstall are pure mirror operations on rag's local
source files: install adds the bundled builtins, uninstall removes
them. Both then call `vaultspec_core.core.commands.sync_provider`
to propagate the change to `.mcp.json` and provider dirs. This is
the only design that scales — any other approach (targeted
`mcp_remove`, hand-rolled `.mcp.json` mutation, etc.) breaks the
symmetry and bakes ownership knowledge into rag that belongs in
core. The cost is that core's `mcp_sync()` must be a *reconciling*
operation, not purely additive: when a source file is gone, sync
must prune the corresponding destination entry. Today core's
`mcp_sync()` is additive only. **The orphan-pruning fix in core is
a hard prerequisite** for this rag PR and is implemented as a
sister PR against `vaultspec-core` landing first. See "Required
Core Support" below.

## Constraints

- rag declares `vaultspec-core>=0.1.9` as a hard dependency in
  `pyproject.toml` (bumped from `>=0.1.0` to guarantee the public
  symbols this ADR relies on). No try/except-ImportError fallback.
- rag must follow core's layer separation: install orchestration lives
  in a new `src/vaultspec_rag/commands.py` (mirroring
  `core/commands.py`), and Typer wrappers live in `cli.py` and
  immediately delegate. No file named `install.py`.
- rag's CLI flag names must match core's `cli/root.py:cmd_install` and
  `cmd_uninstall` exactly for every flag whose meaning is shared.
  100% alignment is required.
- rag's `commands.py` orchestration functions must mirror core's
  `install_run`/`uninstall_run` parameter names and types as closely
  as the rag use case allows.
- Files rag exclusively owns (its bundled builtin rule and MCP files
  inside `.vaultspec/rules/`, its index under `.vault/data/`) may be
  written directly by rag using core's atomic write helpers
  (`vaultspec_core.core.helpers.atomic_write`), not a hand-rolled
  helper.
- Files core owns (`.gitignore`, `.gitattributes`, `.mcp.json`,
  manifest, provider dirs) are mutated **only** through core's public
  API calls (`mcp_add`, `mcp_remove`, `sync_provider`). rag does not
  read or write these files directly.
- `seed_builtins` must use `importlib.resources.files()` for resource
  enumeration, mirroring core's `builtins/__init__.py:seed_builtins`.
- No mocks, fakes, or skips in tests. Integration tests run against
  the real filesystem and a real installed `vaultspec-core` (which
  is in the dev environment by definition).

## Implementation

### Module Layout

This PR adds two files and modifies two:

| File                                     | Action   | Role                                                                                                           |
| :--------------------------------------- | :------- | :------------------------------------------------------------------------------------------------------------- |
| `src/vaultspec_rag/commands.py`          | NEW      | Orchestration. `install_run`, `uninstall_run`. Mirrors `vaultspec_core/core/commands.py` role.                 |
| `src/vaultspec_rag/builtins/__init__.py` | NEW      | `seed_builtins`, `list_builtins`. Mirrors `vaultspec_core/builtins/__init__.py`.                               |
| `src/vaultspec_rag/cli.py`               | MODIFIED | Add `cmd_install` and `cmd_uninstall` Typer wrappers that delegate to `commands.py`.                           |
| `pyproject.toml`                         | MODIFIED | (a) bump `vaultspec-core>=0.1.9`; (b) add hatch `force-include` `.vaultspec/rules` → `vaultspec_rag/builtins`. |

The rag-side directory layout after this PR:

```text
src/vaultspec_rag/
├── builtins/                    # NEW (bundled, populated at wheel build)
│   ├── __init__.py              # seed_builtins / list_builtins
│   └── rules/
│       ├── rules/vaultspec-rag.builtin.md
│       └── mcps/vaultspec-rag.builtin.json
├── commands.py                  # NEW (orchestration)
├── cli.py                       # MODIFIED (thin Typer wrappers)
├── ... (existing modules untouched)
```

**A future refactor** (filed as a separate issue against this repo)
will move rag toward core's full layered shape: introducing
`src/vaultspec_rag/cli/` and `src/vaultspec_rag/core/` subpackages and
relocating existing modules. This ADR explicitly does NOT do that
work — scope discipline. The new `commands.py` is positioned so the
future refactor moves it into `core/commands.py` with no changes to
its callers.

### Dependency on core

`pyproject.toml` `[project] dependencies` updates:

```toml
"vaultspec-core>=0.1.9",   # bumped from >=0.1.0
```

Justification: 0.1.9 is the version where the public symbols this
ADR relies on (`install_run`, `uninstall_run`, `sync_provider`,
`mcp_add`, `mcp_remove`, `mcp_list`, `atomic_write`) are all
documented and stable per the audit.

### Bundling

`pyproject.toml` adds (mirrors core's pattern verbatim):

```toml
[tool.hatch.build.targets.wheel.force-include]
".vaultspec/rules" = "vaultspec_rag/builtins"
```

The repo's existing `.vaultspec/rules/rules/vaultspec-rag.builtin.md`
and `.vaultspec/rules/mcps/vaultspec-rag.builtin.json` ship in the
wheel under `vaultspec_rag/builtins/rules/`.

### `vaultspec_rag/builtins/__init__.py`

Mirrors `vaultspec_core/builtins/__init__.py` exactly. Two public
functions:

```python
def seed_builtins(target_rules_dir: Path, *, force: bool = False) -> list[str]:
    """Recursively copy bundled builtins into target_rules_dir.

    Skips destinations that already exist unless force=True.
    Returns relative paths actually written.
    """

def list_builtins() -> list[str]:
    """Enumerate bundled builtin file paths (relative)."""
```

Internally uses `importlib.resources.files("vaultspec_rag.builtins")`
to walk the bundled tree, and `vaultspec_core.core.helpers.atomic_write`
for the actual file writes — keeps atomic-write semantics consistent
with core, no hand-rolled helper.

### `vaultspec_rag/commands.py`

Two top-level public functions, parameter names and order mirroring
core's `install_run` / `uninstall_run` exactly where the meaning is
shared:

```python
def install_run(
    path: Path,
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
) -> dict[str, Any]:
    """Install vaultspec-rag enrollment into a workspace.

    Steps:
      1. Resolve workspace via vaultspec_core.config.workspace.resolve_workspace
      2. mkdir -p .vault/, .vault/data/, .vaultspec/rules/rules/, .vaultspec/rules/mcps/
      3. seed_builtins(.vaultspec/rules/, force=force or upgrade)
      4. vaultspec_core.core.commands.sync_provider("all", dry_run, force, skip)
      5. Return result dict shaped like core's install_run result
    """

def uninstall_run(
    path: Path,
    *,
    remove_data: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
) -> dict[str, Any]:
    """Remove vaultspec-rag enrollment from a workspace.

    Symmetric mirror of install_run: uninstall removes the source
    files rag owns, then invokes core's sync to propagate the
    removal. Same propagation primitive as install — same code path,
    inverted intent.

    Steps:
      1. Refuse without force=True (return dry-run preview)
      2. unlink rag's two builtin files from
         .vaultspec/rules/rules/vaultspec-rag.builtin.md and
         .vaultspec/rules/mcps/vaultspec-rag.builtin.json
      3. vaultspec_core.core.commands.sync_provider("all", dry_run, force, skip)
         — propagates the source-file removal to .mcp.json and
         provider dirs (depends on core's reconciling sync — see
         "Required Core Support" below)
      4. If remove_data: rmtree .vault/data/
      5. Return result dict shaped like core's uninstall_run result

    rag's uninstall NEVER touches core's installation. It removes
    only files rag owns and lets core's sync handle propagation.
    """
```

Dependencies on core (direct imports — no try/except, core is hard dep):

```python
from vaultspec_core.config.workspace import resolve_workspace
from vaultspec_core.core.commands import sync_provider
from vaultspec_core.core.types import init_paths
from vaultspec_core.core.helpers import atomic_write
from vaultspec_core.core.exceptions import VaultSpecError, ResourceNotFoundError
```

Exceptions: `commands.py` raises core's `VaultSpecError` subclasses
directly. No new exception types — rag's commands return the same
shaped error surface as core's commands, so callers (CLI wrappers,
tests, future programmatic users) get a uniform contract.

Result dicts: same shape as core's `install_run` / `uninstall_run`
return values per the audit (`{"action": ..., "items": [...], "seeded_count": ..., "path": ...}`). This means rag's reports can be
rendered by the same Rich helpers core uses if rag chooses to import
them, and JSON output via `--json` is structurally identical.

### `vaultspec_rag/cli.py` additions

Two new Typer commands added to the existing root `app`. Wrappers
are thin — parse args, call into `commands.py`, render result, exit.
Flag names match `vaultspec_core/cli/root.py:cmd_install` and
`cmd_uninstall` verbatim.

```python
from .commands import install_run, uninstall_run

@app.command("install")
def cmd_install(
    target: Annotated[Path | None, typer.Option("--target", "-t", help="Workspace path")] = None,
    upgrade: Annotated[bool, typer.Option("--upgrade", help="Re-seed bundled rule/MCP files even if present")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview changes without writing")] = False,
    force: Annotated[bool, typer.Option("--force", help="Override contents if already installed")] = False,
    skip: Annotated[list[str] | None, typer.Option("--skip", help="Skip a component (repeatable)")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    ...

@app.command("uninstall")
def cmd_uninstall(
    target: Annotated[Path | None, typer.Option("--target", "-t", help="Workspace path")] = None,
    remove_data: Annotated[bool, typer.Option("--remove-data", help="Also remove .vault/data/ (rag's index)")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview changes without removing")] = False,
    force: Annotated[bool, typer.Option("--force", help="Required to execute. Uninstall is destructive.")] = False,
    skip: Annotated[list[str] | None, typer.Option("--skip", help="Skip a component (repeatable)")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    ...
```

Flag-by-flag alignment with core:

| Flag                       | Core install | Core uninstall | rag install | rag uninstall | Notes                                             |
| :------------------------- | :----------- | :------------- | :---------- | :------------ | :------------------------------------------------ |
| `--target` / `-t`          | yes          | yes            | yes         | yes           | identical, including short form                   |
| `--dry-run`                | yes          | yes            | yes         | yes           | identical                                         |
| `--force`                  | yes          | yes            | yes         | yes           | identical                                         |
| `--skip NAME` (repeatable) | yes          | yes            | yes         | yes           | identical                                         |
| `--json`                   | yes          | yes            | yes         | yes           | identical                                         |
| `--upgrade`                | yes          | —              | yes         | —             | identical (install only)                          |
| `--remove-vault`           | —            | yes            | —           | —             | core-specific (removes user `.vault/` docs)       |
| `--remove-data`            | —            | —              | —           | yes           | rag-specific (removes rag's index `.vault/data/`) |
| Positional `provider`      | yes          | yes            | —           | —             | omitted: rag has no provider concept              |

The `--remove-data` vs `--remove-vault` divergence is intentional and
documented: the *flag pattern* is identical (default-off, "also
remove" semantics) but the underlying scope differs (rag removes its
own index, core removes user vault documents). Naming them
identically would be misleading.

### Testing

`src/vaultspec_rag/tests/integration/test_install.py` — new file,
real filesystem via `tmp_path`, real `vaultspec_core` (already
installed in dev env per pyproject pin). No mocks. Coverage:

- **Fresh install:** mkdirs created, both builtin files seeded into
  `.vaultspec/rules/`, core's `sync_provider` propagates them,
  resulting `.mcp.json` contains `vaultspec-search-mcp`, provider
  dirs (e.g. `.claude/rules/`) contain the propagated rule.
- **Idempotent re-install:** second `install_run` is a no-op except
  for reporting.
- **`--upgrade` and `--force`:** re-seed even when files exist.
- **`--dry-run` install:** prints preview, no filesystem changes.
- **Uninstall without `--force`:** dry-run preview only.
- **Uninstall with `--force`:** rag's two builtin files removed,
  `mcp_remove` cleanly removes the entry from `.mcp.json`,
  `sync_provider` propagates the rule deletion to provider dirs,
  `.vault/` and vault docs untouched.
- **Uninstall with `--remove-data`:** `.vault/data/` is removed;
  without it, the index survives.
- **Pre-existing user content** in `.vaultspec/`, `.mcp.json`, and
  provider dirs is preserved across both install and uninstall.
- **`--json` output** parses as valid JSON for both commands.
- **CLI integration:** invoke `vaultspec-rag install` and
  `vaultspec-rag uninstall` via Typer's testing client, assert exit
  codes and output panels.

## Required Core Support

One blocker plus four follow-ups. The blocker ships in a sister PR
against `vaultspec-core` and lands before this rag PR merges. The
follow-ups inform the modular ecosystem roadmap and do not block
shipping.

- **(BLOCKER) Reconciling `sync_provider` / `mcp_sync()`.** Today
  `mcp_sync()` is purely additive: it iterates only over sources
  with existing definition files. When a source is deleted and
  sync runs, the destination entry in `.mcp.json` lingers as an
  orphan. The same gap likely exists for `rules_sync`, `agents_sync`,
  and the other per-resource sync functions. **Fix in core:** sync
  must reconcile — after merging current sources, iterate over
  destination entries and prune any whose corresponding source has
  been removed. To preserve user-added entries (those that never
  had a source file in `.vaultspec/rules/`), distinguish them by
  source-existence at last sync, not by name. The simplest viable
  approach: track managed entries in `manifest.json` (or under a
  reserved key inside `.mcp.json` itself) and prune only those
  whose source is now absent. This sister PR is implemented as
  part of the same effort as this rag PR, lands first, and unblocks
  rag's symmetric uninstall.

- **(L) Companion discovery API.** No `vaultspec.companions` Python
  entry-point group. Companions must implement their own `install`
  command. With a discovery API, `vaultspec-core install` could
  enumerate installed companions and seed all their builtins.

- **(L) Companion-declared `.gitignore` entries.**
  `get_recommended_entries()` is hardcoded. Moot for rag today
  (`.vault/` already covered) but blocks future companion needs.

- **(L) Companion-declared `.gitattributes` entries.** Same shape
  as gitignore.

- **(L) Manifest companion tracking.** `ManifestData` has no
  `companions` field. Without it, `vaultspec-core uninstall vaultspec-rag` cannot exist as a first-class operation.

A grouped tracking issue **"companion-package extension API"** in
vaultspec-core should reference this ADR and link the sub-issues.

## Required rag Follow-Up Issues (filed against this repo)

- **Refactor rag toward layered structure.** Move existing modules
  (`store`, `search`, `indexer`, `embeddings`, `api`, `config`,
  `workspace`, `mcp_server`, `watcher`, `service`) into
  `src/vaultspec_rag/core/` and split `cli.py` into a `cli/`
  subpackage with `cli/root.py`, `cli/_target.py`, etc., mirroring
  core's exact shape per the structural audit. This ADR introduces
  `commands.py` as the foothold; the larger refactor is its own
  PR with its own ADR.

## Rationale

**Hard dependency on core, direct imports.** rag already depends on
core. Acknowledging that and using core's public API directly is
strictly better than the previous draft's try/except-ImportError
fallback, which was based on a misreading of the project state. The
audit confirmed the symbols rag needs (`install_run`,
`uninstall_run`, `sync_provider`, `mcp_remove`, `atomic_write`) are
documented, typed, stable, and used by core's own CLI without
intermediation.

**Orchestration lives in `commands.py`, not `install.py`.** Mirrors
core's exact pattern: `core/commands.py` is the orchestration layer
in core, with `cli/root.py` as the thin Typer wrapper. The previous
draft's `install.py` violated this convention by inventing a new
module type that core does not have. Naming the new file
`commands.py` lines it up for the future layered refactor with zero
churn — when rag adopts `core/` and `cli/` subpackages, this file
moves to `core/commands.py` and its callers don't change.

**Symmetric install/uninstall via core's reconciling sync.**
Uninstall is a pure mirror of install: same primitives, inverted
intent. rag deletes its source files; core's sync propagates the
deletion. This is the only design that scales to a modular companion
ecosystem — any other approach (targeted `mcp_remove`, hand-rolled
`.mcp.json` mutation, ownership-tracking inside rag) bakes
ownership knowledge into rag that belongs in core. The cost is the
core orphan-pruning fix, which lands in the sister PR.

**100% CLI flag alignment.** Audit captured core's exact Typer
signatures for `cmd_install`, `cmd_uninstall`, `cmd_sync`. rag mirrors
flag names verbatim. The one divergence (`--remove-data` vs
`--remove-vault`) is documented as intentional and reflects different
scope, not different convention.

**Atomic writes via `core.helpers.atomic_write`.** Reuses the
already-tested core helper instead of forking another implementation.
One source of truth for crash-safe writes across the ecosystem.

**Bundling via hatch `force-include`.** Same idiom contributors
already know from core.

**Refactor scoped out.** rag's flat layout is a long-standing
divergence from core's layered shape. Fixing it inside this PR would
violate scope discipline and produce a sprawling diff. Filing it as
a separate issue with this ADR as the foothold is the disciplined
path.

## Consequences

**Positive.**

- rag's install is **trivially small** — `commands.py` is ~80 lines,
  `cli.py` additions are ~30 lines, `builtins/__init__.py` is ~40
  lines.
- 100% CLI flag alignment with core means users move between the two
  commands without re-learning anything.
- Direct use of core's public API means rag inherits all of core's
  improvements automatically (atomic-write semantics, exception
  hierarchy, sync result shape, JSON output).
- Symmetric install/uninstall via the same `sync_provider`
  primitive — no special-case removal code, no ownership knowledge
  baked into rag.
- The new `commands.py` file is positioned as the foothold for the
  future layered refactor: same role, same name as the slot it will
  occupy in `core/commands.py`.
- Zero risk of `.gitignore` / `.mcp.json` conflicts between rag and
  any other companion, because rag never touches those files
  directly.

**Negative.**

- This rag PR is **gated on the core orphan-pruning sister PR**
  landing first. The two PRs are implemented together as one
  effort, with the core fix merged first. Without it, rag's
  uninstall would leave an orphaned `.mcp.json` entry, which
  breaks the symmetric design.
- rag now imports several core submodules
  (`vaultspec_core.core.commands`, `vaultspec_core.core.helpers`,
  `vaultspec_core.config.workspace`). If core renames these in
  a major release, rag breaks. Mitigation: pin
  `vaultspec-core>=0.1.10,<0.2` (the version containing the
  orphan-pruning fix) and surface a clear upgrade-path error.
- The flat-layout debt in rag remains — only the new code follows
  core's layered convention. Mitigation: tracked follow-up issue
  with this ADR as the foothold.

**Neutral.**

- New `vaultspec_rag.commands` and `vaultspec_rag.builtins` modules
  join the public import surface — internal-by-convention.
- `pyproject.toml` gains a `force-include` block; the wheel grows by
  the size of the bundled rules tree (currently ~few KB).
- Core dep pin tightens from `>=0.1.0` to `>=0.1.9`. No downstream
  consumers affected (rag is leaf-level for end users).

## Alternatives Considered

**`src/vaultspec_rag/install.py` as a top-level module (previous
draft).** Rejected: violates the layer convention documented in
`[[2026-02-22-cli-ecosystem-factoring-adr]]` and confirmed in
core's actual src layout. Core has no `install.py`; install lives in
`core/commands.py`. rag mirrors that.

**Inline orchestration directly in `cli.py` Typer command bodies.**
Rejected: `cli.py` is already ~1800 lines and integration-testing
orchestration without invoking the Typer client is much harder.
Separating orchestration into `commands.py` is exactly the pattern
core follows for the same reasons.

**Try/except-ImportError standalone fallback (previous draft).**
Rejected: rag already declares `vaultspec-core>=0.1.0` as a hard
dependency; the standalone fallback was based on a misreading. Drop
the entire framing.

**Subprocess invocation of `vaultspec-core sync`.** Rejected: when
core is a hard dependency, direct import is strictly better — faster,
structured exceptions, no PATH resolution, no process boundary, and
matches how core's own CLI calls into `core/commands.py`.

**rag mutates `.mcp.json` directly with idempotent merge logic.**
Rejected: violates the modular companion model and creates a class
of conflicts when multiple companions try to manage the same file.
Core is the single writer.

**Targeted `mcp_remove` for uninstall (instead of symmetric sync).**
Rejected: bakes ownership knowledge into rag and breaks the
mirror-of-install symmetry. The clean architectural path is for
core's sync to be a reconciling operation; the orphan-pruning fix
is implemented in the sister core PR and lands first.

**Refactor rag's flat layout to layered (`cli/` + `core/`)
subpackages inside this PR.** Rejected: scope discipline.
`commands.py` is the minimum-viable foothold; the full refactor is
its own effort.

**Hard-rolled atomic write helper inside rag.** Rejected: reuse
`vaultspec_core.core.helpers.atomic_write` for one source of truth.
