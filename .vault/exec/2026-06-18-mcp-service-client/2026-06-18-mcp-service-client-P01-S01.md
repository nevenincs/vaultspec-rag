---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S01'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Convert the top-level package init to lazy attribute loading so importing any submodule no longer eager-loads the heavy facade

## Scope

- `src/vaultspec_rag/__init__.py`

## Description

- Replace the eager top-level imports of `api`, `embeddings`, `indexer`, `search`, and `store` in the package init with `PEP 562` lazy attribute loading.
- Keep `__version__` resolved eagerly at import time via `importlib.metadata.version`.
- Add a `_LAZY_EXPORTS` map from each public name to its owning submodule and a `__getattr__` that imports the owner on first access, caches the resolved value in `globals()`, and raises `AttributeError` for unknown names.
- Add a `TYPE_CHECKING` block that eagerly imports every public name so static type checkers and IDEs still see the full surface without the runtime cost.
- Preserve `__all__` unchanged and add `__dir__` so the lazy names surface in introspection.

## Outcome

- Importing a submodule (for example the new service-client package or a `search` leaf module) no longer pulls `api`, `store`, `search`, `embeddings`, or `indexer` into `sys.modules`; before this change importing `vaultspec_rag.search._validation` dragged all four heavy modules in because the package init eager-imported `api` at module top.
- All public names still resolve on access: `vaultspec_rag.VaultStore`, `vaultspec_rag.search_vault`, and the rest resolve lazily through `__getattr__`, and `__version__` resolves eagerly.
- The whole unit suite for the touched surface stays green; type checking and linting are clean on the file.

## Notes

This lazy init is the load-bearing prerequisite for the import-isolation guarantee the rest of the phase depends on: without it, importing any service-client leaf module would re-trigger the heavy facade through the package init.
