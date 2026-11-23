"""Recorded roots compare by canonical identity, and unusable ones get no key.

MUTATION PROOF, one uninterrupted sequence: removing the ``except`` clause in
``canonical_root_key_or_none`` fails
``test_an_unresolvable_root_has_no_key`` on the NUL-root ``ValueError``.
Removing the blank-string check fails ``test_absent_or_blank_roots_have_no_key``
on its ``is None`` assertion for the blank strings, because a blank path
resolves to the working directory. Restoring each returns the module to green.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._root_identity import canonical_root_key, canonical_root_key_or_none

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_equivalent_spellings_share_one_key(tmp_path: Path) -> None:
    project = tmp_path / "project"
    assert canonical_root_key_or_none(str(project / "nested" / "..")) == (
        canonical_root_key(project)
    )
    assert canonical_root_key_or_none(project) == canonical_root_key(project)


@pytest.mark.parametrize("value", [None, "", "   ", 7, ["/repo"]])
def test_absent_or_blank_roots_have_no_key(value: object) -> None:
    assert canonical_root_key_or_none(value) is None


def test_an_unresolvable_root_has_no_key() -> None:
    assert canonical_root_key_or_none("bad\0root") is None
