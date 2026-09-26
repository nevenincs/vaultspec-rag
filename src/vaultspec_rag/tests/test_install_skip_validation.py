"""``--skip`` token validation, shared by install and uninstall.

Real filesystem (``tmp_path``), real ``vaultspec_core``. No mocks. An unknown
token must be refused before either command touches the workspace; a valid
one must reach the orchestration unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from vaultspec_core.core.enums import Tool
from vaultspec_core.core.exceptions import ProviderError
from vaultspec_core.core.provider_registry import VALID_PROVIDERS
from vaultspec_core.core.provider_registry import validate_skip as _core_validate_skip

from ..commands._install import install_run
from ..commands._skip import rag_skip_vocabulary, validate_rag_skip
from ..commands._uninstall import uninstall_run

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: The full vocabulary, derived independently of the module under test: the
#: tokens rag itself interprets, core's provider names, and the sync-pass
#: names core's own ``--skip`` documents.
_EXPECTED_VOCABULARY = frozenset({"core", "mcp", "hooks", "precommit"}) | {
    tool.value for tool in Tool
}


def _core_accepted_skip_tokens() -> frozenset[str]:
    """Probe core's own ``validate_skip`` for the tokens it accepts.

    Calls the real function under test's dependency rather than
    reconstructing its internal formula, so a change to what core allows is
    caught here without the two copies drifting apart.
    """
    candidates = VALID_PROVIDERS | rag_skip_vocabulary()
    accepted: set[str] = set()
    for token in candidates:
        try:
            _core_validate_skip({token})
        except ProviderError:
            continue
        accepted.add(token)
    return frozenset(accepted)


def test_rag_skip_vocabulary_matches_the_domain() -> None:
    assert rag_skip_vocabulary() == _EXPECTED_VOCABULARY


def test_rag_skip_vocabulary_is_a_superset_of_cores_accepted_skip_set() -> None:
    assert rag_skip_vocabulary() >= _core_accepted_skip_tokens()


@pytest.mark.parametrize("token", sorted(_EXPECTED_VOCABULARY))
def test_validate_rag_skip_accepts_every_valid_token(token: str) -> None:
    validate_rag_skip({token})


def test_validate_rag_skip_rejects_an_unknown_token() -> None:
    with pytest.raises(ValueError, match="Invalid --skip value") as excinfo:
        validate_rag_skip({"bogus"})
    message = str(excinfo.value)
    assert "bogus" in message
    for token in _EXPECTED_VOCABULARY:
        assert token in message


def test_install_rejects_unknown_skip_before_any_write(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bogus"):
        install_run(path=tmp_path, skip={"bogus"}, assume_yes=True)
    assert not (tmp_path / ".vaultspec").exists()


def test_uninstall_rejects_unknown_skip_before_any_write(tmp_path: Path) -> None:
    install_run(path=tmp_path, assume_yes=True)
    marker = tmp_path / ".vaultspec"
    assert marker.is_dir()
    files_before = sorted(marker.rglob("*"))

    with pytest.raises(ValueError, match="bogus"):
        uninstall_run(path=tmp_path, force=True, skip={"bogus"})

    assert sorted(marker.rglob("*")) == files_before
