---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'S13'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# CLI help cleanup — operator-facing help, no leaked developer sections

## Scope

- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/cli/_search.py`
- `src/vaultspec_rag/cli/_status.py`
- `src/vaultspec_rag/cli/_app.py`
- `src/vaultspec_rag/cli/_service_lifecycle.py`
- `src/vaultspec_rag/cli/_mcp_admin.py`
- `src/vaultspec_rag/tests/test_cli.py`

## Description

Moved all user-facing help into explicit `help=` arguments on `@app.command()` and
`@app.callback()` decorators, and stripped developer sections (`Args:`, `Raises:`,
internal type names `CLIState`, parameter name `ctx`) from every affected function
body docstring.

**Commands cleaned:**

- `handle_index` (`_index.py`): `@app.command("index", help="Build or update the vault and/or codebase search index…")`. Body docstring reduced to one sentence.
- `handle_clean` (`_index.py`): `@app.command("clean", help="Drop selected index collections without re-indexing…")`. Body docstring reduced to one sentence.
- `handle_search` (`_search.py`): `@app.command("search", help="Search vault documents or source code using hybrid dense+sparse embeddings…")`. Body docstring reduced to one
  sentence.
- `handle_status` (`_status.py`): `@app.command("status", help="Show index document counts, storage path, and GPU device info…")`. Body docstring reduced to one sentence.
- `main` (`_app.py`): Body docstring stripped of `Args:`/`Raises:` sections, reduced to
  one sentence.
- `version_callback` (`_app.py`): Body docstring stripped of `Args:`/`Raises:` sections,
  reduced to one sentence.
- `service_start` (`_service_lifecycle.py`): `@server_app.command("start", help="Start the background RAG service as a detached process…")`. Body docstring reduced to one
  sentence.
- `service_warmup` (`_service_lifecycle.py`): `@server_app.command("warmup", help="Pre- download GPU model files to the HuggingFace cache…")`. Body docstring reduced to one
  sentence.
- `mcp_start` (`_mcp_admin.py`): `@mcp_app.command("start", help="Start the MCP server in the foreground…")`. Body docstring reduced to one sentence.

**rich_help_panel groupings added to `handle_search`:**

All nine code-specific filter options (`--language`, `--path`, `--include-path`,
`--exclude-path`, `--dedup-locales`, `--prefer`, `--node-type`, `--function-name`,
`--class-name`) now carry `rich_help_panel="Code filters"`. The four vault-specific
filter options (`--doc-type`, `--feature`, `--date`, `--tag`) carry
`rich_help_panel="Vault filters"`. This groups the long option list into two labelled
panels in `--help` output.

**Cross-references to `docs/indexing.md` added:**

The `help=` string on `index`, `clean`, `status`, and `server warmup` each end with
`"See the indexing architecture guide: docs/indexing.md"`.

**New unit test class `TestHelpCleanup` in `test_cli.py`:**

12 `@pytest.mark.unit` tests using Typer `CliRunner`:

- `test_index_help_clean` / `test_index_help_cross_ref`
- `test_clean_help_clean` / `test_clean_help_cross_ref`
- `test_search_help_clean` / `test_search_help_panels`
- `test_status_help_clean` / `test_status_help_cross_ref`
- `test_server_start_help_clean`
- `test_server_warmup_help_clean` / `test_server_warmup_help_cross_ref`
- `test_mcp_start_help_clean`

Each clean-test asserts none of `("Args:", "Raises:", "CLIState", " ctx ")` appear in
the `--help` output. Each cross-ref test asserts `"docs/indexing.md"` is present. Each
panel test asserts `"Code filters"` and `"Vault filters"` are present.

## Outcome

- `ruff check` clean on all modified files.
- `ty check` clean on all modified files.
- `TestHelpCleanup`: 12/12 pass.
- `test_cli.py` combined run: 157 previously-passing tests still pass; 6 pre-existing
  failures in `TestServiceProjectsCli` and `TestJsonOutputMode`/`TestJsonStdoutPurityAcrossCommands`
  are unchanged and unrelated to this step.
