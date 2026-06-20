"""Unit tests for destructive-operation path-containment safety.

Pure filesystem logic: no GPU, no Qdrant, no service. Escapes are tested
through parent traversal and absolute out-of-base paths, which exercise
the resolve-then-compare logic that also closes symlink escapes (both
resolve out of the base) without depending on symlink-creation privilege.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..storage_safety import StorageSafetyError, is_within, resolve_within

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_descendant_is_allowed(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    target = base / "qdrant" / "storage"
    target.mkdir(parents=True)
    assert resolve_within(target, base) == target.resolve()
    assert is_within(target, base) is True


def test_base_itself_is_allowed(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    base.mkdir()
    assert resolve_within(base, base) == base.resolve()


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    base.mkdir()
    escape = base / ".." / ".." / "etc"
    with pytest.raises(StorageSafetyError):
        resolve_within(escape, base)
    assert is_within(escape, base) is False


def test_sibling_outside_base_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    sibling = tmp_path / "other"
    base.mkdir()
    sibling.mkdir()
    with pytest.raises(StorageSafetyError):
        resolve_within(sibling, base)
    assert is_within(sibling, base) is False


def test_deeply_nested_descendant_is_allowed(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    target = base / "a" / "b" / "c" / "d"
    target.mkdir(parents=True)
    assert is_within(target, base) is True


def test_prefix_lookalike_sibling_is_rejected(tmp_path: Path) -> None:
    # `managed-evil` shares a string prefix with `managed` but is not
    # contained: a naive prefix check would wrongly allow it.
    base = tmp_path / "managed"
    lookalike = tmp_path / "managed-evil"
    base.mkdir()
    lookalike.mkdir()
    assert is_within(lookalike, base) is False
