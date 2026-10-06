"""The approval store can only withhold execution, never grant it by accident."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from ..indexer._preprocess_approval import (
    approval_store_path,
    approve_policy,
    policy_is_approved,
    read_approval,
    revoke_approval,
)
from ._private_files import assert_private_file

if TYPE_CHECKING:
    from pathlib import Path

# Every test gets its own, empty approval store.
pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_status_dir")]

_DIGEST = "sha256:" + "a" * 64
_OTHER_DIGEST = "sha256:" + "b" * 64
_WHEN = "2026-01-01T00:00:00+00:00"


def _root(tmp_path: Path, name: str = "root") -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def test_the_store_lives_in_the_status_directory_not_the_repository(
    tmp_path: Path,
    isolated_status_dir: Path,
) -> None:
    root = _root(tmp_path)
    approve_policy(root, _DIGEST, approved_at=_WHEN)

    assert approval_store_path() == isolated_status_dir / "preprocess-approvals.json"
    assert approval_store_path().is_file()
    assert list(root.iterdir()) == []


def test_an_empty_store_approves_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)

    assert read_approval(root) is None
    assert policy_is_approved(root, _DIGEST) is False


def test_approval_binds_the_root_and_the_exact_digest(tmp_path: Path) -> None:
    root = _root(tmp_path)
    other = _root(tmp_path, "other")

    recorded = approve_policy(root, _DIGEST, approved_at=_WHEN)

    assert recorded.root == str(root.resolve())
    assert recorded.policy_digest == _DIGEST
    assert recorded.approved_at == _WHEN
    assert policy_is_approved(root, _DIGEST) is True
    assert policy_is_approved(root, _OTHER_DIGEST) is False
    assert policy_is_approved(other, _DIGEST) is False


def test_a_root_without_a_policy_is_never_approved(tmp_path: Path) -> None:
    root = _root(tmp_path)
    approve_policy(root, _DIGEST, approved_at=_WHEN)

    assert policy_is_approved(root, None) is False


def test_a_root_has_one_approved_policy_at_a_time(tmp_path: Path) -> None:
    root = _root(tmp_path)
    approve_policy(root, _DIGEST, approved_at=_WHEN)
    approve_policy(root, _OTHER_DIGEST, approved_at=_WHEN)

    assert policy_is_approved(root, _DIGEST) is False
    assert policy_is_approved(root, _OTHER_DIGEST) is True


def test_approving_one_root_keeps_every_other_approval(tmp_path: Path) -> None:
    first = _root(tmp_path, "first")
    second = _root(tmp_path, "second")
    approve_policy(first, _DIGEST, approved_at=_WHEN)
    approve_policy(second, _OTHER_DIGEST, approved_at=_WHEN)

    assert policy_is_approved(first, _DIGEST) is True
    assert policy_is_approved(second, _OTHER_DIGEST) is True


def test_equivalent_spellings_of_a_root_share_one_approval(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "nested").mkdir()
    approve_policy(root, _DIGEST, approved_at=_WHEN)

    assert policy_is_approved(root / "nested" / "..", _DIGEST) is True
    assert policy_is_approved(str(root), _DIGEST) is True


def test_revoke_removes_only_that_root(tmp_path: Path) -> None:
    first = _root(tmp_path, "first")
    second = _root(tmp_path, "second")
    approve_policy(first, _DIGEST, approved_at=_WHEN)
    approve_policy(second, _DIGEST, approved_at=_WHEN)

    assert revoke_approval(first) is True
    assert revoke_approval(first) is False
    assert policy_is_approved(first, _DIGEST) is False
    assert policy_is_approved(second, _DIGEST) is True


@pytest.mark.parametrize(
    "damaged",
    [
        "{not json",
        "[]",
        json.dumps({"version": 2, "roots": {}}),
        json.dumps({"roots": {}}),
        json.dumps({"version": 1, "roots": []}),
    ],
)
def test_a_damaged_store_approves_nothing(tmp_path: Path, damaged: str) -> None:
    """Every unreadable shape withholds execution rather than granting it.

    Mutation check: accepting a store whatever its ``version`` says returns
    the genuine record kept under a wrong and under a missing version, and
    fails this test on those two cases; restoring the version check passes.
    """
    root = _root(tmp_path)
    approve_policy(root, _DIGEST, approved_at=_WHEN)
    path = approval_store_path()
    if damaged.startswith("{") and '"roots": {}' in damaged:
        # Keep the genuine record in place so only the envelope is wrong.
        document = json.loads(path.read_text(encoding="utf-8"))
        envelope = json.loads(damaged)
        envelope["roots"] = document["roots"]
        damaged = json.dumps(envelope)
    path.write_text(damaged, encoding="utf-8")

    assert policy_is_approved(root, _DIGEST) is False


def test_one_malformed_record_withholds_only_its_own_root(tmp_path: Path) -> None:
    good = _root(tmp_path, "good")
    bad = _root(tmp_path, "bad")
    approve_policy(good, _DIGEST, approved_at=_WHEN)
    approve_policy(bad, _DIGEST, approved_at=_WHEN)
    path = approval_store_path()
    document = json.loads(path.read_text(encoding="utf-8"))
    bad_key = next(
        key for key, record in document["roots"].items() if "bad" in record["root"]
    )
    document["roots"][bad_key] = {"root": str(bad), "policy_digest": ""}
    path.write_text(json.dumps(document), encoding="utf-8")

    assert policy_is_approved(bad, _DIGEST) is False
    assert policy_is_approved(good, _DIGEST) is True


def test_the_store_is_written_owner_only(tmp_path: Path) -> None:
    """Another account on the machine must not be able to plant an approval.

    Mutation check: publishing the store without the private option fails the
    owner-only assertion; restoring it passes.
    """
    approve_policy(_root(tmp_path), _DIGEST, approved_at=_WHEN)
    assert_private_file(approval_store_path())

    # Rewriting an existing store keeps it private.
    approve_policy(_root(tmp_path, "second"), _DIGEST, approved_at=_WHEN)
    assert_private_file(approval_store_path())


def test_an_unreadable_store_is_not_rewritten_as_empty(tmp_path: Path) -> None:
    """A write must not treat "could not read" as "nothing was approved".

    The store is rewritten whole, so approving one root over a store that
    merely failed to open would cost every other root its approval.

    Mutation check: reading for update with the lenient reader gets as far as
    the replace, whose error does not name the store as the file that could
    not be read, and fails here on the filename; restoring the strict read
    passes.
    """
    first = _root(tmp_path, "first")
    second = _root(tmp_path, "second")
    approve_policy(first, _DIGEST, approved_at=_WHEN)
    path = approval_store_path()
    saved = path.read_bytes()
    # A directory where the file should be: present, and unreadable as a file.
    path.unlink()
    path.mkdir()
    try:
        for write in (
            lambda: approve_policy(second, _DIGEST, approved_at=_WHEN),
            lambda: revoke_approval(first),
        ):
            with pytest.raises(OSError) as refused:
                write()
            # Refused by the read itself, which names the store as the file
            # it could not open; a failed replace would not.
            assert os.path.normcase(str(refused.value.filename)) == os.path.normcase(
                str(path)
            )
        # The read side still fails closed rather than raising.
        assert policy_is_approved(first, _DIGEST) is False
    finally:
        path.rmdir()
        path.write_bytes(saved)

    assert policy_is_approved(first, _DIGEST) is True


def test_writing_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    approve_policy(_root(tmp_path), _DIGEST, approved_at=_WHEN)

    assert [path.name for path in approval_store_path().parent.iterdir()] == [
        "preprocess-approvals.json"
    ]
