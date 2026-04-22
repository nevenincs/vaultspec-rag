---
tags:
  - "#exec"
  - "#install-cuda"
date: 2026-04-22
related:
  - "[[2026-04-22-install-cuda-plan]]"
  - "[[2026-04-22-install-cuda-adr]]"
  - "[[2026-04-22-install-cuda-research]]"
---

# install-cuda phase-1 summary

## scope

Implements `[[2026-04-22-install-cuda-adr]]` per `[[2026-04-22-install-cuda-plan]]`.
Resolves [github issue #81](https://github.com/wgergely/vaultspec-rag/issues/81).

## artefacts landed

| file                                                                       | kind     | lines                       | purpose                                                   |
| :------------------------------------------------------------------------- | :------- | :-------------------------- | :-------------------------------------------------------- |
| `pyproject.toml`                                                           | modified | +1 dep                      | `tomlkit>=0.13` runtime dep                               |
| `uv.lock`                                                                  | modified | autogen                     | locks tomlkit 0.14.0                                      |
| `src/vaultspec_rag/torch_config.py`                                        | NEW      | ~300                        | pure logic: detect/apply/remove cu130 block + diagnose_torch |
| `src/vaultspec_rag/commands.py`                                            | modified | ~+160                       | install/uninstall orchestration calls torch_config; new params and report fields |
| `src/vaultspec_rag/cli.py`                                                 | modified | ~+80                        | `--torch-config/--no-torch-config`, `--yes`, `--sync`; 3-state `_handle_gpu_error`; migrated `service_warmup` check |
| `src/vaultspec_rag/tests/test_torch_config.py`                             | NEW      | 23 tests                    | unit coverage of torch_config module                      |
| `src/vaultspec_rag/tests/test_install_torch_config.py`                     | NEW      | 14 tests                    | install/uninstall torch-config branch coverage            |
| `README.md`                                                                | modified | +~30                        | install section rewrite, manual cu130 snippet, 3-state troubleshooting |

Total: 37 new tests, all passing. 382 unit tests pass overall. ty clean. ruff clean.

## key decisions verified in code

- cu130 is canonical; `CU130_INDEX_NAME`, `CU130_INDEX_URL`, `CU130_MARKER` are `Final` module constants shared between apply and remove — symmetric by construction.
- `apply_patch`/`remove_patch` use `tomlkit` round-trip; user comments and key ordering preserved (verified by `test_apply_preserves_user_comments`).
- Non-TTY detection lives at the CLI edge (`cli.py` reads `sys.stdin.isatty()`); `commands.py` takes an optional `ConfirmFn` callable and treats `None` as "no interactive channel, refuse to guess".
- `uninstall_run` now calls `_run_torch_config_uninstall` even when `.vaultspec/` is absent, so a workspace where rag's enrollment was manually deleted still gets its torch-config block removed.
- `_handle_gpu_error` lazily imports torch inside the helper so the `ImportError` fast path stays cheap.
- CPU_ONLY message renders the manual snippet with Rich markup disabled (`console.print(manual_snippet(), markup=False)`), otherwise `[[tool.uv.index]]` is swallowed as markup syntax. Bug caught during smoke testing, not shipped.
- `sync_after=True` shells out to `uv sync --reinstall-package torch` via `subprocess.run(..., check=False, capture_output=True)` — non-zero exit becomes a warning, never a hard failure.

## test results

```
uv run pytest src/vaultspec_rag/tests/ -m "not integration and not performance and not quality and not robustness and not subprocess_gpu" \
  --ignore=src/vaultspec_rag/tests/integration --ignore=src/vaultspec_rag/tests/benchmarks

382 passed, 44 deselected, 5 warnings in 37.45s
```

```
uv run ruff check src/vaultspec_rag/     # All checks passed!
uv run ruff format --check <changed>     # clean
uv run ty check src/vaultspec_rag/torch_config.py src/vaultspec_rag/commands.py  # All checks passed!
```

Integration tests under `src/vaultspec_rag/tests/integration/` require `HF_TOKEN` (gated SPLADE model). They were not executed in this session; the torch-config path does not require GPU or network, and its coverage is provided by the 37 new non-GPU tests.

## follow-ups

None blocking. Tracked optional follow-ups (per ADR):

- `--torch-index URL` override for cu124 / cu121 / private mirrors.
- macOS MPS story, should rag ever target that platform.
- Move the existing `integration/test_install.py` tests off the
  `integration` marker (they don't need HF either).

## acceptance-criteria mapping (issue #81)

| criterion                                                                                       | status                                                                       |
| :---------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------- |
| `install` in a fresh project adds cu130 index + torch source, prompts for confirmation         | done (`--yes` bypasses; non-TTY requires explicit flag)                      |
| Running `install` twice is a no-op for the torch-config block                                  | done (`test_install_idempotent_on_second_run`)                               |
| `uninstall` removes only the exact entries install added                                       | done (canonical-shape match; CUSTOMISED left intact — `test_uninstall_on_customised_block_skips_with_conflict`) |
| CPU-torch error names `uv run vaultspec-rag install` as the fix                                | done (`TorchDiagnosis.CPU_ONLY` branch in `_handle_gpu_error`)               |
| CUDA-torch-but-no-GPU error stays as "No CUDA GPU detected"                                    | done (`TorchDiagnosis.NO_GPU` branch)                                        |
| README install section updated                                                                 | done (lead with `uv add vaultspec-rag && uv run vaultspec-rag install`; manual snippet + troubleshooting retained) |
