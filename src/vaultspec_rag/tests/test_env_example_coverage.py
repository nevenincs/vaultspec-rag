"""Guard test: ``.env.example`` documents every recognised env var.

``EnvVar`` is the single source of truth for the environment variables this
project reads, and ``.env.example`` is the only place an operator can discover
what each one does and what it defaults to. Those two drift silently: adding a
member to the enum is a one-line change that ships a knob nobody outside the
source can find. This test closes that gap by requiring an assignment line for
every member.

The check looks for an ASSIGNMENT line (``VAR=`` or ``# VAR=``), not a bare
mention, for two reasons. A prose mention carries no default, so it does not
actually document the variable. And a substring match would let
``VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES`` satisfy the requirement for
``VAULTSPEC_RAG_PREPROCESS``, which is exactly the pair most likely to be
confused.

Both directions of this guard were exercised: one variable's assignment line
was deleted from ``.env.example``, this test was run alone and observed to fail
on ``test_env_example_documents_every_env_var`` naming that variable as
missing, the line was restored, and the test was observed to pass. One
uninterrupted sequence, with nothing left mutated on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ..config import EnvVar

pytestmark = [pytest.mark.unit]

# repo-root/src/vaultspec_rag/tests/<this file> -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_EXAMPLE_PATH = _REPO_ROOT / ".env.example"

#: A documented variable is one with its own assignment line, live or
#: commented out. Anchored at both ends of the name so a longer variable that
#: merely starts with a shorter one's name cannot stand in for it.
_ASSIGNMENT_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _documented_variables() -> set[str]:
    text = _ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    return set(_ASSIGNMENT_RE.findall(text))


def test_env_example_exists() -> None:
    assert _ENV_EXAMPLE_PATH.is_file(), (
        f"operator env template missing at {_ENV_EXAMPLE_PATH}"
    )


def test_env_example_documents_every_env_var() -> None:
    documented = _documented_variables()
    missing = sorted(var.value for var in EnvVar if var.value not in documented)
    assert not missing, (
        "the operator env template documents no default for "
        f"{len(missing)} recognised environment variable(s): "
        f"{', '.join(missing)}. Add a commented '# NAME=default' line with a "
        "prose comment stating what the variable does and what changing it "
        "costs, under the matching section of .env.example."
    )
