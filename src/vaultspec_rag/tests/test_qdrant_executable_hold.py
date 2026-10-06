"""Guard tests for holding an executable between hashing it and running it.

A digest check and the process creation that follows it are two looks at a
path. These tests stand inside the gap between them - the block in which the
file is held - and try to change what the path names. What "held" guarantees
differs by platform, so each platform's guarantee has its own test and the
others are skipped there, with the reason.

No mocks: every file is a real file, every swap is a real rename, write or
unlink, and where a process is created it is a real process whose only trace
is a file it writes.

Every test here is a guard and has been observed failing for its intended
reason; the mutation each one catches is named in its own docstring.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ..qdrant_runtime._executable_hold import held_executable

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_VERIFIED = b"the bytes that were verified\n"
_SWAPPED_IN = b"bytes nobody verified\n"


def _marker_script(directory: Path, name: str) -> tuple[Path, Path]:
    """Write a shell script that leaves a marker file, and return both."""
    marker = directory / f"{name}-ran.txt"
    script = directory / f"{name}.sh"
    script.write_text(f"#!/bin/sh\necho ran > '{marker}'\n", encoding="utf-8")
    script.chmod(0o700)
    return script, marker


class TestWhatMayBeHeld:
    """Only a regular file, opened as itself."""

    def test_the_digest_is_read_from_the_held_file(self, tmp_path: Path) -> None:
        target = tmp_path / "qdrant"
        target.write_bytes(_VERIFIED)

        with held_executable(target) as held:
            assert held.sha256() == hashlib.sha256(_VERIFIED).hexdigest()
            # Hashing twice reads the whole file twice, not the remainder.
            assert held.sha256() == hashlib.sha256(_VERIFIED).hexdigest()
            assert held.names_held_file()

    def test_a_link_is_refused_and_never_followed(self, tmp_path: Path) -> None:
        """A link to a perfectly good file is still not the file that was named.

        Mutation it catches: opening the path with a plain open, which follows
        the link, hands back the target and fails this on the missing
        ``OSError``.
        """
        target = tmp_path / "real"
        target.write_bytes(_VERIFIED)
        link = tmp_path / "qdrant"
        link.symlink_to(target)

        with pytest.raises(OSError), held_executable(link):
            pass

    @pytest.mark.parametrize("shape", ["directory", "missing"])
    def test_anything_but_an_existing_regular_file_is_refused(
        self, shape: str, tmp_path: Path
    ) -> None:
        target = tmp_path / "qdrant"
        if shape == "directory":
            target.mkdir()

        with pytest.raises(OSError), held_executable(target):
            pass


@pytest.mark.skipif(
    sys.platform != "win32", reason="only Windows can deny writers and renames"
)
class TestAHeldFileCannotChangeOnWindows:
    """The hold itself keeps the path naming the hashed bytes."""

    def test_no_replacement_rewrite_rename_or_removal_succeeds_while_held(
        self, tmp_path: Path
    ) -> None:
        """Every way of swapping the file in the window is refused.

        The same operations succeed once the hold is released, so each
        refusal is the hold's doing and not a file nobody could have touched.

        Mutation it catches: holding with write sharing, the way an ordinary
        no-follow open does, lets the in-place rewrite through and fails this
        on that attempt's missing ``PermissionError``.
        """
        target = tmp_path / "qdrant.exe"
        target.write_bytes(_VERIFIED)
        other = tmp_path / "other.exe"
        other.write_bytes(_SWAPPED_IN)
        aside = tmp_path / "moved-aside.exe"

        def rewrite_in_place() -> None:
            with target.open("ab") as stream:
                stream.write(_SWAPPED_IN)

        attempts = {
            "replace": lambda: os.replace(other, target),
            "rewrite in place": rewrite_in_place,
            "rename away": lambda: os.rename(target, aside),
            "remove": target.unlink,
            "rename the directory": lambda: os.rename(
                tmp_path, tmp_path.with_name(f"{tmp_path.name}-moved")
            ),
        }
        with held_executable(target) as held:
            assert held.exclusive
            assert held.launch_path == str(target)
            verified = held.sha256()
            for name, attempt in attempts.items():
                with pytest.raises(PermissionError):
                    attempt()
                assert target.read_bytes() == _VERIFIED, name
            assert held.sha256() == verified
            assert held.unchanged(verified)

        rewrite_in_place()
        os.replace(other, target)
        assert target.read_bytes() == _SWAPPED_IN

    def test_a_second_reader_may_hold_the_file_at_the_same_time(
        self, tmp_path: Path
    ) -> None:
        """A status check and a spawn hashing the same install do not collide."""
        target = tmp_path / "qdrant.exe"
        target.write_bytes(_VERIFIED)

        with held_executable(target) as first, held_executable(target) as second:
            assert first.sha256() == second.sha256()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="only Linux can create a process from an open descriptor",
)
class TestAHeldFileIsTheOneThatRunsOnLinux:
    """A process is created from the held descriptor, not from the path."""

    def test_a_replacement_made_while_held_does_not_run(self, tmp_path: Path) -> None:
        """The path is given a new file inside the window; the old one runs.

        Mutation it catches: creating the process from the path instead of
        the held descriptor runs the replacement, and this fails on the marker
        assertions below.
        """
        launcher, ran = _marker_script(tmp_path, "verified")
        replacement, replacement_ran = _marker_script(tmp_path, "swapped")

        with held_executable(launcher) as held:
            assert not held.exclusive
            verified = held.sha256()
            os.replace(replacement, launcher)
            assert not held.names_held_file()

            process = subprocess.Popen(
                [str(launcher)], executable=held.launch_path, pass_fds=held.inherited
            )
            assert process.wait(timeout=30.0) == 0
            assert held.unchanged(verified)

        assert ran.is_file()
        assert not replacement_ran.exists(), "the file swapped in was executed"

    def test_a_rewrite_in_place_is_seen_once_the_process_exists(
        self, tmp_path: Path
    ) -> None:
        """The one change the descriptor cannot outrun is caught afterwards.

        Mutation it catches: answering "unchanged" without hashing again
        fails this on the final assertion.
        """
        launcher, _ran = _marker_script(tmp_path, "verified")

        with held_executable(launcher) as held:
            verified = held.sha256()
            with launcher.open("ab") as stream:
                stream.write(b"echo rewritten\n")
            process = subprocess.Popen(
                [str(launcher)],
                executable=held.launch_path,
                pass_fds=held.inherited,
                stdout=subprocess.DEVNULL,
            )
            assert process.wait(timeout=30.0) == 0

            assert not held.unchanged(verified)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows refuses the swap itself")
class TestAPathThatStopsNamingTheHeldFile:
    """Where a process must be created by path, the path is looked at again."""

    def test_a_replacement_is_seen_through_the_path(self, tmp_path: Path) -> None:
        """Mutation it catches: comparing nothing, or the path with itself,
        reports the swapped path as still naming the held file and fails the
        second assertion."""
        target = tmp_path / "qdrant"
        target.write_bytes(_VERIFIED)
        other = tmp_path / "other"
        other.write_bytes(_VERIFIED)

        with held_executable(target) as held:
            assert held.names_held_file()
            os.replace(other, target)
            assert not held.names_held_file()
            target.unlink()
            assert not held.names_held_file()
