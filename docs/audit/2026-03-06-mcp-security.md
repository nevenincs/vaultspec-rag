# Audit: MCP Server Security

Feature: mcp_server.py FastMCP tools, resources, prompts

## 2026-03-06 -- Review (Passes 9-19)

### Path Traversal Fix: VERIFIED (Task #17 -- RESOLVED)

Lines 194-196: `get_code_file()` now uses `resolve()` + `is_relative_to()` to prevent path traversal.

```python
full_path = (comp.root_dir / path).resolve()
if not full_path.is_relative_to(comp.root_dir.resolve()):
    return f"Error: path '{path}' is outside the workspace."
```

### SearchResult Serialization: VERIFIED (Task #16 -- RESOLVED)

`SearchResultItem` Pydantic model with `model_config = {"from_attributes": True}` mirrors the `SearchResult` dataclass. `model_validate(r, from_attributes=True)` correctly converts dataclass instances.

### GPU Pivot Compatibility: CLEAN

No GPU-specific code. Delegates to VaultSearcher/VaultStore which handle embeddings internally. No changes needed.

### `get_index_status()` Defensive Coding

Lines 162-178: Uses `hasattr` checks before calling `count()`, `count_code()`, `db_path`. This is overly defensive for internal code (these methods are guaranteed to exist on VaultStore). Not a bug but unnecessary.

## Pass 27 — Full mcp_server.py review

Full line-by-line audit. All confirmed correct:

- `RagComponents` lazy-loaded singleton via `get_comp()` -- clean pattern
- All 3 search tools (`search_vault`, `search_codebase`, `search_all`) delegate correctly to VaultSearcher
- `SearchResultItem.model_validate(r, from_attributes=True)` correctly converts SearchResult dataclass
- `get_code_file()` path traversal protection verified at lines 205-207
- `get_vault_document()` resource correctly retrieves by stem ID
- `analyze_feature()` prompt template is clean

No new issues found.
