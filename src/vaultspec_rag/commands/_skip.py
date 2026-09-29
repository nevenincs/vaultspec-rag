"""Validation for the ``--skip`` component set shared by install and uninstall.

Rag interprets ``core`` and ``mcp`` itself; every other ``--skip`` token
travels unchanged into core's own provider sync (``sync_provider("all", ...,
skip={*skip, "mcp"})``), so the forwarded half of rag's vocabulary is exactly
what that sync accepts - core's provider names (``VALID_PROVIDERS``, minus the
``"all"`` selector) plus its ``hooks`` and ``precommit`` sync-pass names.
Reading the provider half straight from ``VALID_PROVIDERS`` rather than
copying it means a provider core adds is accepted by rag's own ``--skip``
with no matching edit here. An unrecognised token used to reach that sync
inside a broad ``except Exception`` and surface as a warning after files were
already written; validating the whole set up front, before either command
does anything, turns a typo into a refusal instead.
"""

from __future__ import annotations

from vaultspec_core.core.provider_registry import VALID_PROVIDERS

#: Tokens rag's own orchestration reads directly and never forwards.
_RAG_CONSUMED_TOKENS = frozenset({"core", "mcp"})

#: Sync-pass names core's ``sync_provider("all", ...)`` recognises alongside
#: its provider names, forwarded through unchanged. Documented on
#: ``vaultspec-core install --skip``'s own help text.
_CORE_SYNC_PASS_TOKENS = frozenset({"hooks", "precommit"})


def rag_skip_vocabulary() -> frozenset[str]:
    """Return every token vaultspec-rag's ``--skip`` accepts."""
    return _RAG_CONSUMED_TOKENS | (VALID_PROVIDERS - {"all"}) | _CORE_SYNC_PASS_TOKENS


def validate_rag_skip(skip: set[str]) -> None:
    """Reject an unknown ``--skip`` token before install or uninstall runs.

    Args:
        skip: The requested skip tokens, exactly as passed by the caller.

    Raises:
        ValueError: If *skip* names a token outside :func:`rag_skip_vocabulary`,
            in the same "Invalid --skip value(s): ...; Valid: ..." shape core
            raises for its own invalid ``--skip``.
    """
    valid = rag_skip_vocabulary()
    bad = skip - valid
    if not bad:
        return
    msg = (
        f"Invalid --skip value(s): {', '.join(sorted(bad))}. "
        f"Valid: {', '.join(sorted(valid))}"
    )
    raise ValueError(msg)
