---
tags:
  - '#plan'
  - '#vaultragignore'
date: '2026-04-04'
modified: '2026-07-27'
body_hash: 'sha256:9ac58034b354a216f86b33b7947b77ddf6665355ef28b54f66bfc1a7477656b2'
related:
  - '[[2026-04-04-vaultragignore-adr]]'
  - '[[2026-04-04-vaultragignore-research]]'
---

# `vaultragignore` implementation plan

Add `.vaultragignore` support to `CodebaseIndexer` — gitignore-syntax file at project
root that excludes git-tracked files from codebase indexing. Plus CLI `--dry-run` and
`--exclude` options.

See `2026-04-04-vaultragignore-adr` for design decisions (D1–D9).
See `2026-04-04-vaultragignore-research` for investigation.

### Phase `P01` - Ignore-file support in the codebase indexer

Recognise a root-level ignore file in gitignore syntax alongside the existing git ignore rules, combine the two specifications so either can exclude a path, and accept caller-supplied extra excludes.

- [x] `P01.S01` - Accept caller-supplied extra exclude patterns on the codebase indexer and build the git ignore specification through its own extracted helper so a second specification can sit beside it; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S02` - Build the root-level ignore-file specification in gitignore syntax and apply it in the scan walk so a path excluded by either specification is skipped, including git-tracked files; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S03` - Expose the resolved file set as a public scan entry point so a caller can preview what would be indexed without indexing it; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - CLI preview and exclude surface

Add the preview and extra-exclude flags, returning the preview before any service delegation, and warn when an exclude cannot be honoured on the delegated path.

- [x] `P02.S04` - Add the preview and repeatable exclude flags to the index command, returning the preview before the service-delegation branch so a preview never needs a running service; `src/vaultspec_rag/cli/_index.py`.
- [x] `P02.S05` - Warn when an exclude is supplied against a delegated run without a preview, and forward the extra excludes on the in-process path; `src/vaultspec_rag/cli/_index.py`.

### Phase `P03` - Tests

Cover the combined specification, the root-only scope, the preview scoping and ordering, and prove end-to-end that the ignore file removes a git-tracked file from the index.

- [x] `P03.S06` - Cover the two-specification combination, the root-only lookup, and the extra-exclude merge with unit tests over the scan; `src/vaultspec_rag/tests/`.
- [x] `P03.S07` - Prove end-to-end against a real index that a path named by the ignore file is absent afterwards, and cover the preview scoping and its ordering ahead of delegation; `src/vaultspec_rag/tests/integration/`.

## Phase 1: Core — `indexer.py`

### 1.1 Add `extra_excludes` to constructor

```python
def __init__(
    self,
    root_dir: pathlib.Path,
    model: EmbeddingModel,
    store: VaultStore,
    *,
    gpu_lock: threading.Lock | None = None,
    extra_excludes: list[str] | None = None,
) -> None:
    ...
    self._extra_excludes = extra_excludes or []
```

### 1.2 Extract `_build_gitignore_spec()`

Move the existing pattern-collection logic (lines 1112–1141) into a private method:

```python
def _build_gitignore_spec(self) -> pathspec.GitIgnoreSpec:
    import pathspec
    patterns: list[str] = [".venv/", ".git/", "node_modules/", "__pycache__/", ".qdrant/"]
    for gitignore in self.root_dir.rglob(".gitignore"):
        # ... existing subdirectory-prefixed pattern loading ...
    return pathspec.GitIgnoreSpec.from_lines(patterns)
```

### 1.3 Add `_build_vaultragignore_spec()`

```python
def _build_vaultragignore_spec(self) -> pathspec.GitIgnoreSpec | None:
    import pathspec
    patterns: list[str] = []
    ignore_file = self.root_dir / ".vaultragignore"
    if ignore_file.is_file():
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
            patterns.extend(
                line.strip() for line in lines
                if line.strip() and not line.strip().startswith("#")
            )
        except OSError:
            pass  # silently ignore unreadable file
    patterns.extend(self._extra_excludes)
    if not patterns:
        return None
    return pathspec.GitIgnoreSpec.from_lines(patterns)
```

### 1.4 Update `_scan_codebase()` walk loop

Replace inline pattern building with the two spec builders. Check both:

```python
def _scan_codebase(self) -> list[pathlib.Path]:
    git_spec = self._build_gitignore_spec()
    rag_spec = self._build_vaultragignore_spec()

    def is_excluded(rel_path: str) -> bool:
        if git_spec.match_file(rel_path):
            return True
        return rag_spec is not None and rag_spec.match_file(rel_path)

    # ... os.walk loop using is_excluded() for both dirs and files ...
```

### 1.5 Add public `scan_files()`

```python
def scan_files(self) -> list[pathlib.Path]:
    """Return the list of files that would be indexed.

    Does not require GPU or vector store — safe to call with
    ``model=None`` and ``store=None`` for dry-run usage.
    """
    return self._scan_codebase()
```

## Phase 2: CLI — `cli.py`

### 2.1 Add `--dry-run` and `--exclude` to `handle_index`

```python
@app.command("index")
def handle_index(
    ...,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List files that would be indexed without indexing."),
    ] = False,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Ad-hoc exclusion pattern (repeatable)."),
    ] = None,
) -> None:
```

### 2.2 Dry-run early return (before `--port` block — D9)

Must come before the `--port` MCP delegation block. Dry-run is always local.

```python
if dry_run:
    if index_type not in ("code", "all"):
        console.print("[yellow]--dry-run only applies to codebase indexing.[/]")
        return
    from .indexer import CodebaseIndexer
    c_indexer = CodebaseIndexer(
        target, None, None,  # type: ignore[arg-type]
        extra_excludes=exclude or [],
    )
    files = c_indexer.scan_files()
    console.print(f"[bold]{len(files)}[/] files would be indexed:")
    for f in sorted(files):
        console.print(f"  {f.relative_to(target)}")
    return
```

### 2.3 Warn on `--exclude` + `--port` without `--dry-run`

In the `--port` MCP delegation block, warn that `--exclude` is ignored:

```python
if port is not None:
    if exclude:
        console.print(
            "[yellow]--exclude is ignored when delegating to MCP server.[/]"
        )
    # ... existing MCP delegation ...
```

### 2.4 Pass `extra_excludes` in non-dry-run local path

```python
c_indexer = CodebaseIndexer(target, emb_model, store, extra_excludes=exclude or [])
```

## Phase 3: Tests

### 3.1 Unit tests (`test_indexer_unit.py`) — no GPU

New class `TestVaultragignore`:

| Test                                                      | Verifies                                                                                        |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `test_vaultragignore_excludes_matching_files`             | `.vaultragignore` with `*.log` excludes `.log` files from `scan_files()`                        |
| `test_missing_vaultragignore_no_error`                    | No `.vaultragignore` → no crash, baseline patterns still work                                   |
| `test_extra_excludes_applied`                             | `extra_excludes=["*.tmp"]` excludes `.tmp` files                                                |
| `test_vaultragignore_negation_cannot_override_gitignore`  | `.gitignore` has `secret.py`, `.vaultragignore` has `!secret.py` → `secret.py` still excluded   |
| `test_vaultragignore_internal_negation_works`             | `.vaultragignore` has `*.log` + `!important.log` → `foo.log` excluded, `important.log` included |
| `test_gitignore_still_respected_alongside_vaultragignore` | Both files present, both exclusion sets applied                                                 |
| `test_scan_files_public_method`                           | `scan_files()` returns same result as `_scan_codebase()`                                        |

Pattern: use `CodebaseIndexer.__new__()` + set `root_dir` and `_extra_excludes` manually
(same as existing gitignore unit tests at line 666+).

### 3.2 Integration test (`test_codebase_integration.py`) — real GPU

| Test                                           | Verifies                                                                                                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_vaultragignore_excludes_from_full_index` | Create temp project with `.vaultragignore` excluding a source file. `full_index()` produces zero chunks for that file. Remove ignore file, re-index, chunks appear. |

### 3.3 CLI test (`test_cli.py`)

| Test                       | Verifies                                                         |
| -------------------------- | ---------------------------------------------------------------- |
| `test_dry_run_lists_files` | `--dry-run --type code` prints file paths without loading GPU    |
| `test_exclude_pattern`     | `--exclude "*.test.py"` omits matching files from dry-run output |

## Parallelization

Phase 1 (indexer) must complete before Phase 2 (CLI) and Phase 3 (tests).
Phase 2 and Phase 3 unit tests can be done in parallel. Integration tests
depend on both Phase 1 and Phase 2.

## Verification

### Automated

- `just ci` (ruff + pytest) passes — all existing 220+ tests unaffected
- New unit tests verify each ADR decision: D1 (two-spec OR), D2 (root-only),
  D3 (silent missing), D4 (extra_excludes), D5 (scan_files), D7 (extracted builders)
- New integration test verifies end-to-end: `.vaultragignore` → `full_index()` → excluded
- New CLI tests verify D6 (dry-run codebase only), D9 (dry-run before port)

### Manual (post-implementation)

- Create a `.vaultragignore` in the test-project with `*.md` and run
  `vaultspec-rag index --dry-run --type code` — verify markdown files absent from output
- Run `vaultspec-rag index --dry-run --exclude "*.py"` — verify Python files absent
- Run `vaultspec-rag index --type code` with and without `.vaultragignore` — verify
  Qdrant chunk counts differ as expected

## Description

See the summary above.

## Steps

Retained-plan evidence: the detailed phase, wave, or step sections in this document are the step inventory; this canonical section preserves that inventory without duplicating it.
