---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
related:
  - '[[2026-03-06-codebase-indexer-tech-stack-research]]'
  - '[[2026-03-07-api-verification-research]]'
---

# ADR: Manual tree-sitter node walking over Query API for metadata extraction

## Status

Accepted

## Context

The `ASTChunker` in `indexer.py` needs to extract metadata (function names,
class names, node types) from tree-sitter parse trees. Two approaches exist:
the tree-sitter Query API (S-expression pattern matching) and manual node
walking via `child_by_field_name()`.

## Decision

Use manual node walking (`node.child_by_field_name("name")`) for metadata
extraction rather than the tree-sitter Query API.

## Rationale

1. **Simpler for our use case.** We extract a single field (`name`) from
   known node types (`function_definition`, `class_definition`,
   `decorated_definition`). This is a direct field access, not a pattern
   search.

1. **No query compilation overhead.** The Query API compiles S-expression
   patterns into an internal representation. For extracting one field from
   one node, this is unnecessary overhead.

1. **Cross-language consistency.** Each language has different decorator/
   annotation handling (verified via runtime testing):

   - Python: `decorated_definition` wraps the real definition -- must unwrap
     via `child_by_field_name("definition")` first
   - Java: annotations are inside `modifiers` child -- name is on the
     declaration directly
   - TypeScript: decorators are siblings -- name is on the declaration
   - Rust: `attribute_item` is a sibling -- name is on the item

   Manual walking handles these differences with simple `if` branches.
   Query patterns would need per-language S-expressions.

1. **Query API is better for bulk extraction.** If we later need to extract
   all functions, classes, and imports from an entire file in one pass, the
   Query API would be more efficient. For per-chunk single-field extraction,
   manual walking is simpler.

## Consequences

- `ASTChunker` metadata extraction uses `child_by_field_name()`.

- Python `decorated_definition` nodes must be unwrapped before name extraction:

  ```python
  if node.type == "decorated_definition":
      inner = node.child_by_field_name("definition")
      if inner:
          node = inner
  ```

- Query API remains available for future bulk extraction needs.
