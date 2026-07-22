"""Unit tests for the watcher change filter (no GPU).

The filter decides which filesystem events reach the indexer. Index-shaping
control files must be admitted as ordinary code changes so the indexer-side
config-epoch check can observe the drift and self-escalate; non-vault markdown
must be admitted because the chunker's language map indexes it. A file whose
extension is unsupported but matched by a resolved preprocess rule must also be
admitted, and - since a root's preprocess config is repo-authored code
(preprocess-sandbox-removal ADR) - that resolution happens for any root with no
trust record.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ..config import EnvVar, reset_config
from ..indexer._chunking import SUPPORTED_EXTENSIONS
from ..indexer._preprocess_config import (
    PREPROCESS_CONFIG_FILENAME,
    load_preprocess_rules,
)
from ..watcher import _is_code_change, _is_vault_change

pytestmark = [pytest.mark.unit]


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    vault = root / ".vault"
    vault.mkdir(parents=True)
    return root, vault


@pytest.fixture
def _default_preprocess_mode(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Resolve the ``default`` mode with an isolated status dir.

    Clearing the mode env var leaves the resolved preprocess mode at
    ``default``, which resolves a root's rules with no trust act - the
    condition the S11 regression asserts. The status dir is isolated per the
    managed-singleton rule.
    """
    status = tmp_path_factory.mktemp("watcher_status")
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status))
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    reset_config()
    try:
        yield
    finally:
        reset_config()


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


def test_watcher_uses_every_indexer_extension(project: tuple[Path, Path]) -> None:
    root, vault = project
    for extension in SUPPORTED_EXTENSIONS:
        assert _is_code_change(root / f"source{extension}", root, vault) is True


def test_watcher_normalizes_suffix_case(project: tuple[Path, Path]) -> None:
    root, vault = project
    assert _is_code_change(root / "MODULE.PY", root, vault) is True
    assert _is_code_change(root / "CONFIG.JSON", root, vault) is True
    assert _is_code_change(root / "README.MD", root, vault) is True
    assert _is_vault_change(vault / "DECISION.MD", vault) is True


def test_watcher_rejects_extensions_absent_from_indexer(
    project: tuple[Path, Path],
) -> None:
    root, vault = project
    for extension in (".lua", ".swift", ".zig"):
        assert extension not in SUPPORTED_EXTENSIONS
        assert _is_code_change(root / f"source{extension}", root, vault) is False


@pytest.mark.usefixtures("_default_preprocess_mode")
def test_preprocessable_file_admitted_via_resolved_rule_no_trust(
    project: tuple[Path, Path],
) -> None:
    """A rule-matched file is a code change under default mode, no trust record.

    The watcher resolves the root's preprocess config
    (``code_indexer.preprocess_config()``) and hands it to the change filter so
    a watched ``.pdf`` - an extension outside ``_CODE_EXTENSIONS`` - is
    recognized. Since the trust store was removed (ADR D7/D9),
    ``load_preprocess_rules`` resolves the rule for this root with no trust act,
    so the watched file is admitted. Without the resolved config it is rejected,
    proving the config is what admits it.
    """
    root, vault = project
    root.mkdir(parents=True, exist_ok=True)
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        """
        version = 1

        [[rule]]
        pattern = "*.pdf"
        command = "extract {path}"
        on_error = "skip"
        """,
        encoding="utf-8",
    )

    config = load_preprocess_rules(root)
    assert bool(config), "rule must resolve for any root with no trust record"

    watched_pdf = root / "docs" / "report.pdf"
    assert _is_code_change(watched_pdf, root, vault, config) is True
    # The .pdf is admitted only because of the resolved rule: with no config,
    # its extension is outside _CODE_EXTENSIONS and it is rejected.
    assert _is_code_change(watched_pdf, root, vault, None) is False
