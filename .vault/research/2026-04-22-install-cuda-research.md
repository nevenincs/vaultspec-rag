---
tags:
  - "#research"
  - "#install-cuda"
date: 2026-04-22
related:
  - "[[2026-04-12-vaultspec-rag-install-adr]]"
  - "[[2026-04-06-ecosystem-integration-adr]]"
---

# install-cuda research: configuring torch cuda for consumer projects

## problem

A fresh consumer project running `uv add vaultspec-rag` on Linux or
Windows resolves the **CPU-only** torch wheel from PyPI. On the next
`uv run vaultspec-rag index` the CLI prints:

```
Error: No CUDA GPU detected.
vaultspec-rag requires a CUDA-capable NVIDIA GPU.
```

…on a machine that has a CUDA GPU. Two distinct failures stack up:

- The `pyproject.toml` mechanism that pins `torch` to the cu130 index
  in **rag's** workspace does not propagate to the consumer. Consumers
  therefore get PyPI-torch (CPU-only on Linux/Windows).
- The CLI's `_handle_gpu_error` branch in `src/vaultspec_rag/cli.py:58`
  cannot distinguish "torch has no CUDA support" from "CUDA GPU
  missing" and prints the wrong remediation.

Scope: GitHub issue [#81](https://github.com/wgergely/vaultspec-rag/issues/81).

## uv source-propagation semantics

`[tool.uv.sources]` and `[[tool.uv.index]]` are a **development-time
construct scoped to the project or workspace** that declares them.
They are not publishable metadata. The
[uv dependency docs](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-sources)
state verbatim:

> Sources are only respected by uv. If another tool is used, only the
> definitions in the standard project tables will be used.

And, more decisively, sources are not carried in wheel metadata:
when rag's wheel is published to PyPI, only `[project] dependencies`
reaches the consumer's resolver. The cu130 pin in rag's
`pyproject.toml` is invisible.

This is deliberate — the Python packaging spec forbids a dependency
from rewriting the consumer's resolver configuration. No patch to
rag's `pyproject.toml` shape can change this. A downstream consumer
must opt-in to the cu130 index themselves.

### `explicit = true` scope

`explicit = true` on a named index means that index is used **only**
for packages that name it in `tool.uv.sources`. This prevents the
pytorch index from leaking into resolution for unrelated packages.
The flag is respected **only in the project that declares the index**;
it has no effect on downstream consumers because the declaration
never reaches them.

### Why a `[gpu]` extra does not help

PyTorch's CUDA wheels are not on PyPI. They live on
`https://download.pytorch.org/whl/cu<ver>`. A `[gpu]` extra on rag
that adds `torch>=2.4` still resolves from PyPI, which serves only the
CPU-only `torch` wheels on Linux and Windows. There is no release
channel on PyPI that maps to CUDA wheels.

## the workable shape

rag must **patch the consumer's `pyproject.toml`** to add the cu130
index and the torch source pin. The canonical shape (matches rag's
own `pyproject.toml:96-104`):

```toml
[tool.uv.sources]
torch = [
    { index = "pytorch-cu130", marker = "sys_platform == 'linux' or sys_platform == 'win32'" },
]

[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true
```

- `explicit = true` keeps the index scoped to torch.
- The marker leaves macOS untouched (PyTorch on macOS ships CUDA-less
  universal/mps wheels from PyPI).
- `pytorch-cu130` is the canonical name already used by rag; keeping
  the same name across rag and consumer makes the patch recognisable
  on uninstall.

After writing the block, the consumer needs
`uv sync --reinstall-package torch` to swap the cached CPU wheel for
the cu130 wheel.

## detecting cpu-only torch vs no-gpu

`torch` exposes three observable states for CUDA support:

| State                   | `torch.version.cuda`      | `torch.cuda.is_available()` | Meaning                                  |
| :---------------------- | :------------------------ | :-------------------------- | :--------------------------------------- |
| CPU-only wheel          | `None`                    | `False`                     | Packaging problem                        |
| CUDA wheel, no GPU      | `"13.0"` (or similar str) | `False`                     | Driver / hardware problem                |
| CUDA wheel, GPU present | `"13.0"` (or similar)     | `True`                      | Working                                  |

The current `_handle_gpu_error` in `src/vaultspec_rag/cli.py:58`
collapses the first two states into one message, which is wrong for
the far-more-common consumer case (CPU-only wheel). We need to
**branch on `torch.version.cuda is None`** before deciding the message.

A fourth state, `ImportError`, is separate: torch wasn't installed
at all. The existing branch for this is already correct.

## tomlkit as the editing vehicle

The `pyproject.toml` we are patching is **user-authored**. It almost
certainly contains comments, formatting, and ordering that must be
preserved. Two candidates:

- `tomllib` (stdlib, read-only). Cannot write. Disqualified.
- `tomlkit`. Preserves comments, whitespace, and ordering across
  round-trips. Used by poetry, pdm, and astral-sh tooling. MIT
  license. Pure Python, small install footprint. Already uv's own
  writer for `uv add`-style mutations in recent versions (confirmed
  via `uv` source).

`tomlkit` is the idiomatic choice for editing a user's
`pyproject.toml` programmatically. No stdlib alternative exists that
preserves style. Adding it as a runtime dependency is a one-line
change.

### idempotency markers

`tomlkit` lets us check for the presence of our block by structured
inspection, not string match:

- `doc["tool"]["uv"]["index"]` as a list-of-table; iterate and look
  for `name == "pytorch-cu130"`.
- `doc["tool"]["uv"]["sources"]["torch"]` as list-of-inline-tables;
  look for an entry with `index == "pytorch-cu130"`.

Re-running `install` then re-entering the edit path finds both entries
and returns without writes. The uninstall pass uses the same lookup
to remove only the entries with the canonical name, preserving any
user-added entries in the same tables.

### safety considerations

- **Confirmation prompt** before writing. Consumer's
  `pyproject.toml` is *their* file, not rag's. Use rich's
  `Confirm.ask` (already a dependency). `--yes` bypasses for CI.
  `--no-torch-config` opts out entirely.
- **Backup on write**. `atomic_write` (rag already re-exports core's
  helper) writes to a `.tmp` sibling + `os.replace`, so a failed
  write never corrupts the user file. No separate `.bak` needed.
- **Diff preview** in dry-run mode (`--dry-run`): print the TOML
  block that would be added, then exit without writing.
- **Conflict detection**. If the consumer has an existing
  `pytorch-cu130` index pointing at a different URL, or a
  `torch` source pointing at a different index, do not clobber:
  warn and skip.
- **Read-write-read round-trip** before committing: reparse the
  post-edit document to verify syntactic validity before
  `os.replace`.

## confirmation and flag surface

The issue asks for:

- `--yes` / `-y` — skip the pyproject confirmation prompt.
- `--no-torch-config` — skip the torch-config step entirely.

No existing rag `install` flag conflicts with either. Core's
`cmd_install` does not have these (install there is non-interactive
today), so we do not breach the 100%-alignment rule in the prior ADR
(`[[2026-04-12-vaultspec-rag-install-adr]]`) — we add flags rag
requires that have no core analogue, which the prior ADR already
allows for rag-specific scope (precedent: `--remove-data`).

A third flag discussed but rejected: `--torch-index URL`. Lets
advanced users point at cu121, cu124, or a private mirror. Marked
out-of-scope for the first pass — add later if users request it.
For now, `pytorch-cu130` is hardcoded and matches rag's own canonical
shape; users who need a different index can edit the block manually
and our idempotency check will leave it alone.

## uv sync orchestration

Two options after patching:

- **Shell out.** `subprocess.run(["uv", "sync",
  "--reinstall-package", "torch"], cwd=target)`. Pros: one-shot, user
  ends in a ready state. Cons: requires `uv` on PATH, blocks on
  network, surfaces uv's error messages alongside ours.
- **Print the command.** Write the block, then print
  `uv sync --reinstall-package torch` as the next step.
  Pros: zero process boundary, no dependency on uv's PATH, no
  implicit network. Cons: two-step UX.

**Recommendation: print by default, shell out behind `--sync` (opt-in).**
rag's other workspace mutations (builtin seeding) do not shell out;
consistency matters. The print path also keeps `install` fast and
predictable in CI and containerised workflows. Users who want the
one-liner pass `--sync`.

## uninstall symmetry

`uninstall` must reverse only the exact entries `install` wrote:

- Remove the `pytorch-cu130` entry from `[[tool.uv.index]]` iff the
  URL matches our canonical URL.
- Remove the `torch` entry in `[tool.uv.sources]` iff it has the
  `pytorch-cu130` index reference *and* nothing else distinctive
  (our marker, our shape).
- Leave the rest of the tables intact. If the `torch` source list
  becomes empty, drop the key. If the index list becomes empty,
  drop the table.
- If the user has customised either entry (different URL, different
  marker, extra keys), emit a warning and skip — the user now owns
  those lines.

Same match predicate as the install idempotency check, inverted.

## error-message taxonomy after the fix

Final `_handle_gpu_error` behaviour:

| Caught exception                                 | Detected state                                | Message                                                                                                   |
| :----------------------------------------------- | :-------------------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| `ImportError`                                    | torch not installed                           | `uv add vaultspec-rag && uv run vaultspec-rag install` (unchanged intent)                                 |
| `RuntimeError` / any, with `torch.version.cuda is None` | CPU-only torch wheel                          | "PyTorch was installed without CUDA support (CPU-only wheel). Your GPU is fine." + `vaultspec-rag install` |
| `RuntimeError` / any, with `torch.version.cuda` set and `torch.cuda.is_available()` False | CUDA wheel but no GPU / driver issue          | existing "No CUDA GPU detected" + driver/hardware hint                                                    |
| other                                            | unknown                                       | fall-through (existing)                                                                                   |

The message text, once locked down in the ADR, must also include the
raw manual snippet so users who want to patch their `pyproject.toml`
by hand (e.g. in an air-gapped environment) are unblocked without
running `install`.

Call-sites for the new helper (from grep):

- `src/vaultspec_rag/cli.py:527`
- `src/vaultspec_rag/cli.py:937`
- `src/vaultspec_rag/cli.py:992`
- `src/vaultspec_rag/cli.py:1652` (sibling check in `service_warmup`,
  currently prints a bare "No CUDA GPU detected" — must be replaced
  with a call into `_handle_gpu_error` or equivalent)
- `src/vaultspec_rag/cli.py:1885`
- `src/vaultspec_rag/cli.py:1990`

The central helper is already in place; the taxonomy refactor happens
inside it, so all call-sites inherit the new messages automatically
(except line 1652, which must be migrated).

## related prior work

- `[[2026-04-12-vaultspec-rag-install-adr]]` — install command
  architecture; this feature extends it.
- `[[2026-04-06-ecosystem-integration-adr]]` — companion delegation
  model. rag **does not** modify shared files core owns. The
  consumer's `pyproject.toml` is **user-owned**, not core-owned —
  editing it is within rag's scope, but only with an explicit
  user consent gate.
- pyproject.toml:96-104 — canonical cu130 block rag already uses
  internally. This is the reference shape we mirror into the consumer.

## key decisions to lock down in adr

- Hard-coded cu130 or configurable? (proposed: cu130 only for v1)
- Default to `--sync` or not? (proposed: no, opt-in)
- Module layout: extend `commands.py` or add a new `torch_config.py`?
  (proposed: new `torch_config.py` module, imported from
  `commands.py`; keeps `commands.py` focused on orchestration)
- Where does the marker string
  `sys_platform == 'linux' or sys_platform == 'win32'` live as a
  constant? (proposed: module-level in `torch_config.py`)
- Do we also update the README's Install section? (yes — acceptance
  criterion in the issue)
- Uninstall: should it *always* attempt torch-config removal, or
  require `--torch-config` / mirror `--yes` semantics? (proposed:
  always attempt, silent skip when no matching block exists)

## out of scope

- A `[gpu]` optional extra (cannot work; cu wheels not on PyPI).
- Pip / poetry / pdm compatibility shims (rag is uv-first per
  existing conventions).
- A `--torch-index URL` override flag (tracked as follow-up).
- macOS torch-config (the marker leaves macOS alone; macOS users
  get PyPI-torch as today, which is correct on MPS hardware).
