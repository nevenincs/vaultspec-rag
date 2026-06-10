"""MCP resources and prompts — pure protocol adapter.

The ``vault://`` resource and ``analyze_feature`` prompt delegate to the
REST daemon via ``_call_daemon``.  No server internals are imported.
"""

from __future__ import annotations

from ._mcp import mcp
from ._tools import (
    _call_daemon,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module intentional import
)


@mcp.resource("vault://{doc_id}")
async def get_vault_document(doc_id: str) -> str:
    """Retrieve the full content of a vault document by its stem ID.

    Delegates to the daemon's ``/vault-document`` REST endpoint.

    Args:
        doc_id: Relative path without extension (e.g.,
            ``"adr/overview"``).

    Returns:
        The full text content of the vault document.

    Raises:
        FileNotFoundError: If no document matches the given ID.
        RuntimeError: If the daemon is not running or the REST call
            fails.
    """
    res = _call_daemon("/vault-document", {"doc_id": doc_id})
    if "content" in res:
        return str(res["content"])
    if res.get("error") == "not_found":
        raise FileNotFoundError(f"Document '{doc_id}' not found")
    # Structured error from daemon (registry_full, local_store_locked, etc.)
    raise RuntimeError(str(res.get("message", f"Failed to fetch document '{doc_id}'")))


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
    return (
        f"Please analyze the implementation and documentation "
        f"for the '{feature_name}' feature.\n\n"
        f"1. Use `search_vault` with 'feature:{feature_name}' "
        f"to find related ADRs and plans.\n"
        f"2. Use `search_codebase` to find the actual "
        f"implementation logic.\n"
        f"3. Summarize how the implementation aligns with "
        f"the original design specs."
    )
