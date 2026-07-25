---
tags:
  - '#exec'
  - '#install-cuda'
date: 2026-04-22
modified: '2026-06-30'
related:
  - '[[2026-04-22-install-cuda-phase1-summary-exec]]'
  - '[[2026-04-22-install-cuda-adr]]'
  - '[[2026-04-22-install-cuda-plan]]'
---

# install-cuda phase-1 code review

## scope

Reviews the diff landed under feature branch `feature/install-cuda`
for [issue #81](https://github.com/nevenincs/vaultspec-rag/issues/81).
Files under review:

- `src/vaultspec_rag/torch_config.py` (new)
- `src/vaultspec_rag/commands.py` (modified)
- `src/vaultspec_rag/cli.py` (modified)
- `src/vaultspec_rag/tests/test_torch_config.py` (new)
- `src/vaultspec_rag/tests/test_install_torch_config.py` (new)
- `pyproject.toml`, `uv.lock`, `README.md`

## adherence to prior ADRs

**`[[2026-04-12-vaultspec-rag-install-adr]]`** — install/uninstall
layering. Verdict: **adhered**.

- Orchestration stays in `commands.py`; Typer wrappers in `cli.py`
  remain thin (args → call → render → exit). New flags
  (`--torch-config`, `--yes`, `--sync`) are added as Typer options
  and passed through unchanged.
- New `torch_config.py` module mirrors core's per-resource file
  pattern (analogous to `gitignore.py`/`mcps.py`/`gitattributes.py`
  in core). No bloat into `commands.py`.
- No direct mutation of `.gitignore`, `.gitattributes`,
  `.mcp.json`, or provider dirs — only the user's `pyproject.toml`,
  which the ADR established as user-owned (consent-gated).

**`[[2026-04-06-ecosystem-integration-adr]]`** — companion
delegation contract. Verdict: **adhered**.

- rag never modifies files core owns; the consumer `pyproject.toml`
  sits outside core's writeable surface (user-owned).
- Consent gate present (confirmation prompt; `--yes` bypass;
  `--no-torch-config` opt-out; non-TTY refusal).

## test mandate (CLAUDE.md)

Verdict: **adhered**.

- No `from unittest...`, no `@patch`, no `MagicMock`, no
  `monkeypatch`, no `pytest.skip`. Grep-verified across new test
  files.
- All fixtures write real bytes to real `tmp_path` files and use
  real `tomlkit` / real `vaultspec_core` helpers.
- `diagnose_torch` is tested as a pure function over (cuda,
  available) args — no torch stubbing required.
- The 4-case parametrized test for `diagnose_torch` pins the
  taxonomy in both the code and the test suite simultaneously.

## three-state diagnosis completeness

Verdict: **complete**.

- `NO_TORCH` — `ImportError` branch; tested indirectly via the
  error-handler smoke run.
- `CPU_ONLY` — `torch.version.cuda is None`; tested in
  `test_diagnose_torch[None-False-cpu_only]` and the anomaly case
  `[None-True-cpu_only]`.
- `NO_GPU` — CUDA str present, `is_available()` False; tested.
- `WORKING` — passthrough; tested.
- Bare `cli.py:1652` check migrated to call `_handle_gpu_error`
  with a `RuntimeError("CUDA runtime unavailable")` — verified by
  grep that no other site still prints `"No CUDA GPU detected"`
  independently.

## uninstall symmetry

Verdict: **adhered**.

- Canonical-match predicate (`_index_match`, `_source_match`)
  used on both apply and remove paths — single source of truth.
- CUSTOMISED state leaves the user's entries intact and reports
  `action="skipped"` with conflicts. Explicit round-trip test
  (`test_uninstall_round_trip_preserves_project_table`) pins the
  contract.
- Uninstall now runs torch-config removal even when `.vaultspec/`
  is absent — discovered during testing; fix landed before commit.
  Prevents orphaned cu130 blocks when rag's `.vaultspec` state was
  manually removed.

## idempotency of `apply_patch`

Verdict: **correct**.

- Second call returns `action="already"` without touching the file
  (SHA-256 compare).
- Third call, and any subsequent, same outcome — the canonical-match
  predicate short-circuits before any mutation.

## safety of `pyproject.toml` mutation

Verdict: **safe**.

- Write goes through `vaultspec_core.core.helpers.atomic_write`
  (write-to-`.tmp` + `os.replace`). User file never half-written.
- Pre-write reparse (`tomlkit.parse(new_text)`) guarantees the
  TOML is valid before it crosses the FS boundary.
- CUSTOMISED state refuses to mutate; the user's divergent entries
  are surfaced in the report's `conflicts` list.
- `tomlkit` round-trip preserves comments and key ordering
  (`test_apply_preserves_user_comments`).

## flag surface review

| flag                | defaults | behaviour                                                          |
| :------------------ | :------- | :----------------------------------------------------------------- |
| `--torch-config`    | on       | Run the torch-config step.                                         |
| `--no-torch-config` | off      | Skip entirely (`action="disabled"`).                               |
| `--yes`/`-y`        | off      | Skip confirmation prompt. Required in non-TTY contexts.            |
| `--sync`            | off      | After a successful patch, run `uv sync --reinstall-package torch`. |

No conflicts with existing `install`/`uninstall` flags. Uninstall
gets a reserved `--yes`/`-y` for CLI symmetry (currently no prompt
to bypass; accepted for forward compatibility without warning).

## README review

Verdict: **aligned**.

- Lead install command updated to
  `uv add vaultspec-rag && uv run vaultspec-rag install`.
- Manual cu130 snippet retained for air-gapped users.
- Troubleshooting section names the three error states and points
  at the one-liner fix.
- Markdown passes mdformat / pymarkdownlnt (project pre-commit
  hooks run in the commit step).

## risks flagged at plan time — status

| risk                                   | outcome                                                                    |
| :------------------------------------- | :------------------------------------------------------------------------- |
| tomlkit drops non-ASCII chars          | n/a (round-trip test passes; tomlkit is ASCII-clean by design)             |
| `apply_patch` destroys user formatting | verified false (`test_apply_preserves_user_comments`)                      |
| `uv sync` fails                        | fenced: `check=False`, becomes warning                                     |
| Non-TTY UX surprise                    | CLI reads `sys.stdin.isatty()` → passes `confirm=None` → "skipped-non-tty" |
| `diagnose_torch` classification wrong  | pinned by parametrized tests                                               |

## sign-off

**Status: green.** The implementation meets the ADR in full. All
acceptance criteria from issue #81 map to passing tests or visible
behaviour. No blockers for PR submission. Follow-up work (torch-index
override, macOS MPS, test-marker cleanup) is documented in the
phase summary.
