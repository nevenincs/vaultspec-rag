"""Unit tests for watcher code-change classification.

``_is_code_change`` rejects vault-contained and out-of-root paths, treats the
three index-shaping control filenames as reconciliation triggers, and otherwise
fails closed without a ``ResolvedIndexPolicy`` snapshot. With a snapshot, only
an admitted classification whose content kind is ``CODE`` is code-owned. Each
snapshot assigns one owner; disagreeing explicit targets fail during resolution.

The conventional source profile admits ordinary code suffixes. Parser
capability, document-target rules, preprocessing defaults, and trust posture do
not widen code admission. An explicit ``target='code'`` may admit unconventional
content such as PDF.

Tests supply snapshots directly; they do not exercise the production watcher's
snapshot refresh and failure-retention lifecycle.
"""

from pathlib import Path

import pytest

from ..indexer._chunking import CONVENTIONAL_SOURCE_EXTENSIONS
from ..indexer._content_policy import (
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from ..indexer._resolved_policy import ResolvedIndexPolicy, resolve_index_policy
from ..watcher import _is_code_change, _is_vault_change

pytestmark = [pytest.mark.unit]


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    vault = root / ".vault"
    vault.mkdir(parents=True)
    return root, vault


@pytest.fixture
def code_policy(project: tuple[Path, Path]) -> ResolvedIndexPolicy:
    root, _vault = project
    return resolve_index_policy(
        root,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
    )


def test_root_control_files_are_admitted(project: tuple[Path, Path]) -> None:
    root, vault = project
    for name in (".gitignore", ".vaultragignore", ".vaultragpreprocess.toml"):
        assert _is_code_change(root / name, root, vault, None) is True


def test_nested_gitignore_is_admitted(project: tuple[Path, Path]) -> None:
    root, vault = project
    assert (
        _is_code_change(root / "pkg" / "sub" / ".gitignore", root, vault, None)
        is True
    )


def test_markdown_outside_vault_is_not_conventional_code(
    project: tuple[Path, Path],
    code_policy: ResolvedIndexPolicy,
) -> None:
    root, vault = project
    assert _is_code_change(root / "README.md", root, vault, code_policy) is False
    assert (
        _is_code_change(root / "docs" / "guide.md", root, vault, code_policy)
        is False
    )


def test_markdown_inside_vault_stays_vault_classified(
    project: tuple[Path, Path],
) -> None:
    root, vault = project
    doc = vault / "adr" / "2026-01-01-x-adr.md"
    assert _is_vault_change(doc, vault) is True
    assert _is_code_change(doc, root, vault, None) is False


def test_path_outside_root_is_rejected(
    project: tuple[Path, Path], tmp_path: Path
) -> None:
    root, vault = project
    assert (
        _is_code_change(tmp_path / "elsewhere" / ".gitignore", root, vault, None)
        is False
    )
    assert (
        _is_code_change(tmp_path / "elsewhere" / "a.py", root, vault, None)
        is False
    )


def test_unrelated_extension_still_rejected(
    project: tuple[Path, Path],
    code_policy: ResolvedIndexPolicy,
) -> None:
    root, vault = project
    assert _is_code_change(root / "photo.jpg", root, vault, code_policy) is False


def test_watcher_uses_every_conventional_source_extension(
    project: tuple[Path, Path],
    code_policy: ResolvedIndexPolicy,
) -> None:
    root, vault = project
    for extension in CONVENTIONAL_SOURCE_EXTENSIONS:
        assert (
            _is_code_change(root / f"source{extension}", root, vault, code_policy)
            is True
        )


def test_watcher_normalizes_suffix_case(
    project: tuple[Path, Path],
    code_policy: ResolvedIndexPolicy,
) -> None:
    root, vault = project
    assert _is_code_change(root / "MODULE.PY", root, vault, code_policy) is True
    assert _is_code_change(root / "CONFIG.JSON", root, vault, code_policy) is False
    assert _is_code_change(root / "README.MD", root, vault, code_policy) is False
    assert _is_vault_change(vault / "DECISION.MD", vault) is True


def test_watcher_rejects_extensions_absent_from_indexer(
    project: tuple[Path, Path],
    code_policy: ResolvedIndexPolicy,
) -> None:
    root, vault = project
    for extension in (".lua", ".swift", ".zig"):
        assert extension not in CONVENTIONAL_SOURCE_EXTENSIONS
        assert (
            _is_code_change(root / f"source{extension}", root, vault, code_policy)
            is False
        )


def test_explicit_code_target_admits_unconventional_source(
    project: tuple[Path, Path],
) -> None:
    """Prove explicit ``target='code'`` admits ``.pdf`` through a supplied
    ``ResolvedIndexPolicy`` snapshot, while ``policy=None`` rejects it.
    """
    root, vault = project
    root.mkdir(parents=True, exist_ok=True)
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        """
        version = 2

        [[rule]]
        target = "code"
        extractor_version = "1.0.0"
        pattern = "*.pdf"
        command = "extract {path}"
        on_error = "skip"
        """,
        encoding="utf-8",
    )

    policy = resolve_index_policy(
        root,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
    )

    watched_pdf = root / "docs" / "report.pdf"
    assert _is_code_change(watched_pdf, root, vault, policy) is True
    assert _is_code_change(watched_pdf, root, vault, None) is False
