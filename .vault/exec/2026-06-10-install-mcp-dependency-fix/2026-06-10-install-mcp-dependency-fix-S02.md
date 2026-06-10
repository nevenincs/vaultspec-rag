---
tags:
  - '#exec'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
step_id: 'S02'
related:
  - "[[2026-06-10-install-mcp-dependency-fix-plan]]"
---

# Guard the unconditional mcp import in main with try/except re-raising a chained RuntimeError carrying an actionable uv and pywin32 remediation message, messaging only with no DLL handling

## Scope

- `src/vaultspec_rag/server/_main.py`

## Description

- Wrap the unconditional `from ..mcp import mcp` in the daemon entry point's
  `main()` in a `try`/`except ImportError`.
- Re-raise a chained `RuntimeError` (`from exc`) carrying an actionable message:
  it names the likely `uv`/`pywin32` post-install cause, cites upstream
  `modelcontextprotocol/python-sdk#2233`, and gives the `pywin32_postinstall`
  remediation plus the reinstall path when `mcp` is missing entirely.
- Keep the change messaging-only: no DLL handling, no `os.add_dll_directory`.

## Outcome

Implemented and shipped out-of-band in commit `4e4af36`. Verified against the
working tree: the guarded import is present in `main()`, the `RuntimeError` is
chained from the original `ImportError`, and the message matches the ADR intent.
The change also corrected a previously misplaced docstring that had sat after
the bare import statement. `ruff check` passes on the file.

## Notes

The delivered message references the upstream issue and the manual
`python -m pywin32_postinstall -install` remediation, consistent with the ADR's
decision to message rather than manage `pywin32`'s DLLs.
