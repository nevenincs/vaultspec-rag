---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-09
related: []
---

# MCP Server Documentation Audit (2026-03-09)

## Summary

Comprehensive audit of `src/vaultspec_rag/mcp_server.py` against documentation standards.
All violations are categorized and listed below.

______________________________________________________________________

## Critical Violations (Must Fix)

### RagComponents Dataclass (Lines 31–40)

| Line  | Member                          | Category            | Violation                                                                                                                                               |
| ----- | ------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 32–33 | RagComponents (class docstring) | Pydantic Attributes | Missing `Attributes:` section. Fields have no descriptions: `store`, `model`, `searcher`, `vault_indexer`, `code_indexer`, `root_dir` all undocumented. |
| 35    | `store`                         | Missing Description | Field `store: VaultStore` has no description in `Attributes:` or inline docstring.                                                                      |
| 36    | `model`                         | Missing Description | Field `model: EmbeddingModel` has no description in `Attributes:` or inline docstring.                                                                  |
| 37    | `searcher`                      | Missing Description | Field `searcher: VaultSearcher` has no description in `Attributes:` or inline docstring.                                                                |
| 38    | `vault_indexer`                 | Missing Description | Field `vault_indexer: VaultIndexer` has no description in `Attributes:` or inline docstring.                                                            |
| 39    | `code_indexer`                  | Missing Description | Field `code_indexer: CodebaseIndexer` has no description in `Attributes:` or inline docstring.                                                          |
| 40    | `root_dir`                      | Missing Description | Field `root_dir: Path` has no description in `Attributes:` or inline docstring.                                                                         |

______________________________________________________________________

### Module-Level Functions

| Line    | Function            | Category        | Violation                                                                                                                                                    |
| ------- | ------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 168–170 | `_clamp_top_k()`    | Missing Args    | Missing `Args:` section with parameter `top_k` documented.                                                                                                   |
| 168–170 | `_clamp_top_k()`    | Missing Returns | Missing `Returns:` section. Return type is `int`, should document what clamping achieves.                                                                    |
| 173–180 | `_validate_query()` | Missing Args    | Missing `Args:` section with parameter `query` documented.                                                                                                   |
| 173–180 | `_validate_query()` | Missing Returns | Missing `Returns:` section. Return type is `str`, should document truncation behavior.                                                                       |
| 173–180 | `_validate_query()` | Missing Raises  | `_MAX_QUERY_LEN` is hardcoded; docstring should mention no exception is raised for long queries (only logged). Consider documenting the constant explicitly. |

______________________________________________________________________

### MCP Tools (Async Functions)

| Line    | Function             | Category             | Violation                                                                                                                                                                                                        |
| ------- | -------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 184–211 | `search_vault()`     | Missing Returns      | Missing `Returns:` section. Function returns `SearchResponse` but docstring does not document the return type or fields.                                                                                         |
| 184–211 | `search_vault()`     | Incomplete Args      | `Args:` section present but missing `top_k` parameter documentation about the default value (5) or clamping behavior.                                                                                            |
| 184–211 | `search_vault()`     | Missing Raises       | No `Raises:` section documenting potential exceptions: `RuntimeError` (from `get_comp()`), exceptions from GPU thread execution.                                                                                 |
| 214–259 | `search_codebase()`  | Missing Returns      | Missing `Returns:` section. Function returns `SearchResponse` but docstring does not document the return type or fields.                                                                                         |
| 214–259 | `search_codebase()`  | Incomplete Args      | `Args:` section present but missing details about: default `top_k` (5), clamping behavior, or what happens if all filters are `None`.                                                                            |
| 214–259 | `search_codebase()`  | Missing Raises       | No `Raises:` section documenting potential exceptions: `RuntimeError` (from `get_comp()`), exceptions from GPU thread execution.                                                                                 |
| 262–284 | `search_all()`       | Missing Docstring    | Incomplete docstring. Present but missing: Args section (no `query` or `top_k` documented), Returns section, Raises section.                                                                                     |
| 262–284 | `search_all()`       | Missing Args         | No `Args:` section. Parameters `query` and `top_k` are undefined in documentation.                                                                                                                               |
| 262–284 | `search_all()`       | Missing Returns      | No `Returns:` section. Return type `SearchResponse` is not documented.                                                                                                                                           |
| 262–284 | `search_all()`       | Missing Raises       | No `Raises:` section. Potential exceptions from `get_comp()` and GPU thread not documented.                                                                                                                      |
| 287–318 | `get_index_status()` | Missing Docstring    | Minimal docstring. Missing: Args section (though function takes no args), Returns section, Raises section.                                                                                                       |
| 287–318 | `get_index_status()` | Missing Returns      | No `Returns:` section. Return type `IndexStatus` and its fields not documented.                                                                                                                                  |
| 287–318 | `get_index_status()` | Missing Raises       | No `Raises:` section. Potential exceptions: `ImportError` handling is silent but exceptions from `get_comp()` or GPU info retrieval not documented.                                                              |
| 321–345 | `get_code_file()`    | Missing Returns      | No `Returns:` section. Return type is `str` (file content) but not documented.                                                                                                                                   |
| 321–345 | `get_code_file()`    | Missing Raises       | No `Raises:` section. Documented exceptions in docstring but no formal `Raises:` section. The function can raise: `ValueError` (path outside workspace or file too large), `FileNotFoundError` (file not found). |
| 321–345 | `get_code_file()`    | Raises Inconsistency | Exceptions are raised in the code but not listed in a formal `Raises:` section. Docstring uses prose ("raise ValueError") but should use Google-style `Raises:` block.                                           |
| 348–379 | `reindex_vault()`    | Missing Returns      | No `Returns:` section. Return type `IndexResponse` not documented.                                                                                                                                               |
| 348–379 | `reindex_vault()`    | Missing Raises       | No `Raises:` section. Potential exceptions from indexing operations not documented.                                                                                                                              |
| 382–410 | `reindex_codebase()` | Missing Returns      | No `Returns:` section. Return type `IndexResponse` not documented.                                                                                                                                               |
| 382–410 | `reindex_codebase()` | Missing Raises       | No `Raises:` section. Potential exceptions from indexing operations not documented.                                                                                                                              |

______________________________________________________________________

### MCP Resources (Async Functions)

| Line    | Function               | Category          | Violation                                                                                                                     |
| ------- | ---------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 414–429 | `get_vault_document()` | Missing Docstring | Minimal docstring. Missing: full Args section details, Returns section, Raises section.                                       |
| 414–429 | `get_vault_document()` | Missing Returns   | No `Returns:` section. Return type is `str` (document content) but not documented.                                            |
| 414–429 | `get_vault_document()` | Missing Raises    | No `Raises:` section. Function can raise `FileNotFoundError` if document not found, but not formally documented in `Raises:`. |

______________________________________________________________________

### MCP Prompts (Sync Functions)

| Line    | Function            | Category        | Violation                                                                                                          |
| ------- | ------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------ |
| 433–445 | `analyze_feature()` | Missing Args    | Missing formal `Args:` section. Parameter `feature_name` has inline description but no Google-style `Args:` block. |
| 433–445 | `analyze_feature()` | Missing Returns | Missing `Returns:` section. Return type is `str` (prompt string) but not documented.                               |

______________________________________________________________________

### Main Entry Point

| Line    | Function | Category        | Violation                                                                                               |
| ------- | -------- | --------------- | ------------------------------------------------------------------------------------------------------- |
| 448–453 | `main()` | Missing Args    | No `Args:` section. Parameter `port` has no type or description (though signature shows `int \| None`). |
| 448–453 | `main()` | Missing Returns | No `Returns:` section. Function returns `None` but should be documented.                                |
| 448–453 | `main()` | Missing Raises  | No `Raises:` section. `mcp.run()` may raise exceptions not documented.                                  |

______________________________________________________________________

## Secondary Violations (Pydantic Models)

### SearchResultItem (Lines 120–139)

| Line    | Field                              | Category            | Violation                                                                                                                                                                                                                                        |
| ------- | ---------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 120–139 | SearchResultItem (class docstring) | Missing Attributes  | No `Attributes:` section in docstring. Fields have no inline descriptions: `id`, `path`, `title`, `score`, `snippet`, `source`, `doc_type`, `feature`, `date`, `language`, `line_start`, `line_end`, `node_type`, `function_name`, `class_name`. |
| 125     | `id`                               | Missing Description | Field description missing. Intent unclear: is this document ID, chunk ID, or search result ID?                                                                                                                                                   |
| 126     | `path`                             | Missing Description | Field description missing. Unclear if relative or absolute path.                                                                                                                                                                                 |
| 127     | `title`                            | Missing Description | Field description missing. Is this document title, chunk title, or function/class name?                                                                                                                                                          |
| 128     | `score`                            | Missing Description | Field description missing. Unclear if score is normalized (0-1), raw, or percentile.                                                                                                                                                             |
| 129     | `snippet`                          | Missing Description | Field description missing. Unclear if this is truncated excerpt or full content.                                                                                                                                                                 |
| 130     | `source`                           | Missing Description | Field description missing. Unclear: "vault" or "codebase" or enum?                                                                                                                                                                               |
| 131     | `doc_type`                         | Missing Description | Field description missing. Unclear valid values (adr, plan, research, audit, etc.).                                                                                                                                                              |
| 132     | `feature`                          | Missing Description | Field description missing. Unclear if this is feature name, category, or tag.                                                                                                                                                                    |
| 133     | `date`                             | Missing Description | Field description missing. Unclear format (ISO, Unix timestamp, readable string).                                                                                                                                                                |
| 134     | `language`                         | Missing Description | Field description missing. Only relevant to codebase results; unclear why present in unified model.                                                                                                                                              |
| 135     | `line_start`                       | Missing Description | Field description missing. Unclear if 0-indexed or 1-indexed; when applicable.                                                                                                                                                                   |
| 136     | `line_end`                         | Missing Description | Field description missing. Unclear if inclusive or exclusive; required for range interpretation.                                                                                                                                                 |
| 137     | `node_type`                        | Missing Description | Field description missing. Only for codebase; should document valid AST node types.                                                                                                                                                              |
| 138     | `function_name`                    | Missing Description | Field description missing. Only for codebase; when populated.                                                                                                                                                                                    |
| 139     | `class_name`                       | Missing Description | Field description missing. Only for codebase; when populated.                                                                                                                                                                                    |

______________________________________________________________________

### SearchResponse (Lines 142–144)

| Line    | Field          | Category  | Violation                                                                                                  |
| ------- | -------------- | --------- | ---------------------------------------------------------------------------------------------------------- |
| 142–144 | SearchResponse | Docstring | Missing class docstring entirely. No documentation of what this response represents or when it's returned. |
| 143     | `results`      | Redundant | Field has `description=` kwarg in Field() but class has no docstring explaining the overall structure.     |
| 144     | `summary`      | Redundant | Field has `description=` kwarg in Field() but class has no docstring explaining the overall structure.     |

______________________________________________________________________

### IndexStatus (Lines 147–153)

| Line    | Field       | Category   | Violation                                                                                              |
| ------- | ----------- | ---------- | ------------------------------------------------------------------------------------------------------ |
| 147–153 | IndexStatus | Docstring  | Missing class docstring entirely. Should document what this status represents and when it's retrieved. |
| 148–153 | All fields  | Documented | Fields have `description=` in Field() — compliant with requirements. No violations.                    |

______________________________________________________________________

### IndexResponse (Lines 156–162)

| Line    | Field         | Category   | Violation                                                                                               |
| ------- | ------------- | ---------- | ------------------------------------------------------------------------------------------------------- |
| 156–162 | IndexResponse | Docstring  | Missing class docstring entirely. Should document what this response represents and when it's returned. |
| 157–162 | All fields    | Documented | Fields have `description=` in Field() — compliant with requirements. No violations.                     |

______________________________________________________________________

## Type Hint Violations

### Missing Type Hints on Parameters

| Line   | Function      | Parameter | Violation                                               |
| ------ | ------------- | --------- | ------------------------------------------------------- |
| (none) | All functions | N/A       | All function parameters have type hints. No violations. |

### Type Hints on Return Values

| Line   | Function      | Return Type | Violation                                                     |
| ------ | ------------- | ----------- | ------------------------------------------------------------- |
| (none) | All functions | N/A         | All functions have explicit return type hints. No violations. |

______________________________________________________________________

## Terminology Consistency

### Terminology Review

| Term          | Usage                                                                                                           | Violations                                                                            |
| ------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| "vault"       | Consistent: used as lowercase adjective ("vault documentation", "vault document")                               | None                                                                                  |
| "codebase"    | Consistent: used as lowercase noun ("source codebase", "codebase chunks")                                       | None                                                                                  |
| "MCP tool"    | Consistent: used as phrase in comments and docstrings                                                           | None                                                                                  |
| "search_type" | NOT USED in docstrings or code comments; implicit in function names (search_vault, search_codebase, search_all) | Minor: could be more explicit in tool docstrings that these are distinct search types |

______________________________________________________________________

## Summary Statistics

| Category                                      | Count  |
| --------------------------------------------- | ------ |
| Missing Docstrings (in key classes/functions) | 5      |
| Missing Args Sections                         | 10     |
| Missing Returns Sections                      | 13     |
| Missing Raises Sections                       | 12     |
| Missing Pydantic Attributes Documentation     | 19     |
| Missing Class Docstrings (Pydantic models)    | 3      |
| Type Hint Violations                          | 0      |
| Terminology Inconsistencies                   | 0      |
| **TOTAL VIOLATIONS**                          | **62** |

______________________________________________________________________

## Recommendations (Priority Order)

1. **Immediate (P0):** Add `Attributes:` section to `RagComponents` dataclass documenting all 6 fields.
1. **Immediate (P0):** Add class docstrings to `SearchResponse`, `IndexStatus`, `IndexResponse` models.
1. **Immediate (P0):** Add field descriptions to all 15 fields in `SearchResultItem`.
1. **High (P1):** Add `Returns:` and `Raises:` sections to all 8 MCP tools (search_vault, search_codebase, search_all, get_index_status, get_code_file, reindex_vault, reindex_codebase, get_vault_document).
1. **High (P1):** Add formal `Args:` and `Returns:` sections to utility functions (\_clamp_top_k,\_validate_query, analyze_feature, main).
1. **Medium (P2):** Add `Raises:` section to all exception-raising functions, especially get_code_file (ValueError, FileNotFoundError).

______________________________________________________________________

## Compliant Components

- ✅ All function/method signatures have type hints.
- ✅ All return values have type annotations.
- ✅ Terminology ("vault", "codebase", "MCP tool") is consistent throughout.
- ✅ `IndexStatus` and `IndexResponse` models have complete Field descriptions.
