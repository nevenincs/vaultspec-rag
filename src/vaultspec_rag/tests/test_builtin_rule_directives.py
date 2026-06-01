"""Maintenance guard for the shipped built-in rule (#145).

The bundled rule (`.vaultspec/rules/rules/vaultspec-rag.builtin.md`) is the
standing agent guidance every consumer inherits. When service behaviour
changes (e.g. auto-reindex), its DO/DO NOT directives must be updated in the
same change. This test fails if the load-bearing auto-reindex / opt-out
directive tokens go missing, so a behaviour change cannot silently leave the
rule stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# repo-root/src/vaultspec_rag/tests/<this file> -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RULE_PATH = _REPO_ROOT / ".vaultspec" / "rules" / "rules" / "vaultspec-rag.builtin.md"

# Tokens the rule MUST carry once the auto-reindex feature ships (#143/#144/#145).
_REQUIRED_DIRECTIVE_TOKENS = [
    "auto-reindex",
    "DO NOT manually reindex",
    "--no-watch",
    "VAULTSPEC_RAG_WATCH_ENABLED",
    "watcher status",
]


def test_builtin_rule_source_exists() -> None:
    assert _RULE_PATH.is_file(), f"built-in rule missing at {_RULE_PATH}"


@pytest.mark.parametrize("token", _REQUIRED_DIRECTIVE_TOKENS)
def test_builtin_rule_carries_auto_reindex_directive(token: str) -> None:
    text = _RULE_PATH.read_text(encoding="utf-8")
    assert token in text, (
        f"built-in rule is missing the required directive token {token!r}; "
        "service behaviour changed without updating the rule (see #145)"
    )
