"""Maintenance guard for the shipped built-in rule (#145).

The bundled rule (`.vaultspec/rules/rules/vaultspec-rag.builtin.md`) is the
standing agent operating manual every consumer inherits. This test fails if the
rule's load-bearing directives go missing, so a behaviour or wording change
cannot silently leave the rule without its core guidance: use semantic search,
run the server-bound backend, and do not manually reindex.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# repo-root/src/vaultspec_rag/tests/<this file> -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RULE_PATH = _REPO_ROOT / ".vaultspec" / "rules" / "rules" / "vaultspec-rag.builtin.md"

# Load-bearing directives the rule MUST carry. Keep this list in lockstep with
# the rule's core mandates: semantic search is the primary use, server mode is the
# default backend (local is the explicit opt-out), and the watcher makes manual
# reindex redundant.
_REQUIRED_DIRECTIVE_TOKENS = [
    "semantic search",
    "default backend",
    "--local-only",
    "DO NOT manually reindex",
]


def test_builtin_rule_source_exists() -> None:
    assert _RULE_PATH.is_file(), f"built-in rule missing at {_RULE_PATH}"


@pytest.mark.parametrize("token", _REQUIRED_DIRECTIVE_TOKENS)
def test_builtin_rule_carries_core_directive(token: str) -> None:
    text = _RULE_PATH.read_text(encoding="utf-8")
    assert token in text, (
        f"built-in rule is missing the required directive token {token!r}; "
        "the rule's core guidance changed without updating it (see #145)"
    )
