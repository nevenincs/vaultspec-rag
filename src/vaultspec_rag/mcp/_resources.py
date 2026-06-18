"""MCP resources and prompts - pure protocol adapter.

The ``vault://`` resource delegates to the running daemon's ``/vault-document``
route through the shared :mod:`vaultspec_rag.serviceclient` client, sharing the
port resolution, worker-thread offload, and one service-down error with the
search/admin tools. The ``analyze_feature`` prompt is a pure string template.
"""

from __future__ import annotations

from functools import partial

from ..serviceclient import _try_http_vault_document
from ._mcp import mcp
from ._tools import (
    _delegate,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
    _require_port,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
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
        RuntimeError: If the service is not running or the REST call
            fails.
    """
    port = _require_port()
    res = await _delegate(partial(_try_http_vault_document, doc_id, "", port))
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
