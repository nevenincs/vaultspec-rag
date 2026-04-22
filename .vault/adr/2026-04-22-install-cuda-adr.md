---
tags:
  - "#adr"
  - "#install-cuda"
date: 2026-04-22
related:
  - "[[2026-04-22-install-cuda-research]]"
  - "[[2026-04-12-vaultspec-rag-install-adr]]"
  - "[[2026-04-06-ecosystem-integration-adr]]"
---

# install-cuda adr: patching consumer pyproject.toml for cu130 torch and actionable cpu-torch errors | (**status:** `proposed`)

## problem statement

`uv add vaultspec-rag` in a fresh consumer project resolves the
CPU-only torch wheel from PyPI. rag's own `[tool.uv.sources]` pin
to the cu130 index does not propagate to consumers (uv scopes
sources to the project that declares them — see
[[2026-04-22-install-cuda-research]]). The CLI then prints
`Error: No CUDA GPU detected` on a machine with a working GPU, with
no in-product remediation.

Two decisions required:

- **Where** the torch-config write lives in rag's source tree, and
  the **exact shape** of the `pyproject.toml` patch, the flag
  surface on `install` / `uninstall`, and the uv-sync handoff.
- **How** `_handle_gpu_error` distinguishes the three distinct
  failure states (no torch / CPU torch / no GPU) and what each
  remediation message says.

## considerations

**Companion delegation contract.** The ecosystem ADR
([[2026-04-06-ecosystem-integration-adr]]) and the install ADR
([[2026-04-12-vaultspec-rag-install-adr]]) require that rag never
directly mutates **shared** repository files that core owns
(`.gitignore`, `.gitattributes`, `.mcp.json`). `pyproject.toml` is
neither rag's nor core's — it is **user-owned**. Precedent from the
install ADR: user-owned artefacts are editable by rag *with an
explicit user consent gate*. This ADR extends that precedent: the
consent gate is a rich `Confirm.ask` prompt (bypassed by `--yes`
and fully opted-out of by `--no-torch-config`).

**Symmetric install / uninstall.** The install ADR established that
uninstall must mirror install: each artefact install writes must
have an uninstall counterpart that removes exactly what we wrote.
This ADR follows the same rule for the torch-config block. The
match predicate for uninstall is the same one install uses for
idempotency: remove iff the entry has rag's canonical shape.

**Layer separation.** The install ADR routed orchestration through
`src/vaultspec_rag/commands.py` and kept `cli.py` as thin Typer
wrappers. This ADR preserves that: torch-config logic lives in a
new dedicated module and is *called from* `commands.py`, not from
`cli.py`. `cli.py` gains two new flags on existing `install` /
`uninstall` wrappers, nothing more.

**Editing user TOML.** `tomlkit` is the standard choice for
round-trip-preserving TOML edits; `tomllib` is read-only. `tomlkit`
is used by poetry, pdm, and astral's own uv writer. Adding it as a
runtime dep is one line. Alternatives (regex, ast-like hand-rolled
parser) are categorically wrong for user files and rejected.

**Scope boundary.** rag is uv-first. This ADR does not add pip,
poetry, or pdm compatibility shims. If the consumer project has no
`pyproject.toml` (or has one with no `[project]` table), the
torch-config step warns and skips — it does not create or upgrade
the file. Users of other tools are directed at the manual snippet
in the error message and the README.

## constraints

- rag must not modify `.gitignore`, `.gitattributes`, `.mcp.json`,
  or any provider dir — all unchanged from prior ADRs.
- The torch-config step is gated by an interactive confirmation
  prompt by default. `--yes` bypasses; `--no-torch-config` skips
  entirely. Non-TTY (CI) detected via `sys.stdin.isatty()` — in
  that case, require `--yes` or `--no-torch-config`, refuse to
  guess.
- The patch is **idempotent**: re-running `install` with no changes
  writes nothing and reports "torch config already present".
- `uninstall` removes only entries that match rag's canonical
  shape. Any customisation the user made is preserved with a
  warning.
- The patch never triggers `uv sync` itself. Users opt in with
  `--sync` if they want the one-liner install.
- No mocks, no skips in tests. Integration tests use real
  `tmp_path` workspaces, real `tomlkit`, and assert the resulting
  TOML round-trips correctly. No subprocess invocation of `uv`
  under test (that would be `--sync`-path territory and is gated
  by its own manual-run test case).
- The three-state error taxonomy must be covered by unit tests
  that construct each state via a real torch import path (no
  monkeypatching torch; use the actual `torch.version.cuda`
  attribute as the signal and test via a small helper that
  receives a `cuda: str | None` argument).
- `vaultspec-rag` itself must not require torch to be importable
  at install-command time. The `install` path is pure file ops +
  tomlkit; torch is loaded lazily elsewhere. Verified in current
  `commands.py` (no torch import) — this ADR does not change that.

## implementation

### module layout

One new file, three modified files:

| file                                          | action   | role                                                                                                                                |
| :-------------------------------------------- | :------- | :---------------------------------------------------------------------------------------------------------------------------------- |
| `src/vaultspec_rag/torch_config.py`           | NEW      | Pure logic for detecting, writing, and removing the canonical cu130 block in a pyproject.toml. No Typer, no Rich, no I/O side-effects beyond the single `atomic_write`. |
| `src/vaultspec_rag/commands.py`               | MODIFIED | `install_run` / `uninstall_run` call into `torch_config` after the seed / sync steps. Two new params thread through: `configure_torch: bool = True`, `assume_yes: bool = False`. |
| `src/vaultspec_rag/cli.py`                    | MODIFIED | `cmd_install` / `cmd_uninstall` gain `--no-torch-config` and `--yes`/`-y`; `cmd_install` gains `--sync`. `_handle_gpu_error` refactored to the three-state taxonomy. The sibling bare check at `cli.py:1652` migrates to use the same helper (or a shared leaf). |
| `src/vaultspec_rag/README.md`, root `README.md` | MODIFIED | Install section updated to `uv add vaultspec-rag && uv run vaultspec-rag install`. Manual cu130 snippet retained for air-gapped users. |
| `pyproject.toml`                              | MODIFIED | Add `tomlkit>=0.13` to `[project] dependencies`. No other changes. |

### canonical cu130 block

Mirrors rag's internal `pyproject.toml:96-104` verbatim:

```toml
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[tool.uv.sources]
torch = [
    { index = "pytorch-cu130", marker = "sys_platform == 'linux' or sys_platform == 'win32'" },
]
```

Module-level constants in `torch_config.py`:

```python
CU130_INDEX_NAME: Final = "pytorch-cu130"
CU130_INDEX_URL: Final = "https://download.pytorch.org/whl/cu130"
CU130_MARKER: Final = "sys_platform == 'linux' or sys_platform == 'win32'"
```

All match predicates and all writes reference these constants — one
source of truth, guaranteed symmetric.

### `torch_config.py` public surface

Six functions, all pure relative to the `pyproject.toml` they
receive as a `Path`:

```python
def detect_state(pyproject: Path) -> TorchConfigState:
    """Classify the current torch-config block at `pyproject`.

    Returns one of: MISSING, CANONICAL, CUSTOMISED, NO_PROJECT_FILE.
    Pure read.
    """

def preview_patch(pyproject: Path) -> str:
    """Return the TOML snippet install would add. Pure read."""

def apply_patch(pyproject: Path) -> PatchReport:
    """Write the cu130 block using tomlkit round-trip semantics.

    Idempotent: returns action="skipped" when state is CANONICAL.
    Refuses when state is CUSTOMISED: returns action="conflict"
    with the conflicting keys in the report. Refuses when state
    is NO_PROJECT_FILE. Otherwise writes via atomic_write.
    """

def remove_patch(pyproject: Path) -> PatchReport:
    """Inverse of apply_patch. Removes only canonical entries.

    Leaves CUSTOMISED entries untouched with a warning. No-op when
    state is MISSING or NO_PROJECT_FILE.
    """

def diagnose_torch(cuda: str | None, available: bool) -> TorchDiagnosis:
    """Classify the torch install state from `torch.version.cuda`
    and `torch.cuda.is_available()`. Returns one of NO_TORCH,
    CPU_ONLY, NO_GPU, WORKING. Used by _handle_gpu_error.
    """

def manual_snippet() -> str:
    """Return the canonical cu130 block as a string for error
    messages and --dry-run output.
    """
```

`TorchConfigState` and `TorchDiagnosis` are `enum.StrEnum`s so the
JSON output surface is stable.

### `commands.py` integration

`install_run` gains two keyword-only parameters:

```python
def install_run(
    path: Path | None = None,
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    force: bool = False,
    skip: set[str] | None = None,
    configure_torch: bool = True,
    assume_yes: bool = False,
    sync_after: bool = False,
) -> InstallReport:
    ...
```

After the existing `seed_builtins` + `sync_provider` steps, a new
block runs:

1. If `configure_torch` is False → skip, note in report.
2. Call `torch_config.detect_state(target / "pyproject.toml")`.
3. If `MISSING`: prompt (bypassed by `assume_yes`) → on yes, call
   `apply_patch`, record the result in the report.
4. If `CANONICAL`: no-op, record "already configured".
5. If `CUSTOMISED`: warn with the conflicting keys, skip.
6. If `NO_PROJECT_FILE`: warn, skip.
7. If `sync_after` is True and the patch was applied,
   `subprocess.run(["uv", "sync", "--reinstall-package", "torch"],
   cwd=target, check=True)`. Errors surface as non-fatal
   warnings on the report.

`InstallReport` gains two fields:

```python
@dataclass
class InstallReport:
    ...
    torch_config_action: str = "skipped"    # applied|skipped|conflict|absent|already
    torch_config_conflicts: list[str] = field(default_factory=list)
```

`uninstall_run` gains one parameter (`assume_yes`) and one report
field (`torch_config_removed: bool`). The `configure_torch` gate is
absent on uninstall — uninstall always attempts symmetric removal
(silent no-op when MISSING). Rationale: uninstall's job is to leave
the workspace as it found it, and the user already consented by
running `uninstall`.

### `cli.py` flag additions

```python
@app.command("install")
def cmd_install(
    ...
    configure_torch: Annotated[bool, typer.Option("--torch-config/--no-torch-config",
        help="Configure cu130 torch index in pyproject.toml (default on)")] = True,
    yes: Annotated[bool, typer.Option("--yes", "-y",
        help="Skip confirmation prompts")] = False,
    sync_after: Annotated[bool, typer.Option("--sync",
        help="Run `uv sync --reinstall-package torch` after patching")] = False,
) -> None:
    ...

@app.command("uninstall")
def cmd_uninstall(
    ...
    yes: Annotated[bool, typer.Option("--yes", "-y",
        help="Skip confirmation prompts")] = False,
) -> None:
    ...
```

No conflicts with existing flags. `--torch-config` follows Typer's
`/--no-foo` bool-flag convention (consistent with the rest of
rag's CLI — confirmed via `cli.py` grep).

### `_handle_gpu_error` refactor

```python
def _handle_gpu_error(exc: Exception) -> None:
    from .torch_config import diagnose_torch, manual_snippet, TorchDiagnosis

    if isinstance(exc, ImportError):
        diagnosis = TorchDiagnosis.NO_TORCH
    else:
        try:
            import torch
            diagnosis = diagnose_torch(torch.version.cuda, torch.cuda.is_available())
        except Exception:  # noqa: BLE001 — defensive fallback
            diagnosis = TorchDiagnosis.NO_TORCH

    if diagnosis == TorchDiagnosis.NO_TORCH:
        console.print(
            "[bold red]Error:[/] PyTorch is not installed.\n\n"
            "  [cyan]uv add vaultspec-rag && uv run vaultspec-rag install[/] "
            "configures the cu130 torch index and installs the GPU build.",
        )
    elif diagnosis == TorchDiagnosis.CPU_ONLY:
        console.print(
            "[bold red]Error:[/] PyTorch was installed without CUDA support "
            "(CPU-only wheel). Your GPU is fine.\n\n"
            "  [cyan]uv run vaultspec-rag install[/] patches your "
            "pyproject.toml with the cu130 torch index. After patching, "
            "rerun [cyan]uv sync --reinstall-package torch[/].\n\n"
            "  Or configure manually in your pyproject.toml:\n"
            + manual_snippet(),
        )
    elif diagnosis == TorchDiagnosis.NO_GPU:
        console.print(
            "[bold red]Error:[/] No CUDA GPU detected.\n"
            "  PyTorch is built with CUDA support, but no CUDA device "
            "is available. Check your NVIDIA driver and CUDA runtime "
            "installation.",
        )
    else:  # WORKING — caller hit an unrelated error; pass through.
        console.print(f"[bold red]Error:[/] {exc}")

    raise typer.Exit(code=1)
```

The bare `cli.py:1652` check in `service_warmup` migrates to call
`_handle_gpu_error(RuntimeError("cuda"))` on failure, inheriting
the same taxonomy — no duplicate messages.

### testing

`src/vaultspec_rag/tests/unit/test_torch_config.py` (new):

- **detect_state** on five fixtures: missing pyproject, pyproject
  with no cu130 block, pyproject with canonical block, pyproject
  with customised block (different URL), pyproject with customised
  block (extra keys in torch source).
- **apply_patch** writes the canonical block into a pyproject that
  has a `[project]` table but no `[tool.uv]`. Round-trip reparse
  succeeds. Diff matches `manual_snippet()`.
- **apply_patch** is idempotent: second call returns
  `action="skipped"` and writes nothing (mtime unchanged).
- **apply_patch** on a customised workspace returns
  `action="conflict"` with the offending keys. File unchanged.
- **apply_patch** preserves user comments, table ordering, and
  inline whitespace in the rest of the document.
- **remove_patch** on the just-applied state leaves the file
  byte-identical to its pre-apply content (the symmetric-mirror
  test).
- **remove_patch** on a customised workspace leaves the customised
  entries in place and emits a warning.
- **diagnose_torch** on the 4 state combinations: (None, False) →
  CPU_ONLY; ("13.0", False) → NO_GPU; ("13.0", True) → WORKING;
  (None, True) → anomaly (fallback to CPU_ONLY; documented).

`src/vaultspec_rag/tests/integration/test_install_torch_config.py`
(new):

- **Fresh install + --yes**: target tmp_path has a minimal
  `pyproject.toml`; `install_run(..., assume_yes=True)` writes the
  cu130 block; report has `torch_config_action="applied"`.
- **Install, uninstall round-trip**: install then uninstall returns
  the file to its original SHA-256.
- **Install with `--no-torch-config`**: report has
  `torch_config_action="skipped"`; pyproject unchanged.
- **Install with no pyproject.toml at target**: report warns,
  file-system untouched, no crash.
- **Install with a customised cu130 block**: report has
  `torch_config_action="conflict"` and lists the conflict; file
  unchanged.
- **Install `--sync` is exercised manually** (requires `uv` in
  PATH and a live network), marked with a new
  `@pytest.mark.subprocess_gpu` variant or just a standalone
  manual-test fixture. Unit path does not shell out to uv.

### required core support

None. Everything this ADR needs is already in place:

- `atomic_write` from core — used by `torch_config.apply_patch`.
- `install_run` / `uninstall_run` orchestration — extended here.
- Existing reconciling sync (core 0.1.10+, prior ADR) — unaffected
  by this feature.

### required rag follow-ups

- `--torch-index URL` flag for cu124 / cu121 / private mirror
  support. Deferred; file as a follow-up issue referencing this
  ADR.
- macOS story: today macOS users get PyPI-torch (no CUDA on macOS
  Silicon is normal). If MPS support in rag becomes a goal,
  revisit the marker string. Deferred.

## rationale

**Patch the consumer's pyproject.toml with consent.** This is the
only way `uv add vaultspec-rag` → `uv run vaultspec-rag index` can
succeed on a fresh GPU machine. Alternatives (an optional `[gpu]`
extra, a `UV_EXTRA_INDEX_URL` environment variable, a published
wrapper distribution) all fail: CUDA wheels are not on PyPI,
env-var-only config is brittle, and a wrapper package is
unnecessarily heavy for a one-liner config block.

**New `torch_config.py` module, not extend `commands.py`.** The
edit logic is non-trivial (parse, match, write, round-trip, diff,
state classification), carries its own tests, and has a small
public surface. Placing it beside `commands.py` mirrors core's
per-resource module pattern (`gitignore.py`, `gitattributes.py`,
`mcps.py`). `commands.py` stays thin and orchestration-focused.

**Three-state diagnosis with a pure function.** The classification
logic (`diagnose_torch(cuda, available)`) is a pure function and
tests directly on the two observable torch attributes without
mocking. Both `_handle_gpu_error` and `service_warmup` consume the
same function, so the error taxonomy never drifts between call-sites.

**tomlkit over regex or stdlib.** User `pyproject.toml` files have
comments, custom key ordering, and inline whitespace that regex
surgery destroys. `tomlkit` preserves all of it. It is the idiomatic
tool for this job and pulling it in is one line of dependency cost.

**Sync opt-in, not default.** Running `uv sync --reinstall-package
torch` implicitly from `install` surprises users who expect
file-only mutations, and breaks in CI / offline / containerised
contexts. `--sync` is the one-liner escape hatch for users who
want it.

**Uninstall always attempts symmetric removal.** Without the gate,
`uninstall` might leave an orphaned cu130 block in the user's
pyproject. Safer default: attempt removal, skip silently when
MISSING, warn when CUSTOMISED.

**Non-TTY safety.** Requiring `--yes` or `--no-torch-config` in
non-interactive contexts prevents hung `install` runs in CI
pipelines. The current CI for rag itself exercises both branches.

## consequences

**positive**

- Consumer workflow shrinks to
  `uv add vaultspec-rag && uv run vaultspec-rag install`.
- Error messages identify the actual failure state and name the
  one-liner fix. No more "No CUDA GPU detected" on working GPUs.
- Uninstall cleanly reverses the change. Users can opt out at any
  time with `--no-torch-config` or by running `uninstall`.
- One source of truth for the canonical block (three module-level
  constants in `torch_config.py`) guarantees symmetric apply /
  remove.
- New `torch_config.py` module matches core's per-resource layout
  (`gitignore.py`, etc.) and nudges rag one step closer to the
  layered structure tracked as a follow-up in the install ADR.

**negative**

- `tomlkit` is a new runtime dependency (~40 KB, pure Python, MIT,
  widely used). Small footprint but not zero.
- Writing to a user's `pyproject.toml` is invasive. Mitigations:
  confirmation prompt, `--yes` / `--no-torch-config` flags,
  `--dry-run` preview, round-trip-preserving writes via
  `tomlkit`, and symmetric uninstall.
- Non-TTY handling (must pass `--yes` or `--no-torch-config`) is
  new UX contract — documented in the README.

**neutral**

- `install` return shape grows by two fields; JSON consumers
  (currently rag's own tests and CI) tolerate additive changes.
- Line 1652 in `cli.py` moves from a bare print-and-exit to the
  central helper — cleans up a divergence that pre-dated this ADR.

## alternatives considered

**Document the manual fix and do nothing else.** Rejected: the
issue explicitly asks for an in-product path. Users running
`uv add vaultspec-rag` expect the advertised experience to work
without reading further docs. README-only fixes violate the
"make the error actionable" acceptance criterion.

**Ship a `vaultspec-rag-bootstrap` CLI / separate package that
bundles cu130 torch.** Rejected: redistributing torch is
license-heavy and size-prohibitive, and forking PyTorch's release
channel is brittle. uv's own docs recommend the index-source
pattern we use.

**Mutate pyproject.toml with regex.** Rejected: destroys comments
and formatting. Fails the "respect user-authored files" criterion.

**Shell out to `uv add --index`.** Rejected on two counts: (a) the
relevant uv subcommand for this is not `uv add` but `uv add
--index` + `uv sources`, which does not yet have a stable
Python-facing API; (b) we'd still need to write the `torch`
source pin separately. Direct tomlkit editing is simpler and more
testable.

**Put `torch_config` logic inside `commands.py`.** Rejected:
bloats `commands.py` past its orchestration role and obscures the
per-resource pattern. Matching core's
`gitignore.py`/`gitattributes.py`/`mcps.py` shape is the
convention.

**Have `_handle_gpu_error` import torch at module level.** Rejected:
torch can be slow to import (~1 s) and the error path must not
pay that tax when `ImportError` already fired. Lazy import inside
the helper keeps the fast path fast.

**Require `--yes` unconditionally (no interactive prompt).**
Rejected: the default UX (prompt on a TTY) is less surprising for
first-time users. The non-TTY fallback is strict; the TTY default
is friendly. Best of both.

**Default `--sync` to on.** Rejected: implicit network / process
invocations surprise users. Opt-in preserves predictability.
