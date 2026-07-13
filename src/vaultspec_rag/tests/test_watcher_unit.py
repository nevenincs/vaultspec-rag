"""Unit tests for the watcher change filter (no GPU).

The filter decides which filesystem events reach the indexer. Index-shaping
control files must be admitted as ordinary code changes so the indexer-side
config-epoch check can observe the drift and self-escalate; non-vault markdown
must be admitted because the chunker's language map indexes it.
"""

from pathlib import Path

import pytest

from ..watcher import _is_code_change, _is_vault_change

pytestmark = [pytest.mark.unit]


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    vault = root / ".vault"
    vault.mkdir(parents=True)
    return root, vault


def test_root_control_files_are_admitted(project: tuple[Path, Path]) -> None:
    root, vault = project
    for name in (".gitignore", ".vaultragignore", ".vaultragpreprocess.toml"):
        assert _is_code_change(root / name, root, vault) is True


def test_nested_gitignore_is_admitted(project: tuple[Path, Path]) -> None:
    root, vault = project
    assert _is_code_change(root / "pkg" / "sub" / ".gitignore", root, vault) is True


def test_markdown_outside_vault_is_code_change(project: tuple[Path, Path]) -> None:
    root, vault = project
    assert _is_code_change(root / "README.md", root, vault) is True
    assert _is_code_change(root / "docs" / "guide.md", root, vault) is True


def test_markdown_inside_vault_stays_vault_classified(
    project: tuple[Path, Path],
) -> None:
    root, vault = project
    doc = vault / "adr" / "2026-01-01-x-adr.md"
    assert _is_vault_change(doc, vault) is True
    assert _is_code_change(doc, root, vault) is False


def test_path_outside_root_is_rejected(
    project: tuple[Path, Path], tmp_path: Path
) -> None:
    root, vault = project
    assert _is_code_change(tmp_path / "elsewhere" / ".gitignore", root, vault) is False
    assert _is_code_change(tmp_path / "elsewhere" / "a.py", root, vault) is False


def test_unrelated_extension_still_rejected(project: tuple[Path, Path]) -> None:
    root, vault = project
    assert _is_code_change(root / "photo.jpg", root, vault) is False
