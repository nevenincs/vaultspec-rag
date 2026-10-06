"""The one verdict on what the managed Qdrant server's installed name holds.

The resolver, the spawn check, the provisioner and the status listing all ask
the same function, so each state is pinned here once, on real files in a temp
directory.

A healthy verdict needs a file the committed pins vouch for, and they vouch
only for the real release. So the healthy cases run with a stand-in pinned
through the one declared seam; every other case runs against the committed
pins as they are, which refuse any stand-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import TYPE_CHECKING

import pytest

from ..config._types import EnvVar
from ..qdrant_runtime._constants import MANIFEST_FILENAME, QDRANT_SERVER_VERSION
from ..qdrant_runtime._managed_install import (
    InstallState,
    classify_managed_binary,
    unreadable_refusal,
)
from ..qdrant_runtime._resolve import asset_for_platform, binary_filename
from ._fake_qdrant_binary import unreadable
from ._stand_in_release import pinned_stand_in

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_PINNED = b"\x7fthe executable a pinned stand-in release holds\x00" * 256
_OTHER = b"an executable no pin table vouches for"


@pytest.fixture
def binary(tmp_path: Path) -> Path:
    """The installed name inside an empty version directory."""
    version_dir = tmp_path / "bin" / "qdrant" / QDRANT_SERVER_VERSION
    version_dir.mkdir(parents=True)
    return version_dir / binary_filename()


@pytest.fixture
def stand_in_pinned() -> Generator[None]:
    """Make ``_PINNED`` the pinned release executable for the test."""
    with pinned_stand_in(_PINNED):
        yield


class TestTheVerdict:
    def test_nothing_at_the_installed_name_is_absent(self, binary: Path) -> None:
        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.ABSENT
        assert judged.binary == binary
        assert judged.refusal == ""

    def test_a_file_where_the_version_directory_belongs_is_absent(
        self, tmp_path: Path
    ) -> None:
        """A path that cannot exist holds nothing; it is not an error to ask."""
        not_a_directory = tmp_path / QDRANT_SERVER_VERSION
        not_a_directory.write_text("a file", encoding="utf-8")

        judged = classify_managed_binary(not_a_directory / binary_filename())

        assert judged.state is InstallState.ABSENT

    @pytest.mark.usefixtures("stand_in_pinned")
    def test_a_pinned_executable_is_healthy_and_says_which_asset_it_is(
        self, binary: Path
    ) -> None:
        """The verdict carries the asset and the committed digest that matched.

        The resolver holds every later spawn to that digest, so it must be
        the one the table holds for the asset and not merely the file's own.
        """
        binary.write_bytes(_PINNED)

        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.HEALTHY
        assert judged.asset == asset_for_platform()
        assert judged.sha256 == hashlib.sha256(_PINNED).hexdigest()
        assert judged.refusal == ""

    @pytest.mark.usefixtures("stand_in_pinned")
    @pytest.mark.parametrize(
        "manifest",
        [
            None,
            "{ not json",
            json.dumps({"version": "0.0.1", "source": "operator"}),
        ],
        ids=["no manifest", "an unparseable manifest", "a manifest saying otherwise"],
    )
    def test_the_manifest_changes_neither_verdict(
        self, binary: Path, manifest: str | None
    ) -> None:
        """Pinned bytes are healthy and other bytes refused, whatever it says.

        Mutation: made ``_judge_content`` match no committed digest. Observed
        the healthy assertion fail in every case. Then made it match any
        content. Observed the refused assertion fail in every case.
        Restored after each; passes.
        """
        if manifest is not None:
            (binary.parent / MANIFEST_FILENAME).write_text(manifest, encoding="utf-8")

        binary.write_bytes(_PINNED)
        pinned = classify_managed_binary(binary)
        binary.write_bytes(_OTHER)
        other = classify_managed_binary(binary)

        assert pinned.state is InstallState.HEALTHY
        assert other.state is InstallState.REFUSED

    def test_the_stand_in_is_refused_once_it_is_no_longer_pinned(
        self, binary: Path
    ) -> None:
        """Health is the committed table's word, read on every call.

        The same bytes that are healthy inside the seam are refused outside
        it, which is the state every test not using the seam runs in.
        """
        binary.write_bytes(_PINNED)

        assert classify_managed_binary(binary).state is InstallState.REFUSED

    def test_other_bytes_are_refused_with_two_complete_ways_out(
        self, binary: Path
    ) -> None:
        """The refusal can be acted on as written, from whatever command showed it.

        Mutation: reworded the refusal to say "re-run with --upgrade", as it
        once did. Observed the command assertion fail. Restored; passes.
        """
        binary.write_bytes(_OTHER)

        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.REFUSED
        assert hashlib.sha256(_OTHER).hexdigest() in judged.problem
        assert str(binary) in judged.refusal
        assert "`vaultspec-rag server qdrant install --upgrade`" in judged.refusal
        assert (
            "`vaultspec-rag server qdrant install --upgrade --archive <file>`"
            in judged.refusal
        )
        assert EnvVar.QDRANT_BINARY.value in judged.refusal
        assert EnvVar.QDRANT_BINARY_SHA256.value in judged.refusal
        assert "re-run" not in judged.refusal.lower()

    @pytest.mark.usefixtures("stand_in_pinned")
    def test_a_link_is_refused_even_when_it_leads_to_a_pinned_executable(
        self, binary: Path, tmp_path: Path
    ) -> None:
        """What is installed must be the file itself, not a pointer to one.

        Mutation: removed the link test in ``classify_managed_binary``.
        Observed the state assertion fail (``obstructed`` where ``refused``
        was required): a link is not a regular file, so the operator was
        told nothing can be installed there, when the upgrade form replaces
        a link. Restored; passes.
        """
        target = tmp_path / "elsewhere"
        target.write_bytes(_PINNED)
        try:
            os.symlink(target, binary)
        except OSError:
            pytest.fail("Cannot create symlink - test requires symlink support")

        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.REFUSED
        assert "symbolic link" in judged.problem
        assert "`vaultspec-rag server qdrant install --upgrade`" in judged.refusal

    def test_a_directory_at_the_installed_name_is_obstructed(
        self, binary: Path
    ) -> None:
        binary.mkdir()

        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.OBSTRUCTED
        assert "Remove it" in judged.refusal
        assert "`vaultspec-rag server qdrant install`" in judged.refusal
        assert "--upgrade" not in judged.refusal

    @pytest.mark.usefixtures("stand_in_pinned")
    def test_a_file_that_cannot_be_read_is_unreadable_not_refused(
        self, binary: Path
    ) -> None:
        """Nothing is known about bytes that were never read.

        The file is the pinned executable throughout. While another handle
        holds it, or its permissions deny its owner, the verdict is that it
        cannot be read, and never that it is wrong.

        Mutation: made ``_judge_content`` catch ``RuntimeError`` where it
        catches ``OSError``. Observed ``PermissionError`` escape the call.
        Restored; passes.
        """
        binary.write_bytes(_PINNED)

        with unreadable(binary):
            judged = classify_managed_binary(binary)

        assert judged.state is InstallState.UNREADABLE
        assert "cannot be read" in judged.refusal
        assert "Close whatever holds it" in judged.refusal
        assert "--upgrade" not in judged.refusal
        # Readable again, the same file is what it always was.
        assert classify_managed_binary(binary).state is InstallState.HEALTHY


@pytest.mark.usefixtures("stand_in_pinned")
class TestWhatSitsBesideThePinnedExecutable:
    """A pinned executable is healthy only in a directory an install left.

    A library the server asks for by name can be loaded from the server's own
    directory, and the executable's digest says nothing about it.
    """

    @pytest.mark.parametrize(
        ("planted", "is_folder"),
        [("VCRUNTIME140.dll", False), ("notes.txt", False), ("qdrant.local", True)],
        ids=["a library", "any file", "a folder"],
    )
    def test_anything_no_install_wrote_refuses_a_pinned_executable(
        self, binary: Path, planted: str, is_folder: bool
    ) -> None:
        """The refusal names what is there and how to clear it.

        Mutation: made ``companions_verdict`` find nothing. Observed the state
        assertion fail in every case (``healthy`` where ``accompanied`` was
        required). Restored; passes.
        """
        binary.write_bytes(_PINNED)
        beside = binary.parent / planted
        if is_folder:
            beside.mkdir()
        else:
            beside.write_bytes(b"not an install's")

        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.ACCOMPANIED
        assert planted in judged.problem
        assert planted in judged.refusal
        assert f"Remove everything from {binary.parent} except" in judged.refusal
        assert "--upgrade" not in judged.refusal

    def test_what_an_install_writes_leaves_it_healthy(self, binary: Path) -> None:
        """The manifest and the working files of a run in progress are expected.

        A second command may be installing while this one judges, and a run
        that was killed leaves its working files until the next one sweeps
        them; neither is a reason to refuse a server that is what it should be.

        Mutation: made ``_install_writes`` recognise nothing. Observed the
        state assertion fail (``accompanied`` where ``healthy`` was required).
        Restored; passes.
        """
        binary.write_bytes(_PINNED)
        version_dir = binary.parent
        (version_dir / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
        (version_dir / f".{MANIFEST_FILENAME}.4242.0123456789ab.tmp").write_text(
            "{", encoding="utf-8"
        )
        (
            version_dir / f".{asset_for_platform()}.4242.0123456789ab.staging"
        ).write_bytes(b"half an archive")

        assert classify_managed_binary(binary).state is InstallState.HEALTHY

    def test_a_long_list_is_counted_not_recited(self, binary: Path) -> None:
        binary.write_bytes(_PINNED)
        for index in range(7):
            (binary.parent / f"stray-{index}.txt").write_bytes(b"")

        judged = classify_managed_binary(binary)

        assert judged.state is InstallState.ACCOMPANIED
        assert "stray-4.txt and 2 more" in judged.refusal
        assert "stray-5.txt" not in judged.refusal

    def test_other_bytes_are_refused_as_other_bytes_whatever_is_beside_them(
        self, binary: Path
    ) -> None:
        """The executable is judged first: its remedy is the one that installs."""
        binary.write_bytes(_OTHER)
        (binary.parent / "notes.txt").write_bytes(b"")

        assert classify_managed_binary(binary).state is InstallState.REFUSED

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="no permission here stops a directory's owner from listing it",
    )
    def test_a_directory_that_cannot_be_listed_is_unreadable_not_clean(
        self, binary: Path
    ) -> None:
        """Nothing is known about a directory nobody could list.

        The executable can still be opened by name, so it hashes as pinned;
        what is beside it is the part that cannot be seen.
        """
        if os.geteuid() == 0:
            pytest.fail("permissions do not stop the superuser listing a directory")
        binary.write_bytes(_PINNED)
        version_dir = binary.parent
        mode = version_dir.stat().st_mode
        version_dir.chmod(0o300)
        try:
            judged = classify_managed_binary(binary)
        finally:
            version_dir.chmod(mode)

        assert judged.state is InstallState.UNREADABLE
        assert "cannot be listed" in judged.refusal
        assert "--upgrade" not in judged.refusal


def test_the_unreadable_sentence_names_the_file_and_the_cause(tmp_path: Path) -> None:
    """One sentence for a binary of any source, so it names no source."""
    path = tmp_path / "any-binary"

    sentence = unreadable_refusal(path, PermissionError(13, "Permission denied"))

    assert str(path) in sentence
    assert "Permission denied" in sentence
    assert "managed" not in sentence
    assert "install" not in sentence
