"""The persisted per-root automatic-update opt-out fails closed.

An operator's stop has to outlive the watcher it stopped, and a store that
cannot be read must never be taken to mean "nobody stopped anything".

MUTATION PROOF, each run as one uninterrupted break, run, restore, run:

- Making ``_read`` skip a record that fails validation instead of raising
  fails ``test_one_malformed_record_makes_the_whole_store_unverifiable`` on
  its ``UNVERIFIABLE`` assertion.
- Treating ``RootRecordStoreError`` as an empty store in
  ``disable_auto_update`` fails
  ``test_an_unreadable_store_refuses_a_write_and_is_left_untouched`` on its
  ``pytest.raises``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .. import watcher_intent
from .._root_record_store import RootRecordStoreError
from ..watcher_intent import (
    AutoUpdateState,
    auto_update_state,
    auto_update_store_path,
    disable_auto_update,
    disabled_roots,
    enable_auto_update,
    load_auto_update_store,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_status_dir")]


def test_the_store_lives_in_the_status_directory(isolated_status_dir: Path) -> None:
    assert auto_update_store_path() == isolated_status_dir / "auto-update.json"


def test_absence_of_a_record_means_enabled(tmp_path: Path) -> None:
    assert auto_update_state(tmp_path) is AutoUpdateState.ENABLED


def test_stop_survives_a_reload_and_only_start_clears_it(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    record = disable_auto_update(root, initiator="cli")
    assert record.initiator == "cli"
    # A fresh process sees only the file.
    watcher_intent._snapshot = None
    assert load_auto_update_store() is AutoUpdateState.ENABLED
    assert auto_update_state(root) is AutoUpdateState.DISABLED
    assert auto_update_state(tmp_path) is AutoUpdateState.ENABLED
    assert enable_auto_update(root) is True
    assert auto_update_state(root) is AutoUpdateState.ENABLED
    assert enable_auto_update(root) is False


def test_a_repeated_stop_keeps_the_first_record(tmp_path: Path) -> None:
    first = disable_auto_update(tmp_path, initiator="cli")
    again = disable_auto_update(tmp_path, initiator="mcp")
    assert again == first


def test_a_deleted_root_keeps_its_record(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    disable_auto_update(root, initiator="cli")
    root.rmdir()
    assert auto_update_state(root) is AutoUpdateState.DISABLED
    records, fault = disabled_roots()
    assert fault is None
    assert [record.root for record in records] == [str(root.resolve())]


def test_one_malformed_record_makes_the_whole_store_unverifiable(
    tmp_path: Path,
) -> None:
    disable_auto_update(tmp_path, initiator="cli")
    path = auto_update_store_path()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["roots"]["other"] = {"root": "/elsewhere", "auto_update": True}
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_auto_update_store() is AutoUpdateState.UNVERIFIABLE
    # Unverifiable for every root, including one that was never recorded.
    assert auto_update_state(tmp_path / "never") is AutoUpdateState.UNVERIFIABLE
    _, fault = disabled_roots()
    assert fault is not None
    assert fault.startswith("malformed")


def test_an_unreadable_store_refuses_a_write_and_is_left_untouched(
    tmp_path: Path,
) -> None:
    path = auto_update_store_path()
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RootRecordStoreError) as raised:
        disable_auto_update(tmp_path, initiator="cli")
    assert raised.value.kind == "malformed"
    with pytest.raises(RootRecordStoreError):
        enable_auto_update(tmp_path)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_repaired_store_is_noticed_after_the_retry_window(
    tmp_path: Path,
) -> None:
    path = auto_update_store_path()
    path.write_text("{not json", encoding="utf-8")
    assert load_auto_update_store() is AutoUpdateState.UNVERIFIABLE
    path.unlink()
    # Inside the window the failed read stands, so a repaired file is not yet
    # read; this is what fails if the window is not honoured.
    assert auto_update_state(tmp_path) is AutoUpdateState.UNVERIFIABLE

    # Age the failed read by the window itself on the real monotonic clock
    # rather than sleeping through it.
    failed = watcher_intent._snapshot
    assert failed is not None
    watcher_intent._snapshot = replace(
        failed, loaded_at=failed.loaded_at - watcher_intent.UNVERIFIABLE_RETRY_SECONDS
    )
    assert auto_update_state(tmp_path) is AutoUpdateState.ENABLED
