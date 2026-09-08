"""Exact ICO parsing and Windows PE resource tests."""

from __future__ import annotations

import hashlib
import shutil
import struct
import sys
from pathlib import Path

import pytest

from tools.binaries.build_pyapp import APPLICATION_ICON, write_checksum
from tools.binaries.windows_icon import (
    IconResourceError,
    parse_ico,
    stamp_icon,
    verify_icon,
)

pytestmark = pytest.mark.unit

EXPECTED_SIZES = (256, 128, 64, 48, 32, 16)


def test_governed_icon_contains_the_exact_frame_inventory() -> None:
    """The committed ICO is a real ordered multi-frame application icon."""
    images = parse_ico(APPLICATION_ICON)

    assert tuple(image.width for image in images) == EXPECTED_SIZES
    assert tuple(image.height for image in images) == EXPECTED_SIZES
    assert all(struct.unpack_from("<I", image.payload)[0] == 40 for image in images)
    assert all((image.planes, image.bit_count) == (1, 32) for image in images)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        struct.pack("<HHH", 1, 1, 1),
        struct.pack("<HHH", 0, 2, 1),
        struct.pack("<HHH", 0, 1, 0),
        struct.pack("<HHH", 0, 1, 1),
        struct.pack("<HHHBBBBHHII", 0, 1, 1, 16, 16, 0, 0, 1, 32, 99, 22),
    ],
)
def test_parse_ico_rejects_malformed_containers(tmp_path: Path, payload: bytes) -> None:
    """Truncated, mistyped, empty, and out-of-bounds ICOs fail closed."""
    icon = tmp_path / "invalid.ico"
    icon.write_bytes(payload)

    with pytest.raises(IconResourceError):
        parse_ico(icon)


def test_parse_ico_rejects_overlapping_frame_payloads(tmp_path: Path) -> None:
    """Two directory entries cannot alias any portion of their image bytes."""
    directory_end = 6 + 2 * 16
    entry = struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, 8, directory_end)
    icon = tmp_path / "overlapping.ico"
    icon.write_bytes(struct.pack("<HHH", 0, 1, 2) + entry + entry + b"12345678")

    with pytest.raises(IconResourceError, match="invalid ICO frame 1"):
        parse_ico(icon)


def test_stamping_is_rejected_off_windows(tmp_path: Path) -> None:
    """A non-Windows release host cannot silently claim it stamped a PE."""
    if sys.platform == "win32":
        pytest.skip("non-Windows contract")
    executable = tmp_path / "sample.exe"
    executable.write_bytes(b"MZ")

    with pytest.raises(IconResourceError, match="only be updated on Windows"):
        stamp_icon(executable, APPLICATION_ICON)


@pytest.mark.skipif(sys.platform != "win32", reason="requires the Win32 resource API")
def test_real_pe_stamp_is_exact_and_precedes_checksum(tmp_path: Path) -> None:
    """A real PE keeps loading after stamping and its checksum binds icon bytes."""
    executable = tmp_path / "python.exe"
    shutil.copy2(sys.executable, executable)

    stamp_icon(executable, APPLICATION_ICON)
    stamped = executable.read_bytes()
    checksum = write_checksum(executable)

    verify_icon(executable, APPLICATION_ICON)
    assert stamped != Path(sys.executable).read_bytes()
    assert (
        checksum.read_text(encoding="utf-8").split()[0]
        == hashlib.sha256(stamped).hexdigest()
    )
