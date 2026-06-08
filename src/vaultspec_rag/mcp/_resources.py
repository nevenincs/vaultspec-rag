"""MCP resources and prompts.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. Importing this module runs the
``@mcp.resource()`` / ``@mcp.prompt()`` decorators. The HTTP-mode flag
is read through the package alias so a test rebind of ``_http_mode`` is
observed.
"""

from __future__ import annotations

from anyio.to_thread import run_sync as _run_in_thread

import vaultspec_rag.server as _m

from ..server._utils import _default_root
from ._mcp import mcp


@mcp.resource("vault://{doc_id}")
async def get_vault_document(doc_id: str) -> str:
    """Retrieve the full content of a vault document by its stem ID.

    Only available in stdio mode (single-project).  In HTTP mode,
    use the ``search_vault`` tool with an explicit ``project_root``.

    Args:
        doc_id: Relative path without extension (e.g.,
            ``"adr/overview"``).

    Returns:
        The full text content of the vault document.

    Raises:
        FileNotFoundError: If no document matches the given ID.
        ValueError: If called in HTTP service mode.
        RuntimeError: If RAG components fail to initialize.
    """
    if _m._http_mode:
        msg = "Resource vault:// is only available in stdio mode (single-project)."
        raise ValueError(msg)
    root = _default_root()

    def _run() -> str:
        with _m._registry.lease(root) as slot:
            doc = slot.store.get_by_id(doc_id)
            if not doc:
                raise FileNotFoundError(f"Document '{doc_id}' not found")
            return doc.get("content", "")

    return await _run_in_thread(_run)


@mcp.prompt()
def analyze_feature(feature_name: str) -> str:
    """Create a prompt to analyze a feature across docs and code.

    Args:
        feature_name: The feature tag to search for (e.g.,
            ``"pipeline"``, ``"scheduler"``).

    Returns:
        A multi-step instruction string guiding the LLM to
        search vault ADRs, find codebase implementation, and
        summarize alignment.
    """
    root_note = (
        "\n\nNote: In HTTP service mode, you must include "
        "`project_root` in every tool call."
        if _m._http_mode
        else ""
    )
    return (
        f"Please analyze the implementation and documentation "
        f"for the '{feature_name}' feature.\n\n"
        f"1. Use `search_vault` with 'feature:{feature_name}' "
        f"to find related ADRs and plans.\n"
        f"2. Use `search_codebase` to find the actual "
        f"implementation logic.\n"
        f"3. Summarize how the implementation aligns with "
        f"the original design specs."
        f"{root_note}"
    )
